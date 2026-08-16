"""单项下载器模块。

实现单个 ``TaskItem`` 的下载逻辑，包括 httpx Range 请求、流式写入、
失败重试、图集并发、取消处理。严格遵循设计文档 5.2 节（下载流程）
与 5.3 节（重试策略）。

下载流程（设计文档 5.2 节）：
1. 从 SQLite 取 task_item，置为 downloading
2. 检查 .part 文件 → 读取已下载字节数（断点续传）
3. httpx Range 请求
4. 流式接收 64KB 块 → 追加写入 .part → 每 5s/1MB 持久化 → 更新进度
5. 完成 → .part 重命名为最终文件 → status=completed

重试策略（设计文档 5.3 节）：
- 网络异常 / 5xx / 461 / 412 → 重试，2^retry_count 秒指数退避
- 3 次上限 → status=failed
- 4xx（非限流）→ 直接失败不重试
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from app.logger import get_logger
from app.models import TaskItem, now_iso
from app.repositories import TaskItemRepository, TaskRepository
from downloader.constants import (
    LARGE_FILE_THRESHOLD,
    MAX_FILENAME_BASE_LENGTH,
    MAX_SEGMENTS,
    SEGMENT_SIZE,
)
from downloader.progress_reporter import ProgressReporter

if TYPE_CHECKING:
    from app.repositories import CookieRepository
    from crawlers.video_parser import VideoParser

logger = get_logger(__name__)

# === 常量（设计文档 5.2 / 5.3 节）===

# 流式接收块大小 64KB
CHUNK_SIZE: int = 64 * 1024

# 进度持久化间隔 5 秒
PERSIST_INTERVAL_SECONDS: int = 5

# 进度持久化间隔 1MB
PERSIST_INTERVAL_BYTES: int = 1024 * 1024

# 最大重试次数 3
MAX_RETRY_COUNT: int = 3

# 指数退避底数，等待 2^retry_count 秒
RETRY_BACKOFF_BASE: int = 2

# 风控限流状态码（与爬虫层一致，触发重试）
RATE_LIMITED_STATUS_CODES: frozenset[int] = frozenset({461, 412})

# WebP 资源自动转码为 MP4（ISSUE-20）
# 参与转码的扩展名集合
WEBP_EXTENSIONS: frozenset[str] = frozenset({".webp"})
# 转码目标扩展名
MP4_EXTENSION: str = ".mp4"
# FFmpeg 可执行文件名（Windows 下自动追加 .exe）
FFMPEG_EXECUTABLE: str = "ffmpeg"
# WebP 转码中的任务状态：进度条保持 100%，前端显示"转码中"
PROCESSING_STATUS: str = "processing"

# v0.1.3：分片下载常量（SEGMENT_SIZE / MAX_SEGMENTS / LARGE_FILE_THRESHOLD）
# 已移至 downloader/constants.py 集中定义，本模块通过 import 复用


@dataclass(frozen=True)
class DownloadResult:
    """单项下载结果。

    Attributes:
        success: 是否下载成功
        local_path: 成功时的本地文件路径，失败为 None
        error: 失败原因，成功为 None
    """

    success: bool
    local_path: str | None = None
    error: str | None = None


def _remove_webp_original(webp_path: str) -> None:
    """删除原 WebP 文件（转码成功后调用）。

    Args:
        webp_path: 原 WebP 文件路径
    """
    try:
        os.remove(webp_path)
    except OSError as e:
        logger.warning("删除原 WebP 文件失败: %s", e)


def _select_urls_by_indices(urls: list[str], selected_indices_str: str) -> list[str]:
    """按 selected_image_indices JSON 字符串筛选 url 列表。

    语义与 ``worker.download_bridge._filter_image_urls`` 一致；
    在 downloader 内复制以避免 downloader→worker 循环依赖。

    Args:
        urls: 全量 url 列表
        selected_indices_str: 勾选索引 JSON 数组字符串；
            空字符串表示全选；非法 JSON 按全选处理

    Returns:
        筛选后的 url 列表
    """
    if not selected_indices_str:
        return list(urls)
    try:
        indices = json.loads(selected_indices_str)
    except (json.JSONDecodeError, TypeError):
        return list(urls)
    if not isinstance(indices, list):
        return list(urls)
    return [urls[i] for i in indices if isinstance(i, int) and 0 <= i < len(urls)]


class Downloader:
    """单项下载器。

    通过 httpx Range 请求流式下载文件，支持断点续传、失败重试、图集并发。
    进度通过 ProgressReporter 节流上报，状态持久化到 SQLite。

    注意：Downloader **不**修改 status 为 paused（归 Scheduler），
    仅在下载完成时置 completed、失败时置 failed。
    """

    def __init__(
        self,
        progress_reporter: ProgressReporter,
        http_client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        conn: sqlite3.Connection,
        video_parser: VideoParser | None = None,
        cookie_repository: CookieRepository | None = None,
        webp_auto_convert: bool = True,
    ) -> None:
        """初始化下载器。

        Args:
            progress_reporter: 进度节流器
            http_client: httpx 异步客户端
            semaphore: 并发信号量（图集子任务也受此约束）
            conn: SQLite 连接（用于状态持久化与 download_dir 查询）
            video_parser: 图集直链失效时用于重新解析（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
            cookie_repository: 重新解析时取有效 Cookie（v0.1.7 plan 6.6）；
                为 None 时图集 4xx 直接失败不重新解析
            webp_auto_convert: 下载完成后是否将 WebP 文件自动转码为 MP4
        """
        self._progress_reporter = progress_reporter
        self._http_client = http_client
        self._semaphore = semaphore
        self._conn = conn
        self._item_repo = TaskItemRepository(conn)
        self._task_repo = TaskRepository(conn)
        self._video_parser = video_parser
        self._cookie_repository = cookie_repository
        self._webp_auto_convert = webp_auto_convert
        # 按目标文件路径的并发锁：防止同名目标（同一视频/图集被多次下载）
        # 并发写同一个 .part 文件导致合并阶段文件占用冲突（WinError 32）
        self._file_locks: dict[str, asyncio.Lock] = {}

    # === 路径推导 ===

    def _get_download_dir(self, task_item: TaskItem) -> Path:
        """查询 task_item 所属 task 的 download_dir。

        Args:
            task_item: 任务项

        Returns:
            下载目录 Path

        Raises:
            ValueError: task 不存在或 download_dir 为空
        """
        task = self._task_repo.get(task_item.task_id)
        if task is None or not task.download_dir:
            raise ValueError(f"task_id={task_item.task_id} 的 download_dir 为空或 task 不存在")
        return Path(task.download_dir)

    def _get_final_path(self, task_item: TaskItem, url: str, index: int | None = None) -> Path:
        """推导最终文件路径。

        命名规范（问题归档 #4）：采用"作者名 + 源媒体标题"截取前若干字
        作为本地文件名。

        - video / long_video: ``{download_dir}/{基础名}.{ext}``
        - image_set: ``{download_dir}/{基础名}/{基础名}-{index}.{ext}``

        Args:
            task_item: 任务项
            url: 下载直链（用于提取扩展名）
            index: 图集图片序号（从 1 开始），仅 image_set 使用

        Returns:
            最终文件路径
        """
        download_dir = self._get_download_dir(task_item)
        ext = self._extract_extension(url, task_item.type)
        base_name = self._build_base_name(task_item)
        if task_item.type == "image_set" and index is not None:
            target_dir = download_dir / base_name
            return target_dir / f"{base_name}-{index}{ext}"
        return download_dir / f"{base_name}{ext}"

    def _build_base_name(self, task_item: TaskItem) -> str:
        """构建本地文件基础名：作者名 + 源媒体标题。

        - 清洗 Windows 非法字符（``<>:"/\\|?*`` 及控制字符）
        - 截取前 ``MAX_FILENAME_BASE_LENGTH`` 字
        - 无作者/标题时回退到 ``aweme_id`` / ``item_{id}``

        Args:
            task_item: 任务项

        Returns:
            清洗截断后的基础名
        """
        raw = f"{task_item.author or ''}{task_item.title or ''}".strip()
        if not raw:
            return task_item.aweme_id or f"item_{task_item.id}"
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
        cleaned = cleaned.rstrip(" .").strip()
        return cleaned[:MAX_FILENAME_BASE_LENGTH] or task_item.aweme_id or f"item_{task_item.id}"

    def _get_part_path(self, final_path: Path) -> Path:
        """推导 .part 临时文件路径。

        在最终文件名后追加 ``.part`` 后缀。

        Args:
            final_path: 最终文件路径

        Returns:
            .part 临时文件路径
        """
        return Path(str(final_path) + ".part")

    @staticmethod
    def _extract_extension(url: str, item_type: str) -> str:
        """从 URL 提取文件扩展名。

        从 URL path 部分提取扩展名，无法识别时按类型给默认值。

        Args:
            url: 下载直链
            item_type: 任务项类型

        Returns:
            文件扩展名（含点号，如 ``.mp4``）
        """
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix and len(suffix) <= 5:
            return suffix
        # 默认扩展名
        if item_type == "image_set":
            return ".jpg"
        return ".mp4"

    # === 状态持久化 ===

    def _persist_progress(
        self,
        task_item_id: int,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> None:
        """持久化下载进度到 SQLite。

        更新 ``task_items.downloaded_bytes``、``total_bytes``、``updated_at``。

        Args:
            task_item_id: 任务项 ID
            downloaded_bytes: 已下载字节数
            total_bytes: 文件总字节数
        """
        self._item_repo.update_bytes(task_item_id, downloaded_bytes, total_bytes)

    def _mark_status(
        self,
        task_item_id: int,
        status: str,
        fail_reason: str | None = None,
        local_path: str | None = None,
    ) -> None:
        """更新 task_items 状态及关联字段。

        Args:
            task_item_id: 任务项 ID
            status: 新状态
            fail_reason: 失败原因（仅 failed 时使用）
            local_path: 本地文件路径（仅 completed 时使用）
        """
        now = now_iso()
        with self._conn:
            if fail_reason is not None and local_path is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, fail_reason=?, "
                    "local_path=?, updated_at=? WHERE id=?",
                    (status, fail_reason, local_path, now, task_item_id),
                )
            elif fail_reason is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, fail_reason=?, updated_at=? WHERE id=?",
                    (status, fail_reason, now, task_item_id),
                )
            elif local_path is not None:
                self._conn.execute(
                    "UPDATE task_items SET status=?, local_path=?, updated_at=? WHERE id=?",
                    (status, local_path, now, task_item_id),
                )
            else:
                self._conn.execute(
                    "UPDATE task_items SET status=?, updated_at=? WHERE id=?",
                    (status, now, task_item_id),
                )

    # === 重试判断 ===

    def _should_retry(self, status_code: int | None, exception: Exception | None) -> bool:
        """判断是否应重试（设计文档 5.3 节）。

        - 网络异常（httpx.HTTPError 子类）→ True
        - HTTP 5xx → True
        - HTTP 461 / 412（风控限流）→ True
        - HTTP 4xx（非 461/412）→ False
        - HTTP 200/206 → 不进入重试逻辑（调用方保证）

        Args:
            status_code: HTTP 状态码，网络异常时为 None
            exception: 捕获的异常，HTTP 状态码错误时为 None

        Returns:
            是否应重试
        """
        if exception is not None:
            # httpx 网络异常（ConnectError、ReadTimeout、PoolTimeout 等）
            return isinstance(exception, httpx.HTTPError)
        if status_code is not None:
            if 500 <= status_code <= 599:
                return True
            if status_code in RATE_LIMITED_STATUS_CODES:
                return True
            if 400 <= status_code <= 499:
                return False
        return False

    async def _retry_with_backoff(self, retry_count: int) -> None:
        """指数退避等待 ``2^retry_count`` 秒（2s/4s/8s）。

        Args:
            retry_count: 当前重试次数（从 1 开始）
        """
        wait_seconds = RETRY_BACKOFF_BASE**retry_count
        logger.info("等待 %d 秒后重试（第 %d 次）", wait_seconds, retry_count)
        await asyncio.sleep(wait_seconds)

    # === 文件操作 ===

    @staticmethod
    def _find_ffmpeg() -> str | None:
        """查找 FFmpeg 可执行文件。

        搜索优先级：
        1. PyInstaller 打包目录（sys._MEIPASS/ffmpeg.exe）—— CI 构建 sidecar 内嵌
        2. 可执行文件同目录（sys.executable 所在目录/ffmpeg.exe）—— 安装包分发
        3. 项目 resources/ffmpeg/（本地开发，运行 download_ffmpeg.py 后）
        4. 系统 PATH（shutil.which）—— 兜底

        Returns:
            FFmpeg 可执行文件绝对路径，未找到返回 None
        """
        # 1) PyInstaller 打包目录（sidecar 内嵌）
        if hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "ffmpeg.exe"
            if bundled.exists():
                return str(bundled)

        # 2) 可执行文件同目录（安装包分发或直接运行）
        if sys.executable:
            exe_dir = Path(sys.executable).parent
            local = exe_dir / "ffmpeg.exe"
            if local.exists():
                return str(local)

        # 3) 项目 resources/ffmpeg/（本地开发，运行 download_ffmpeg.py 后）
        project_path = (
            Path(__file__).resolve().parent.parent / "resources" / "ffmpeg" / "ffmpeg.exe"
        )
        if project_path.exists():
            return str(project_path)

        # 4) 系统 PATH（兜底）
        ffmpeg_name = FFMPEG_EXECUTABLE
        if os.name == "nt" and not ffmpeg_name.lower().endswith(".exe"):
            ffmpeg_name += ".exe"
        return shutil.which(ffmpeg_name)

    @staticmethod
    def _convert_webp_to_mp4(webp_path: str) -> str | None:
        """将 WebP/WebM 文件转码为 MP4。

        分两步的 100% 稳妥方案：
        1. 先把 WebP 每一帧导出成 PNG 序列（Pillow 解码）
           静态 WebP 仅 1 帧；动画 WebP 通过 Pillow 逐帧 seek 解码，
           不依赖 FFmpeg 原生 webp 解码器（其不支持动画 ANIM/ANMF chunks）
        2. 再用 FFmpeg 把图片序列合成 MP4（libx264 + yuv420p + faststart）

        对于 WebM（EBML 容器，VP8/VP9 视频）：FFmpeg 可直接解码，
        走 FFmpeg 直转路径（无需拆帧），产出 MP4。

        - Frame rate 取自 WebP 帧间隔 time-scale（1000/frame_duration），
          一般动图 10-20fps，检测失败时用默认 15fps
        - 先拆帧再合成：不做 FFmpeg 直转，避免直转产物为静态单帧

        Args:
            webp_path: 输入 WebP/WebM 文件路径

        Returns:
            转码后的 MP4 文件路径，转码失败或 FFmpeg 不可用时返回 None
        """
        ffmpeg = Downloader._find_ffmpeg()
        if ffmpeg is None:
            logger.warning("FFmpeg 未找到，跳过 WebP/WebM 转码: %s", webp_path)
            return None

        src = Path(webp_path)
        # 如果文件已经是 .mp4 扩展名（但内容为 WebP/WebM），加 _converted 后缀避免覆盖
        if src.suffix.lower() == MP4_EXTENSION:
            mp4_path = src.with_name(src.stem + "_converted" + MP4_EXTENSION)
        else:
            mp4_path = src.with_suffix(MP4_EXTENSION)

        # 如果同名的 MP4 已存在，跳过转码（避免重复转码）
        if mp4_path.exists():
            logger.info("MP4 文件已存在，跳过转码: %s", mp4_path)
            return str(mp4_path)

        is_webm = Downloader._is_webm_file(webp_path)

        tmp_dir: Path | None = None
        try:
            # WebM 是视频容器，FFmpeg 可直接解码转码，无需拆帧
            if is_webm:
                return Downloader._convert_webm_via_ffmpeg(
                    ffmpeg, webp_path, mp4_path, src
                )

            from PIL import Image

            img = Image.open(webp_path)
            n_frames: int = getattr(img, "n_frames", 1)

            tmp_dir = Path(tempfile.mkdtemp(prefix="webp_conv_"))
            frames_dir = tmp_dir / "frames"
            frames_dir.mkdir()

            # 检测帧率：取第一帧间隔（ANMF chunk 的 time-scale），默认 15fps
            # 动图通常 10-20fps；部分 WebP 帧间隔为 0 时按 15fps 处理
            fps: float = 15.0
            img.seek(0)
            dur = img.info.get("duration", 0)
            if dur and dur > 0:
                fps = round(1000.0 / dur)
            fps = min(max(fps, 1.0), 60.0)

            logger.info(
                "WebP 拆帧转码（Pillow 解码 %d 帧, %.1f fps）: %s → %s",
                n_frames,
                fps,
                webp_path,
                mp4_path,
            )
            for i in range(n_frames):
                img.seek(i)
                frame = img.convert("RGB")
                frame.save(str(frames_dir / f"frame_{i:04d}.png"))

            # 图片序列 → MP4（libx264 + yuv420p 保证播放器兼容）
            # -movflags +faststart：moov 原子写入文件头，保证播放器能立即读取
            # 时长/索引，否则部分播放器只解码首帧、表现为"静态图片"
            cmd = [
                ffmpeg,
                "-framerate",
                str(fps),
                "-i",
                str(frames_dir / "frame_%04d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(mp4_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                logger.error(
                    "WebP 转码失败（Pillow 解码后编码）: %s, stderr=%s",
                    webp_path,
                    result.stderr.decode("utf-8", errors="replace")[:500],
                )
                return None

            logger.info("WebP 转码完成（Pillow 解码）: %s", mp4_path)
            return str(mp4_path)

        except ImportError:
            logger.error("Pillow 未安装，无法解码 WebP: %s", webp_path)
            return None
        except Exception as e:
            logger.error("WebP 转码异常: %s, error=%s", webp_path, e)
            return None
        finally:
            if tmp_dir is not None and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _maybe_convert_webp(self, file_path: str) -> str:
        """检查文件是否为 WebP/WebM 格式，若是则自动转码为 MP4。

        检测基于文件内容的魔数（Magic Bytes），而非扩展名。
        因为抖音 CDN 返回的资源文件名可能以 .mp4 或 .jpg 结尾，
        但实际内容为 WebP（静态/动画图）或 WebM（VP8/VP9 视频）。

        Args:
            file_path: 当前文件路径

        Returns:
            转码后的文件路径（若未转码则返回原路径）
        """
        if not self._webp_auto_convert:
            return file_path
        if not file_path or not os.path.isfile(file_path):
            return file_path
        # 如果已经是 .mp4 且内容不是 WebP/WebM，跳过
        if file_path.lower().endswith(MP4_EXTENSION) and not self._is_convertible_image(
            file_path
        ):
            return file_path
        # 检测文件内容是否真的是 WebP 或 WebM
        if not self._is_convertible_image(file_path):
            return file_path
        converted = self._convert_webp_to_mp4(file_path)
        return converted if converted else file_path

    @staticmethod
    def _is_webp_file(file_path: str) -> bool:
        """通过文件魔数检测是否为 WebP 格式。

        WebP 文件头特征：
        - 字节 0-3: RIFF
        - 字节 8-11: WEBP

        Args:
            file_path: 文件路径

        Returns:
            是否为 WebP 文件
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(12)
            return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        except Exception:
            return False

    @classmethod
    def _is_convertible_image(cls, file_path: str) -> bool:
        """检测文件是否为可转码为 MP4 的资源（WebP 或 WebM）。

        判断顺序：
        1. WebP（RIFF....WEBP）—— 动图/静态图
        2. WebM（EBML 魔数 1A 45 DF A3）—— VP8/VP9 视频

        Args:
            file_path: 文件路径

        Returns:
            是 WebP 或 WebM 时返回 True
        """
        if cls._is_webp_file(file_path):
            return True
        return cls._is_webm_file(file_path)

    @staticmethod
    def _is_webm_file(file_path: str) -> bool:
        """通过文件魔数检测是否为 WebM 格式。

        WebM 使用 Matroska EBML 容器，文件头以 0x1A 0x45 0xDF 0xA3 开头。

        Args:
            file_path: 文件路径

        Returns:
            是否为 WebM 文件
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(4)
            return header == bytes([0x1A, 0x45, 0xDF, 0xA3])
        except Exception:
            return False

    @staticmethod
    def _convert_webm_via_ffmpeg(
        ffmpeg: str, webm_path: str, mp4_path: Path, src: Path
    ) -> str | None:
        """将 WebM 视频用 FFmpeg 直转编码为 MP4。

        WebM 是视频容器，FFmpeg 原生支持解码（VP8/VP9），无需拆帧，
        直接转码为 H.264 + yuv420p + faststart 保证播放器兼容。

        Args:
            ffmpeg: FFmpeg 可执行文件绝对路径
            webm_path: 输入 WebM 文件路径
            mp4_path: 输出 MP4 文件路径
            src: 输入文件 Path（用于日志）

        Returns:
            MP4 文件路径，转换失败返回 None
        """
        cmd = [
            ffmpeg,
            "-i",
            webm_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(mp4_path),
        ]
        logger.info("WebM 直转 MP4: %s → %s", src, mp4_path)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("FFmpeg 可执行文件未找到: %s", ffmpeg)
            return None
        except subprocess.TimeoutExpired:
            logger.error("WebM 转码超时 (120s): %s", webm_path)
            return None
        if result.returncode != 0:
            logger.error(
                "WebM 转码失败: %s, stderr=%s",
                webm_path,
                result.stderr.decode("utf-8", errors="replace")[:500],
            )
            return None
        logger.info("WebM 转码完成（FFmpeg 直转）: %s", mp4_path)
        return str(mp4_path)

    def _finalize_file(self, part_path: Path, final_path: Path) -> str:
        """将 .part 文件重命名为最终文件名。

        若最终文件已存在则先删除（覆盖旧文件）。

        Args:
            part_path: .part 临时文件路径
            final_path: 最终文件路径

        Returns:
            规范化后的最终文件绝对路径字符串
        """
        if final_path.exists():
            final_path.unlink()
        part_path.rename(final_path)
        # 规范化路径：转换为绝对路径并统一正斜杠，解决 Windows 路径问题
        return os.path.normpath(os.path.abspath(str(final_path)))

    # === 分片下载 ===

    async def _get_file_size(self, url: str) -> int | None:
        """通过 HEAD 请求获取文件总大小。

        Args:
            url: 下载直链

        Returns:
            文件总字节数，获取失败返回 None
        """
        try:
            response = await self._http_client.head(url)
            if response.status_code == 200:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    return int(content_length)
        except httpx.HTTPError as e:
            logger.warning("HEAD 请求获取文件大小失败: %s", e)
        return None

    @staticmethod
    def _calculate_segments(total_bytes: int) -> list[tuple[int, int]]:
        """计算分片字节范围列表。

        segment_count = min(ceil(total_bytes / SEGMENT_SIZE), MAX_SEGMENTS)
        每个分片大小 = ceil(total_bytes / segment_count)

        Args:
            total_bytes: 文件总字节数

        Returns:
            (start, end) 字节范围列表，end 为包含的末字节偏移
        """
        import math

        segment_count = min(math.ceil(total_bytes / SEGMENT_SIZE), MAX_SEGMENTS)
        segment_size = math.ceil(total_bytes / segment_count)
        segments: list[tuple[int, int]] = []
        for i in range(segment_count):
            start = i * segment_size
            end = min(start + segment_size - 1, total_bytes - 1)
            segments.append((start, end))
        return segments

    def _merge_segments(self, part_paths: list[Path], final_path: Path) -> str:
        """将分片 .part.{i} 文件按序合并为最终文件。

        合并完成后删除所有临时分片文件。

        Args:
            part_paths: 分片文件路径列表（按序号排序）
            final_path: 最终文件路径

        Returns:
            规范化后的最终文件绝对路径字符串
        """
        if final_path.exists():
            final_path.unlink()
        with open(final_path, "wb") as out:
            for part_path in part_paths:
                with open(part_path, "rb") as part:
                    while True:
                        chunk = part.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
        # 删除临时分片文件
        for part_path in part_paths:
            if part_path.exists():
                part_path.unlink()
        return os.path.normpath(os.path.abspath(str(final_path)))

    async def _download_segmented(
        self,
        task_item: TaskItem,
        url: str,
        final_path: Path,
        total_bytes: int,
    ) -> DownloadResult:
        """分片并发下载大文件。

        将文件分割为多个字节范围段，使用独立的 HTTP Range 请求并发下载。
        所有分片完成后合并为最终文件。

        Args:
            task_item: 任务项
            url: 下载直链
            final_path: 最终文件路径
            total_bytes: 文件总字节数

        Returns:
            下载结果
        """
        logger.info(
            "分片下载 task_item id=%s total_bytes=%d",
            task_item.id,
            total_bytes,
        )

        segments = self._calculate_segments(total_bytes)
        segment_count = len(segments)
        part_paths = [Path(str(final_path) + f".part.{i}") for i in range(segment_count)]
        segment_progress = [0] * segment_count

        # 进度聚合与持久化
        last_persist_time = time.monotonic()
        last_persist_bytes = 0

        def make_chunk_callback(idx: int) -> Callable[[int], None]:
            def callback(chunk_bytes: int) -> None:
                nonlocal last_persist_time, last_persist_bytes
                segment_progress[idx] += chunk_bytes
                total_downloaded = sum(segment_progress)
                self._progress_reporter.update(task_item.id, total_downloaded, total_bytes)
                now = time.monotonic()
                if (
                    now - last_persist_time >= PERSIST_INTERVAL_SECONDS
                    or total_downloaded - last_persist_bytes >= PERSIST_INTERVAL_BYTES
                ):
                    self._persist_progress(task_item.id, total_downloaded, total_bytes)
                    last_persist_time = now
                    last_persist_bytes = total_downloaded

            return callback

        # 分片信号量（不挤占主下载并发槽位）
        segment_semaphore = asyncio.Semaphore(MAX_SEGMENTS)

        async def download_one_segment(
            idx: int,
            sem: asyncio.Semaphore,
        ) -> int:
            async with sem:
                start, end = segments[idx]
                return await self._download_segment(
                    url, part_paths[idx], start, end, make_chunk_callback(idx)
                )

        try:
            results = await asyncio.gather(
                *[download_one_segment(i, segment_semaphore) for i in range(segment_count)],
                return_exceptions=True,
            )

            # 检查结果
            for i, result in enumerate(results):
                if isinstance(result, ValueError):
                    # 服务端不支持 byte-range，回退到单流下载
                    logger.warning(
                        "分片 %d 返回 200，回退到单流下载 task_item id=%s",
                        i,
                        task_item.id,
                    )
                    # 清理已下载的分片文件
                    for pp in part_paths:
                        if pp.exists():
                            pp.unlink()
                    return DownloadResult(
                        success=False,
                        error="FALLBACK_TO_SINGLE_STREAM",
                    )
                if isinstance(result, BaseException):
                    if isinstance(result, asyncio.CancelledError):
                        raise
                    reason = f"分片 {i} 下载失败: {result}"
                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                    # 清理已下载的分片文件
                    for pp in part_paths:
                        if pp.exists():
                            pp.unlink()
                    return DownloadResult(success=False, error=reason)

            # 所有分片完成 → 合并
            final_str = self._merge_segments(part_paths, final_path)
            # WebP 自动转码（ISSUE-20）
            # 转码前上报 processing 进度：进度条保持 100%，前端显示"转码中"
            self._progress_reporter.update(
                task_item.id,
                total_bytes,
                total_bytes,
                status=PROCESSING_STATUS,
            )
            final_str = self._maybe_convert_webp(final_str)
            self._mark_status(task_item.id, "completed", local_path=final_str)
            # 最终持久化一次
            self._persist_progress(task_item.id, total_bytes, total_bytes)
            logger.info("分片下载完成 task_item id=%s path=%s", task_item.id, final_str)
            return DownloadResult(success=True, local_path=final_str)

        except asyncio.CancelledError:
            # 暂停/取消：持久化进度，保留 .part 文件
            total_downloaded = sum(segment_progress)
            self._persist_progress(task_item.id, total_downloaded, total_bytes)
            logger.info(
                "分片下载被取消 task_item id=%s 已保存进度 %d bytes",
                task_item.id,
                total_downloaded,
            )
            raise

    # === 下载主流程 ===

    async def download(self, task_item: TaskItem) -> DownloadResult:
        """单项下载主入口（设计文档 5.2 节）。

        根据 type 分发到单文件或图集下载流程。
        image_set 类型的 url 字段以换行符分隔多个图片 URL。

        Args:
            task_item: 待下载任务项

        Returns:
            下载结果
        """
        self._mark_status(task_item.id, "downloading")
        logger.info(
            "开始下载 task_item id=%s aweme_id=%s type=%s",
            task_item.id,
            task_item.aweme_id,
            task_item.type,
        )

        if task_item.type == "image_set":
            urls = [u.strip() for u in task_item.url.split("\n") if u.strip()]
            if not urls:
                self._mark_status(task_item.id, "failed", fail_reason="图集 URL 为空")
                return DownloadResult(success=False, error="图集 URL 为空")
            final_path = self._get_final_path(task_item, urls[0], index=1)
            target_dir = final_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            # 图集：按目标文件夹串行化，防止同名图集并发写冲突
            lock = self._file_locks.setdefault(str(target_dir), asyncio.Lock())
            async with lock:
                return await self._download_image_set(task_item, urls, target_dir)

        final_path = self._get_final_path(task_item, task_item.url)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        # 视频：按目标文件串行化，防止同名目标并发写 .part 冲突
        lock = self._file_locks.setdefault(str(final_path), asyncio.Lock())
        async with lock:
            return await self._download_single_file(task_item, task_item.url, final_path)

    async def _download_single_file(
        self,
        task_item: TaskItem,
        url: str,
        final_path: Path,
        mark_status: bool = True,
        report_progress: bool = True,
    ) -> DownloadResult:
        """单文件下载（视频/长视频/图集单张）。

        含 Range 续传、流式写入、重试。受总 Semaphore 约束。
        大文件（≥10MB）自动切换为分片并发下载。

        Args:
            task_item: 任务项
            url: 下载直链
            final_path: 最终文件路径
            mark_status: 是否在完成/失败时标记 task_items 状态。
                图集子下载设为 False，由 _download_image_set 统一标记。
            report_progress: 是否上报字节级进度。
                v0.1.7：图集子下载设为 False，由 _download_image_set
                按"M/N 张"粒度上报，避免字节进度覆盖张数进度。

        Returns:
            下载结果
        """
        part_path = self._get_part_path(final_path)
        retry_count = task_item.retry_count

        # 大文件分片下载探测
        file_size = await self._get_file_size(url)
        if file_size is not None and file_size >= LARGE_FILE_THRESHOLD and not part_path.exists():
            async with self._semaphore:
                result = await self._download_segmented(task_item, url, final_path, file_size)
            if result.success or result.error != "FALLBACK_TO_SINGLE_STREAM":
                return result
            # 回退到单流下载
            logger.info("回退到单流下载 task_item id=%s", task_item.id)

        async with self._semaphore:
            while True:
                # 检查 .part 文件是否存在 → 读取已下载字节数（断点续传）
                downloaded_bytes = part_path.stat().st_size if part_path.exists() else 0

                # 构造 Range 请求头
                headers: dict[str, str] = {}
                if downloaded_bytes > 0:
                    headers["Range"] = f"bytes={downloaded_bytes}-"

                try:
                    async with self._http_client.stream("GET", url, headers=headers) as response:
                        # ISSUE-20 诊断：记录响应 Content-Type，识别 CDN 返回
                        # WebP 缩略图占位（本应返回 video_mp4 却给了 image/webp）
                        resp_content_type = response.headers.get("Content-Type", "").lower()
                        if "webp" in resp_content_type or "image" in resp_content_type:
                            logger.warning(
                                "下载响应为图片而非视频: url=%s content_type=%s status=%d",
                                url[:200],
                                resp_content_type,
                                response.status_code,
                            )
                        if response.status_code == 200:
                            # 服务端不支持 Range 或文件已变，从头下载
                            downloaded_bytes = 0
                        elif response.status_code == 206:
                            pass  # 续传成功
                        elif self._should_retry(response.status_code, None):
                            # 可重试错误（5xx / 461 / 412）
                            retry_count += 1
                            self._item_repo.update_retry(task_item.id, retry_count)
                            if retry_count > MAX_RETRY_COUNT:
                                reason = f"HTTP {response.status_code} 重试耗尽"
                                if mark_status:
                                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                                return DownloadResult(success=False, error=reason)
                            logger.warning(
                                "HTTP %d，第 %d 次重试 task_item id=%s",
                                response.status_code,
                                retry_count,
                                task_item.id,
                            )
                            await self._retry_with_backoff(retry_count)
                            continue
                        else:
                            # 不可重试错误（4xx 非限流）
                            reason = f"HTTP {response.status_code}"
                            if mark_status:
                                self._mark_status(task_item.id, "failed", fail_reason=reason)
                            return DownloadResult(success=False, error=reason)

                        # 流式接收
                        content_length = int(response.headers.get("Content-Length", 0))
                        total_bytes = downloaded_bytes + content_length
                        downloaded_bytes = await self._stream_to_file(
                            response,
                            part_path,
                            task_item,
                            downloaded_bytes,
                            total_bytes,
                            report_progress=report_progress,
                        )

                    # 下载完成 → 重命名 → 标记完成
                    final_str = self._finalize_file(part_path, final_path)
                    # WebP 自动转码（ISSUE-20）
                    if mark_status:
                        # 转码前上报 processing 进度：进度条保持 100%，前端显示"转码中"
                        self._progress_reporter.update(
                            task_item.id,
                            downloaded_bytes,
                            total_bytes,
                            status=PROCESSING_STATUS,
                        )
                    final_str = self._maybe_convert_webp(final_str)
                    if mark_status:
                        self._mark_status(task_item.id, "completed", local_path=final_str)
                    logger.info("下载完成 task_item id=%s path=%s", task_item.id, final_str)
                    return DownloadResult(success=True, local_path=final_str)

                except asyncio.CancelledError:
                    # 暂停/取消：持久化进度，保留 .part 文件，不修改 status（归 Scheduler）
                    # _stream_to_file 可能已持久化更准确的值，此处读 .part 实际大小兜底
                    actual_bytes = part_path.stat().st_size if part_path.exists() else 0
                    total = total_bytes if "total_bytes" in locals() else 0
                    self._persist_progress(task_item.id, actual_bytes, total)
                    logger.info(
                        "下载被取消 task_item id=%s 已保存进度 %d bytes",
                        task_item.id,
                        actual_bytes,
                    )
                    raise

                except httpx.HTTPError as e:
                    # 网络异常 → 重试
                    retry_count += 1
                    self._item_repo.update_retry(task_item.id, retry_count)
                    if retry_count > MAX_RETRY_COUNT:
                        reason = f"网络异常重试耗尽: {e}"
                        if mark_status:
                            self._mark_status(task_item.id, "failed", fail_reason=reason)
                        return DownloadResult(success=False, error=reason)
                    logger.warning(
                        "网络异常 %s，第 %d 次重试 task_item id=%s",
                        e,
                        retry_count,
                        task_item.id,
                    )
                    await self._retry_with_backoff(retry_count)
                    continue

    async def _stream_to_file(
        self,
        response: httpx.Response,
        part_path: Path,
        task_item: TaskItem,
        downloaded_bytes: int,
        total_bytes: int,
        report_progress: bool = True,
    ) -> int:
        """流式接收响应体写入 .part 文件。

        每块 64KB 追加写入、更新内存计数、每 5s/1MB 持久化、更新 ProgressReporter。
        捕获 CancelledError 时持久化进度后重抛。

        Args:
            response: httpx 流式响应
            part_path: .part 临时文件路径
            task_item: 任务项
            downloaded_bytes: 起始已下载字节数（断点续传）
            total_bytes: 文件总字节数
            report_progress: 是否上报字节级进度。
                v0.1.7：图集子下载传 False，避免覆盖 _download_image_set
                按"M/N 张"粒度上报的进度。

        Returns:
            最终已下载字节数
        """
        last_persist_time = time.monotonic()
        last_persist_bytes = downloaded_bytes
        # downloaded_bytes == 0 表示从头下载（新文件或服务端返回 200 不支持 Range）
        # → 用 "wb" 截断旧 .part 内容；否则 "ab" 续传追加。
        mode = "wb" if downloaded_bytes == 0 else "ab"

        try:
            with open(part_path, mode) as f:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    # 更新进度（节流器内部去重）
                    if report_progress:
                        self._progress_reporter.update(
                            task_item.id,
                            downloaded_bytes,
                            total_bytes,
                            status="downloading",
                        )
                    # 检查持久化条件：5 秒 或 1MB
                    now = time.monotonic()
                    if (
                        now - last_persist_time >= PERSIST_INTERVAL_SECONDS
                        or downloaded_bytes - last_persist_bytes >= PERSIST_INTERVAL_BYTES
                    ):
                        self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
                        last_persist_time = now
                        last_persist_bytes = downloaded_bytes
        except asyncio.CancelledError:
            # 持久化进度后重抛（设计文档 5.4 节）
            self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
            raise

        # 最终持久化一次
        self._persist_progress(task_item.id, downloaded_bytes, total_bytes)
        return downloaded_bytes

    async def _download_segment(
        self,
        url: str,
        part_path: Path,
        start: int,
        end: int,
        on_chunk: Callable[[int], None],
    ) -> int:
        """下载单个分片到 .part.{index} 文件。

        含 Range 续传、流式写入、独立重试。

        Args:
            url: 下载直链
            part_path: 分片临时文件路径（.part.{index}）
            start: 分片起始字节（包含）
            end: 分片结束字节（包含）
            on_chunk: 每接收一个数据块的回调，参数为本块字节数

        Returns:
            该分片已下载的总字节数

        Raises:
            ValueError: 服务端返回 200 而非 206（不支持 byte-range）
            httpx.HTTPError: 重试耗尽后的网络异常
        """
        retry_count = 0

        while True:
            # 检查 .part 文件是否存在 → 读取已下载字节数（断点续传）
            downloaded = part_path.stat().st_size if part_path.exists() else 0
            segment_start = start + downloaded

            headers: dict[str, str] = {}
            if downloaded > 0:
                headers["Range"] = f"bytes={segment_start}-{end}"
            else:
                headers["Range"] = f"bytes={start}-{end}"

            try:
                async with self._http_client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 200:
                        # 服务端不支持 byte-range，无法分片下载
                        raise ValueError("服务端返回 200 而非 206，不支持 byte-range 分片下载")
                    elif response.status_code == 206:
                        pass  # 分片请求成功
                    elif self._should_retry(response.status_code, None):
                        retry_count += 1
                        if retry_count > MAX_RETRY_COUNT:
                            raise httpx.HTTPError(f"HTTP {response.status_code} 重试耗尽")
                        logger.warning(
                            "分片 HTTP %d，第 %d 次重试",
                            response.status_code,
                            retry_count,
                        )
                        await self._retry_with_backoff(retry_count)
                        continue
                    else:
                        raise httpx.HTTPError(f"HTTP {response.status_code}")

                    # 流式接收
                    mode = "ab" if downloaded > 0 else "wb"
                    with open(part_path, mode) as f:
                        async for chunk in response.aiter_bytes(CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)
                            on_chunk(len(chunk))

                return downloaded

            except asyncio.CancelledError:
                raise
            except ValueError:
                raise
            except httpx.HTTPError as e:
                retry_count += 1
                if retry_count > MAX_RETRY_COUNT:
                    raise
                logger.warning(
                    "分片网络异常 %s，第 %d 次重试",
                    e,
                    retry_count,
                )
                await self._retry_with_backoff(retry_count)
                continue

    # === 图集直链失效重新解析（v0.1.7 plan 6.6）===

    def _is_link_expired(self, error: str | None) -> bool:
        """判断下载失败原因是否为图片直链失效（403/404）。

        Args:
            error: ``DownloadResult.error`` 字符串

        Returns:
            失效返回 True（可重新解析），其他错误返回 False
        """
        if not error:
            return False
        return "HTTP 403" in error or "HTTP 404" in error

    def _can_reparse(self) -> bool:
        """是否具备图片直链重新解析能力。

        需要 ``video_parser`` 和 ``cookie_repository`` 同时注入。
        """
        return self._video_parser is not None and self._cookie_repository is not None

    def _get_cookie_string(self) -> str | None:
        """从 Cookie 池取一个有效 Cookie 字符串。

        Returns:
            Cookie ``content`` 字符串；无可用 Cookie 返回 None
        """
        if self._cookie_repository is None:
            return None
        cookie = self._cookie_repository.get_valid()
        return cookie.content if cookie else None

    async def _reparse_single_image_url(
        self,
        task_item: TaskItem,
        idx: int,
    ) -> str | None:
        """图片直链失效时重新解析，返回指定索引的新 url。

        按 plan 6.6：调用 ``VideoParser.parse_video`` 重新获取全量 image_urls，
        再按 ``task_item.selected_image_indices`` 重新筛选，取第 idx 个。
        重新解析失败返回 None（由调用方按原失败结果处理）。

        Args:
            task_item: 任务项
            idx: 在已筛选子集中的 0-based 索引

        Returns:
            新的图片直链；无法重新解析返回 None
        """
        if not self._can_reparse():
            return None
        if task_item.aweme_id is None:
            logger.warning(
                "aweme_id 为空，无法重新解析 task_item id=%s",
                task_item.id,
            )
            return None
        cookie = self._get_cookie_string()
        if cookie is None:
            logger.warning(
                "无可用 Cookie，无法重新解析 task_item id=%s",
                task_item.id,
            )
            return None
        try:
            video_info = await self._video_parser.parse_video(task_item.aweme_id, cookie)
        except Exception as e:
            logger.warning(
                "图片直链重新解析失败 task_item id=%s: %s",
                task_item.id,
                e,
            )
            return None
        new_all_urls = list(video_info.image_urls or [])
        new_selected = _select_urls_by_indices(new_all_urls, task_item.selected_image_indices)
        if 0 <= idx < len(new_selected):
            return new_selected[idx]
        logger.warning(
            "重新解析后索引 %d 越界（共 %d 张）task_item id=%s",
            idx,
            len(new_selected),
            task_item.id,
        )
        return None

    async def _download_image_set(
        self,
        task_item: TaskItem,
        urls: list[str],
        target_dir: Path,
    ) -> DownloadResult:
        """图集并发下载（设计文档 5.2 节 + 2.4 节）。

        对每个 URL 创建 _download_single_file 子任务，asyncio.gather 并发执行。
        每个子任务受总 Semaphore 约束。任一失败 → 整个图集标记 failed。

        v0.1.7：子下载设 ``report_progress=False``，由本方法按"M/N 张"粒度
        上报进度，避免字节级进度覆盖张数进度。每张图片子下载完成时调用
        ``progress_reporter.update(task_item.id, 已下载张数, 总张数)``，
        UI 端 ``TaskItemWidget`` 据此显示"已下载 M/N 张"。

        Args:
            task_item: 任务项
            urls: 图片直链列表
            target_dir: 图集目标目录

        Returns:
            下载结果（成功时 local_path 为目录路径）
        """
        logger.info(
            "图集下载 task_item id=%s 共 %d 张图片",
            task_item.id,
            len(urls),
        )
        total_images = len(urls)
        # 初始进度：0 张已完成
        self._progress_reporter.update(task_item.id, 0, total_images)

        # 已完成图片数计数器与锁（gather 并发完成回调需同步）
        completed_count = 0
        completed_lock = asyncio.Lock()

        async def _download_one(seq: int, url: str) -> DownloadResult:
            nonlocal completed_count
            final_path = self._get_final_path(task_item, url, index=seq)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            result = await self._download_single_file(
                task_item,
                url,
                final_path,
                mark_status=False,
                report_progress=False,
            )
            # 图片直链失效重新解析（v0.1.7 plan 6.6）
            if not result.success and self._is_link_expired(result.error):
                # seq 为 1-based 序号，转 0-based 索引取重新解析后的 url
                new_url = await self._reparse_single_image_url(task_item, seq - 1)
                if new_url is not None:
                    logger.info(
                        "图片 %d 直链失效，重新解析后重试 task_item id=%s",
                        seq,
                        task_item.id,
                    )
                    result = await self._download_single_file(
                        task_item,
                        new_url,
                        final_path,
                        mark_status=False,
                        report_progress=False,
                    )
            if result.success:
                async with completed_lock:
                    completed_count += 1
                    self._progress_reporter.update(
                        task_item.id,
                        completed_count,
                        total_images,
                    )
            return result

        tasks: list = [_download_one(i, url) for i, url in enumerate(urls, 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查结果：任一失败 → 整个图集失败
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                if not isinstance(result, asyncio.CancelledError):
                    reason = f"图片 {i + 1} 下载异常: {result}"
                    self._mark_status(task_item.id, "failed", fail_reason=reason)
                    return DownloadResult(success=False, error=reason)
                raise result
            if not result.success:
                reason = f"图片 {i + 1} 下载失败: {result.error}"
                self._mark_status(task_item.id, "failed", fail_reason=reason)
                return DownloadResult(success=False, error=reason)

        # 全部成功
        local_path = os.path.normpath(os.path.abspath(str(target_dir)))
        self._mark_status(task_item.id, "completed", local_path=local_path)
        logger.info("图集下载完成 task_item id=%s path=%s", task_item.id, local_path)
        return DownloadResult(success=True, local_path=local_path)
