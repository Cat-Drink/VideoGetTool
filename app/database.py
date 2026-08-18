"""数据库管理模块。

实现 SQLite 连接管理、表初始化（5 张业务表 + 1 张 schema_version 表）、
6 个索引创建、默认配置插入、基于 schema_version 的迁移框架。

表结构 DDL 与设计文档 4.1 节完全一致。

线程安全考量：
- SQLite 连接不跨线程共享，每个工作线程自行调用 get_connection()
- get_connection 设 check_same_thread=False，由调用方保证线程安全
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from app import config
from app.models import now_iso

# === Schema 版本 ===
SCHEMA_VERSION: int = 2

# === 建表 SQL（与设计文档 4.1 节完全一致）===
CREATE_TASKS_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL,
    source_url      TEXT,
    status          TEXT NOT NULL,
    total_items     INTEGER DEFAULT 0,
    completed_items INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    download_dir    TEXT NOT NULL
)
"""

CREATE_TASK_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS task_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    aweme_id        TEXT,
    url             TEXT NOT NULL,
    title           TEXT,
    author          TEXT,
    author_sec_id   TEXT,
    type            TEXT NOT NULL,
    duration        TEXT,
    image_count     INTEGER,
    cover_url       TEXT,
    status          TEXT NOT NULL,
    downloaded_bytes INTEGER DEFAULT 0,
    total_bytes     INTEGER DEFAULT 0,
    retry_count     INTEGER DEFAULT 0,
    fail_reason     TEXT,
    local_path      TEXT,
    selected_image_indices TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

