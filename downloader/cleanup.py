"""磁盘清理工具（审计 S3/N3）。

提供两类清理：
    1. 任务删除时的**关联文件**安全删除：delete_task_item / delete_task
       顺带清理成品文件与 .part 残留（打破“只删数据库行”的旧语义，
       见 guide §P1「删除任务物理删除文件」）；删除前做目录包含性校验
       （commonpath 包含于任务 download_dir），越界路径一律拒绝。
    2. 启动期孤儿 .part 扫描：清理超过 max_age_days 未更新的 .part 文件
       （进程崩溃 / 任务删除残留），避免磁盘垃圾累积。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# 孤儿 .part 清理的默认最大存活天数
ORPHAN_PART_MAX_AGE_DAYS: int = 7


def _is_contained(path: Path, base: Path) -> bool:
    """判断 path 是否位于 base 目录之内（审计 S3：越界即拒绝）。

    参数:
        path: 待删除目标（文件或目录）。
        base: 允许删除的根目录。

    返回:
        path 位于 base 内返回 True；base 无效或 path 越界返回 False。
    """
    try:
        resolved_base = base.resolve(strict=False)
        resolved_path = path.resolve(strict=False)
        return os.path.commonpath(
            [str(resolved_base), str(resolved_path)]
        ) == str(resolved_base)
    except (OSError, ValueError):
        return False


def safe_remove_output(target: str | Path, base_dir: str | Path) -> bool:
    """安全删除单个下载产物（文件或图集目录），带目录包含性校验。

    参数:
        target: 本地产物路径（local_path 值）。
        base_dir: 允许删除的根目录（任务的 download_dir）。

    返回:
        删除成功（或目标本就不存在，视为成功清理）返回 True；
        越界/校验失败返回 False（调用方仅记日志，不抛错中断删除流程）。
    """
    target_path = Path(target)
    base = Path(base_dir)
    if not _is_contained(target_path, base):
        logger.warning(
            "拒绝删除越界路径 target=%s base=%s（跳过）",
            target_path,
            base,
        )
        return False
    if not target_path.exists():
        return True  # 已不存在，无需处理
    try:
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
        # 顺带清理同名 .part 残留（视频断点续传临时文件）
        part_path = target_path.with_name(target_path.name + ".part")
        if part_path.exists():
            part_path.unlink(missing_ok=True)
        logger.info("已清理下载产物: %s", target_path)
        return True
    except OSError as exc:
        # 文件可能正被占用（WinError 32）：记录日志，不中断后续删除
        logger.warning("清理产物失败 %s: %s", target_path, exc)
        return False


def sweep_orphan_part_files(
    download_dir: str | Path,
    max_age_days: int = ORPHAN_PART_MAX_AGE_DAYS,
) -> int:
    """扫描下载目录，清理超过 max_age_days 未更新的孤儿 .part 文件。

    仅在启动期由 app.py 调用一次。扫描只删除 ``*.part`` 后缀文件，
    不影响正常下载中的 .part（它们会被持续写入、mtime 较新）。

    参数:
        download_dir: 配置的下载目录（仅扫描该目录，防御误删其他位置）。
        max_age_days: 超过该天数的 .part 视为孤儿。

    返回:
        清理的文件数量。
    """
    base = Path(download_dir)
    if not base.is_dir():
        return 0
    cutoff = time_now() - max_age_days * 86400
    removed = 0
    for part_path in base.rglob("*.part"):
        try:
            if part_path.stat().st_mtime < cutoff:
                part_path.unlink(missing_ok=True)
                removed += 1
                logger.info("已清理孤儿 .part: %s", part_path)
        except OSError as exc:
            logger.warning("清理孤儿 .part 失败 %s: %s", part_path, exc)
    if removed:
        logger.info("孤儿 .part 清理完成，共 %d 个", removed)
    return removed


def time_now() -> float:
    """返回当前时间戳（便于测试注入）。"""
    import time

    return time.time()
