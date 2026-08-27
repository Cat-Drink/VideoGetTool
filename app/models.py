"""数据模型定义。

定义 5 个 dataclass 与 5 个枚举类型，作为数据层与上层之间的数据载体。
dataclass 字段与 SQLite 表列一一对应。

设计约束：
- dataclass 不含业务方法（纯数据载体），所有数据库操作在 Repository 层
- 枚举值与 SQLite 中存储的字符串完全一致，Repository 存取时直接用 .value 或字符串
- id 字段为 int | None，新建时传 None，由 SQLite 自增填充
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# === 枚举类型 ===
# 继承 StrEnum（Python 3.11+），便于直接序列化为 SQLite TEXT
# v0.2.1：由 (str, Enum) 迁移至 StrEnum，修复 ruff UP042 并恢复 3.11 前格式化行为


class TaskStatus(StrEnum):
    """任务状态。"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskItemStatus(StrEnum):
    """任务项状态（与 TaskStatus 一致）。"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceType(StrEnum):
    """任务来源类型。"""

    SINGLE = "single"  # 单链接
    BATCH = "batch"  # 批量链接
    USER_HOME = "user_home"  # 主页抓取
    FILE_IMPORT = "file_import"  # 文件导入


class VideoType(StrEnum):
    """视频类型。"""

    VIDEO = "video"  # 普通短视频
    IMAGE_SET = "image_set"  # 图文
    LONG_VIDEO = "long_video"  # 长视频


class CookieStatus(StrEnum):
    """Cookie 状态。"""

    VALID = "valid"  # 有效
    INVALID = "invalid"  # 失效
    UNTESTED = "untested"  # 未测试


# === dataclass 定义 ===
# 字段顺序与表列顺序一致，可变默认值用 field(default=...)


@dataclass
class Task:
    """任务表对应数据类。"""

    id: int | None
    source_type: str
    source_url: str | None
    status: str
    total_items: int = 0
    completed_items: int = 0
    created_at: str = ""
    updated_at: str = ""
    download_dir: str = ""


@dataclass
class TaskItem:
    """任务项表对应数据类。"""

    id: int | None
    task_id: int
    aweme_id: str | None
    url: str
    title: str | None = None
    author: str | None = None
    author_sec_id: str | None = None
    type: str = ""
    duration: str | None = None
    image_count: int | None = None
    cover_url: str | None = None
    status: str = "pending"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    retry_count: int = 0
    fail_reason: str | None = None
    local_path: str | None = None
    # v0.1.7：图片级勾选状态持久化（JSON 数组，如 "[0,1,3]"；空字符串表示全选）
    selected_image_indices: str = ""
    # v0.2.x：逐项媒体类型（JSON 数组，如 '["image","video","image"]'；空字符串表示全为静态图片）
    item_types: str = ""
    # v0.4.0：B 站支持专用字段
    bvid: str | None = None  # B 站视频 BV 号
    cid: int | None = None  # 分 P 的 cid（多 P 时区分）
    page: int = 0  # 分 P 序号（0 表示不分 P）
    audio_url: str = ""  # DASH 音频流 URL（B 站 DASH 格式）
    dash_merged: str = ""  # DASH 音频流是否已合并（'' 未合并 / '1' 已合并）
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Cookie:
    """Cookie 表对应数据类。"""

    id: int | None
    content: str
    label: str | None = None
    status: str = "untested"
    last_used: str | None = None
    last_check: str | None = None
    fail_count: int = 0
    created_at: str = ""


@dataclass
class Metadata:
    """元数据表对应数据类。"""

    id: int | None
    task_item_id: int
    aweme_id: str | None = None
    title: str | None = None
    desc: str | None = None
    author: str | None = None
    author_uid: str | None = None
    publish_time: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    collect_count: int | None = None
    tags: str | None = None
    raw_json: str | None = None


@dataclass
class Config:
    """配置表对应数据类。"""

    key: str
    value: str


# === 时间戳辅助 ===


def now_iso() -> str:
    """返回当前时间的 ISO8601 字符串。

    供 Repository 在 created_at/updated_at 字段使用，保证全应用时间格式统一。
    """
    return datetime.now().isoformat()