CREATE_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_item_id    INTEGER NOT NULL REFERENCES task_items(id) ON DELETE CASCADE,
    aweme_id        TEXT,
    title           TEXT,
    desc            TEXT,
    author          TEXT,
    author_uid      TEXT,
    publish_time    TEXT,
    like_count      INTEGER,
    comment_count   INTEGER,
    share_count     INTEGER,
    collect_count   INTEGER,
    tags            TEXT,
    raw_json        TEXT
)
"""

CREATE_COOKIES_SQL = """
CREATE TABLE IF NOT EXISTS cookies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    label       TEXT,
    status      TEXT NOT NULL,
    last_used   TEXT,
    last_check  TEXT,
    fail_count  INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
)
"""

CREATE_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

CREATE_SCHEMA_VERSION_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""

# 6 个索引
CREATE_INDEXES_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_task_items_task_id ON task_items(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_items_status ON task_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_task_items_aweme_id ON task_items(aweme_id)",
    "CREATE INDEX IF NOT EXISTS idx_cookies_status ON cookies(status)",
    "CREATE INDEX IF NOT EXISTS idx_metadata_task_item_id ON metadata(task_item_id)",
]

# 所有建表 SQL（顺序：先父表后子表，保证外键引用有效）
_ALL_CREATE_TABLE_SQL: list[str] = [
    CREATE_TASKS_SQL,
    CREATE_TASK_ITEMS_SQL,
    CREATE_METADATA_SQL,
    CREATE_COOKIES_SQL,
    CREATE_CONFIG_SQL,
    CREATE_SCHEMA_VERSION_SQL,
]

# === 迁移框架 ===
# 迁移函数注册：MIGRATIONS[N] = 函数，负责版本 N-1 → N 的 DDL
# v1 由 init_db 直接建表，无迁移逻辑；后续版本在此追加
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}

# 已知表名白名单：_column_exists 的 table 参数经 f-string 拼接进 PRAGMA，
# SQLite 的 PRAGMA 不支持参数占位符，用白名单校验防止表名注入
_VALID_TABLES: frozenset[str] = frozenset(
    {
        "tasks",
        "task_items",
        "metadata",
        "cookies",
        "config",
        "schema_version",
    }
)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """检查表中是否存在指定列（幂等迁移辅助）。

    Args:
        conn: SQLite 连接
        table: 表名（必须是 _VALID_TABLES 白名单中的表）
        column: 列名

    Raises:
        ValueError: 表名不在白名单中
    """
    if table not in _VALID_TABLES:
        raise ValueError(f"非法表名: {table!r}")
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """v1 → v2：task_items 表新增 selected_image_indices 列。

    v0.1.7 图文类型下载流程引入图片级勾选，JSON 数组如 "[0,1,3]"
    记录勾选的图片索引；空字符串表示全选。幂等：列已存在时跳过。
    """
    if _column_exists(conn, "task_items", "selected_image_indices"):
        return
    conn.execute("ALTER TABLE task_items ADD COLUMN selected_image_indices TEXT DEFAULT ''")


MIGRATIONS[2] = _migrate_v1_to_v2


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """获取 SQLite 连接。

    - 默认 db_path = config.DB_PATH，调用 config.ensure_app_dirs() 确保父目录存在
    - 开启 WAL 模式（文件数据库）
    - 开启外键约束（ON DELETE CASCADE 依赖此项）
    - row_factory = sqlite3.Row（字典式行，便于 Repository 映射）
    - check_same_thread=False（允许跨线程使用，由调用方保证线程安全）

    Args:
        db_path: 数据库文件路径，默认 config.DB_PATH

    Returns:
        sqlite3.Connection 连接实例
    """
    if db_path is None:
        db_path = config.DB_PATH
        config.ensure_app_dirs()

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """初始化数据库：建表、建索引、插入默认配置、记录 schema 版本。

    全部在一个事务中执行，失败回滚。幂等：重复调用不报错不重复插入。

    Args:
        conn: sqlite3.Connection 连接实例
    """
    with conn:
        # 1. 建表（CREATE TABLE IF NOT EXISTS，幂等）
        for sql in _ALL_CREATE_TABLE_SQL:
            conn.execute(sql)

        # 2. 建索引（CREATE INDEX IF NOT EXISTS，幂等）
        for sql in CREATE_INDEXES_SQL:
            conn.execute(sql)

        # 3. 插入默认配置（INSERT OR IGNORE，已存在则跳过，幂等）
        for key, value in config.DEFAULT_CONFIGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO config(key, value) VALUES(?, ?)",
                (key, value),
            )

        # 4. 记录 schema 版本（仅在 schema_version 表完全空时插入初始版本；
        #    旧库升级时跳过此步，由 migrate() 通过迁移函数追加新版本记录）
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM schema_version").fetchone()
        if existing is None or existing["cnt"] == 0:
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
                (SCHEMA_VERSION, now_iso()),
            )


def migrate(conn: sqlite3.Connection) -> None:
    """执行数据库迁移。

    读取 schema_version 表当前版本，若当前版本 < SCHEMA_VERSION，
    依次执行迁移函数。每个迁移函数负责版本 N-1 → N 的 DDL，执行后更新 schema_version。

    当前已有迁移：
    - v1 → v2：task_items 表新增 selected_image_indices 列（v0.1.7 图文勾选）

    后续里程碑若改表结构，只需新增迁移函数并提升 SCHEMA_VERSION，不改 init_db。

    Args:
        conn: sqlite3.Connection 连接实例
    """
    # 读取当前版本
    row = conn.execute("SELECT MAX(version) AS max_version FROM schema_version").fetchone()
    current_version = row["max_version"] if row and row["max_version"] is not None else 0

    # 依次执行迁移
    for version in range(current_version + 1, SCHEMA_VERSION + 1):
        migration_fn = MIGRATIONS.get(version)
        if migration_fn is not None:
            with conn:
                migration_fn(conn)
                conn.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
                    (version, now_iso()),
                )


def init_default_db() -> sqlite3.Connection:
    """便捷初始化入口：调用 get_connection() + init_db() + migrate()。

    应用启动时调用一次，返回就绪连接。

    Returns:
        初始化完成的 sqlite3.Connection 连接实例
    """
    conn = get_connection()
    init_db(conn)
    migrate(conn)
    return conn


def get_memory_connection() -> sqlite3.Connection:
    """返回内存数据库连接并执行 init_db()，供测试使用。

    内存数据库快且自动清理，不污染真实文件系统。
    注意：内存数据库不支持 WAL 模式（PRAGMA journal_mode 返回 'memory'），
    但其他功能（外键、级联删除）正常。

    Returns:
        初始化完成的内存 sqlite3.Connection 连接实例
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn
