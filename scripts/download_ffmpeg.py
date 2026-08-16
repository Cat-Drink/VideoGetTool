"""FFmpeg 静态二进制下载脚本。

从 gyan.dev 官方发布页下载 Windows 静态编译版 FFmpeg，解压其中的
``ffmpeg.exe`` 到项目 ``resources/ffmpeg/`` 目录，供本地开发与 CI 打包使用。

下载地址：https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
（Essentials 精简版，约 50MB，仅含 ffmpeg.exe / ffprobe.exe，无 DLL 依赖）

如果网络下载失败，自动回退到从 imageio-ffmpeg 包复制内置的 FFmpeg 二进制。

用法：
    python scripts/download_ffmpeg.py            # 下载并解压到 resources/ffmpeg/
    python scripts/download_ffmpeg.py --check    # 仅检测是否已下载（CI 用）
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

# FFmpeg 官方 Windows 静态构建（Essentials 精简版）
FFMPEG_URL: str = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 项目资源目录（脚本位于 scripts/ 下，上一级为项目根目录）
RESOURCES_DIR: Path = Path(__file__).resolve().parent.parent / "resources"
FFMPEG_DIR: Path = RESOURCES_DIR / "ffmpeg"
FFMPEG_EXE: Path = FFMPEG_DIR / "ffmpeg.exe"


def _download(url: str, dest: Path) -> None:
    """下载 URL 到指定路径，输出进度信息。"""
    print(f"下载 FFmpeg: {url}")
    print(f"保存到临时文件: {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total:
                percent = downloaded * 100 // total
                print(f"\r  进度: {percent}% ({downloaded // 1024}KB / {total // 1024}KB)", end="")
    print("\n下载完成")


def extract_ffmpeg(zip_path: Path) -> None:
    """从 zip 中提取 ffmpeg.exe 到 resources/ffmpeg/。"""
    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # 在 zip 中查找 ffmpeg.exe（路径形如 ffmpeg-x.y.z-essentials_build/bin/ffmpeg.exe）
        ffmpeg_members = [m for m in zf.namelist() if m.endswith("/bin/ffmpeg.exe")]
        if not ffmpeg_members:
            raise RuntimeError(f"zip 中未找到 ffmpeg.exe，成员: {zf.namelist()[:5]}...")
        # 取第一个匹配
        member = ffmpeg_members[0]
        print(f"提取 {member} → {FFMPEG_EXE}")
        with zf.open(member) as src, open(FFMPEG_EXE, "wb") as out:
            out.write(src.read())
    print(f"FFmpeg 已就绪: {FFMPEG_EXE}")


def _try_imageio_fallback() -> bool:
    """尝试从 imageio-ffmpeg 包复制内置 FFmpeg 二进制。"""
    try:
        import imageio_ffmpeg

        src = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"从 imageio-ffmpeg 复制 FFmpeg: {src}")
        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(src, FFMPEG_EXE)
        print(f"FFmpeg 已就绪: {FFMPEG_EXE}")
        return True
    except ImportError:
        print("imageio-ffmpeg 未安装，可通过 pip install imageio-ffmpeg 安装", file=sys.stderr)
        return False
    except (RuntimeError, OSError) as e:
        print(f"从 imageio-ffmpeg 复制 FFmpeg 失败: {e}", file=sys.stderr)
        return False


def ensure_ffmpeg() -> bool:
    """确保 FFmpeg 可用，返回是否成功。"""
    if FFMPEG_EXE.exists():
        print(f"FFmpeg 已存在: {FFMPEG_EXE}")
        return True

    print("FFmpeg 未找到，开始下载...")
    tmp_zip = FFMPEG_DIR / "ffmpeg.zip"
    try:
        _download(FFMPEG_URL, tmp_zip)
        extract_ffmpeg(tmp_zip)
        return True
    except Exception as e:
        print(f"下载/解压 FFmpeg 失败: {e}", file=sys.stderr)
        print("尝试回退到 imageio-ffmpeg...", file=sys.stderr)
        return _try_imageio_fallback()
    finally:
        # 清理临时 zip
        if tmp_zip.exists():
            tmp_zip.unlink()


def main() -> int:
    """脚本入口。"""
    parser = argparse.ArgumentParser(description="下载 FFmpeg 静态二进制到 resources/ffmpeg/")
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检测 FFmpeg 是否已下载，不执行下载（用于 CI 判断）",
    )
    args = parser.parse_args()

    if args.check:
        if FFMPEG_EXE.exists():
            print("FFmpeg 已存在")
            return 0
        print("FFmpeg 不存在", file=sys.stderr)
        return 1

    return 0 if ensure_ffmpeg() else 1


if __name__ == "__main__":
    sys.exit(main())
