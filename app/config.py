"""全局配置常量与默认值。

统一管理 APPDATA 路径、数据库/日志文件位置、用户可调参数的默认值，
并提供目录自动创建逻辑。所有路径用 pathlib.Path，保证跨平台路径分隔符正确。

注意：本模块不读取数据库配置，避免循环依赖。
数据库默认值在 database.py 初始化时从 DEFAULT_CONFIGS 插入。
"""

from __future__ import annotations

import os
from pathlib import Path

# === APPDATA 路径常量 ===
# Windows 下 %APPDATA% 指向用户应用数据目录；非 Windows 环境回退到用户主目录
APP_DATA_DIR: Path = Path(os.environ.get("APPDATA", str(Path.home()))) / "XieFengShiYing"
DB_PATH: Path = APP_DATA_DIR / "data.db"
LOG_DIR: Path = APP_DATA_DIR / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"
DEFAULT_DOWNLOAD_DIR: Path = Path.home() / "Downloads" / "XieFengShiYing"

# === 默认配置值 ===
# 与 config 表键值对应，用于首次初始化插入
DEFAULT_CONCURRENCY: int = 3  # 并发下载数，1-10
DEFAULT_CHUNK_SIZE: int = 1024 * 1024  # 1MB，单文件分块大小
DEFAULT_RETRY_COUNT: int = 3  # 失败重试次数，固定不可改
DEFAULT_METADATA_FORMAT: str = "json"  # 元数据保存格式
DEFAULT_WEBP_AUTO_CONVERT: bool = True  # WebP 资源自动转码为 MP4

# 聚合默认配置，键为 config 表的 key，值均为字符串
DEFAULT_CONFIGS: dict[str, str] = {
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "concurrency": str(DEFAULT_CONCURRENCY),
    "chunk_size": str(DEFAULT_CHUNK_SIZE),
    "retry_count": str(DEFAULT_RETRY_COUNT),
    "metadata_format": DEFAULT_METADATA_FORMAT,
    "webp_auto_convert": str(DEFAULT_WEBP_AUTO_CONVERT).lower(),
    "onboarding_done": "false",
}


def ensure_app_dirs() -> None:
    """确保 APP_DATA_DIR 和 LOG_DIR 存在，不存在则创建。

    在应用启动时调用，本里程碑由测试间接验证。
    """
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
