"""下载引擎常量集中定义。

v0.1.3：将散落在 ``downloader/downloader.py`` 顶部的分片下载常量与新增的
长视频时长阈值统一集中到本模块，作为下载引擎层与爬虫层共享的单一来源。

常量导入方向（设计文档 8.2 节分层职责边界）：
    - ``downloader/`` 内部模块直接从本模块导入
    - ``crawlers/`` 通过 ``from downloader.constants import ...`` 复用
      （爬虫层依赖下载引擎层提供的基础常量）
"""

from __future__ import annotations

# === 长视频类型判定 ===

# 长视频时长阈值（秒），超过此值判定为 long_video 类型
# 用户反馈 #12：长视频定义修改为超过 30 分钟
LONG_VIDEO_DURATION_THRESHOLD: int = 1800

# === 分片下载触发与切分 ===

# 大文件阈值（字节），超过此值触发分片下载
LARGE_FILE_THRESHOLD: int = 10 * 1024 * 1024  # 10MB

# 分片大小（字节）
SEGMENT_SIZE: int = 2 * 1024 * 1024  # 2MB

# 最大分片数
MAX_SEGMENTS: int = 8

# === 文件命名 ===

# 本地文件基础名最大长度（字符）
# 问题归档 #4：采用"作者名 + 源媒体标题"截取前若干字作为文件名
MAX_FILENAME_BASE_LENGTH: int = 50

# === 扩展名白名单（审计 P0-3/M7）===

# 从下载直链 URL 后缀提取扩展名时仅采用白名单内的扩展名，
# 其余（.bat/.exe/.url/.m3u8/.mpd 等）一律拒绝并回退到类型默认值，
# 封堵“任意文件写原语”的落盘扩展名通道。
ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        # 视频
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".flv",
        ".ts",
        ".m4s",
        ".avi",
        # 音频（B 站 DASH 音频流）
        ".mp3",
        ".m4a",
        ".aac",
        ".wav",
        ".ogg",
        # 图片（图集）
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".avif",
    }
)
