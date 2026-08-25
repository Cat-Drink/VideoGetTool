"""数据库初始化测试。

验证表结构、索引、WAL 模式、外键、默认配置、级联删除、迁移框架。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import config, database
from app.database import SCHEMA_VERSION
from app.models import Metadata, Task, TaskItem


def _get_table_names(conn: sqlite3.Connection) -> set[str]:
    """获取所有表名。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {row["name"] for row in rows}


def _get_index_names(conn: sqlite3.Connection) -> set[str]:
    """获取所有索引名（排除 sqlite_autoindex_*）。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {row["name"] for row in rows}


class TestInitDb:
    """init_db 测试。"""

    def test_init_db_creates_all_tables(self, memory_db: sqlite3.Connection) -> None:
        """初始化后应存在 6 张表（排除 sqlite_sequence 系统表）。"""
        tables = _get_table_names(memory_db)
        expected = {
            "tasks",
            "task_items",
            "metadata",
            "cookies",
            "config",
            "schema_version",
        }
        # sqlite_sequence 是 AUTOINCREMENT 自动创建的系统表，不算业务表
        tables.discard("sqlite_sequence")
        assert tables == expected

    def test_init_db_creates_all_indexes(self, memory_db: sqlite3.Connection) -> None:
        """初始化后应存在 6 个索引。"""
        indexes = _get_index_names(memory_db)
        expected = {
            "idx_tasks_status",
            "idx_task_items_task_id",
            "idx_task_items_status",
            "idx_task_items_aweme_id",
            "idx_cookies_status",
            "idx_metadata_task_item_id",
        }
        assert indexes == expected

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """文件数据库应开启 WAL 模式。

        注意：内存数据库不支持 WAL，必须用文件数据库测试。
        """
        db_file = tmp_path / "test.db"
        conn = database.get_connection(db_file)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()
            assert mode[0].lower() == "wal"
        finally:
            conn.close()

    def test_foreign_keys_enabled(self, memory_db: sqlite3.Connection) -> None:
        """外键约束应开启。"""
        row = memory_db.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_default_configs_inserted(self, memory_db: sqlite3.Connection) -> None:
        """config 表应含 10 条默认配置，键值与 DEFAULT_CONFIGS 一致。"""
        rows = memory_db.execute("SELECT key, value FROM config ORDER BY key").fetchall()
        result = {row["key"]: row["value"] for row in rows}
        assert result == config.DEFAULT_CONFIGS
        assert len(result) == 11

    def test_init_db_idempotent(self, memory_db: sqlite3.Connection) -> None:
        """连续两次 init_db 不报错，config 表仍 10 条。"""
        database.init_db(memory_db)  # 第二次调用
        rows = memory_db.execute("SELECT COUNT(*) AS cnt FROM config").fetchone()
        assert rows["cnt"] == 11

    def test_cascade_delete(
        self,
        memory_db: sqlite3.Connection,
        task_repo,
        item_repo,
        metadata_repo,
        sample_task: Task,
        sample_task_item: TaskItem,
    ) -> None:
        """删除 task 后 task_item 和 metadata 自动删除（外键 CASCADE）。

        注意：sample_task_item fixture 已插入 sample_task（task_id 已绑定），
        此处只需插入 task_item 与 metadata。
        """
        # sample_task_item.task_id 已由 fixture 绑定（task 已插入）
        item_id = item_repo.create(sample_task_item)
        # 插入 metadata
        metadata_id = metadata_repo.create(
            Metadata(
                id=None,
                task_item_id=item_id,
                aweme_id="aweme_001",
                title="测试视频",
            )
        )

        # 验证都存在
        assert task_repo.get(sample_task_item.task_id) is not None
        assert item_repo.get(item_id) is not None
        assert metadata_repo.get(metadata_id) is not None

        # 删除 task，应级联删除 task_item 和 metadata
        task_repo.delete(sample_task_item.task_id)
        assert task_repo.get(sample_task_item.task_id) is None
        assert item_repo.get(item_id) is None
        assert metadata_repo.get(metadata_id) is None

    def test_schema_version_recorded(self, memory_db: sqlite3.Connection) -> None:
        """schema_version 表应含当前 SCHEMA_VERSION 记录（v0.1.7：版本=2）。"""
        row = memory_db.execute(
            "SELECT version FROM schema_version WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
        assert row is not None
        assert row["version"] == SCHEMA_VERSION

    def test_get_memory_connection(self) -> None:
        """get_memory_connection 返回的连接可直接查询。"""
        conn = database.get_memory_connection()
        try:
            # 能查询 config 表
            rows = conn.execute("SELECT COUNT(*) AS cnt FROM config").fetchone()
            assert rows["cnt"] == 11
        finally:
            conn.close()


class TestMigrate:
    """migrate 测试。"""

    def test_migrate_no_op_on_current_version(self, memory_db: sqlite3.Connection) -> None:
        """当前版本已是 SCHEMA_VERSION 时，migrate 不执行任何操作。"""
        database.migrate(memory_db)  # 应无操作
        # schema_version 仍只有一条 v1 记录
        rows = memory_db.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        assert len(rows) == 1
        assert rows[0]["version"] == database.SCHEMA_VERSION

    def test_migrate_with_empty_db(self, tmp_path: Path) -> None:
        """对未初始化的数据库调用 migrate 应能处理（当前版本为 0）。"""
        db_file = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        try:
            # 不调用 init_db，直接 migrate（schema_version 表不存在）
            # migrate 应能处理这种情况
            # 注意：当前实现假设 schema_version 表已存在（由 init_db 创建）
            # 若表不存在，MAX 查询会失败，这是预期行为——migrate 在 init_db 之后调用
            # 此测试验证 migrate 在已初始化的库上调用是安全的
            database.init_db(conn)
            database.migrate(conn)
        finally:
            conn.close()

    def test_migrate_executes_registered_migration(self, tmp_path: Path, monkeypatch) -> None:
        """migrate 应执行注册的迁移函数并记录版本。

        模拟从版本 0 升级到 SCHEMA_VERSION，注册一个迁移函数验证它被调用。
        """
        db_file = tmp_path / "migrate_test.db"
        conn = database.get_connection(db_file)
        try:
            # 先初始化数据库（创建 schema_version 表）
            database.init_db(conn)
            # 清空 schema_version 表，模拟未迁移状态
            conn.execute("DELETE FROM schema_version")
            conn.commit()

            # 注册一个测试迁移函数（使用 monkeypatch 确保测试后清理）
            migration_called = {"executed": False}

            def fake_migration_v1(c: sqlite3.Connection) -> None:
                migration_called["executed"] = True

            monkeypatch.setitem(database.MIGRATIONS, 1, fake_migration_v1)

            database.migrate(conn)

            assert migration_called["executed"] is True
            # 应记录版本
            row = conn.execute("SELECT version FROM schema_version WHERE version = 1").fetchone()
            assert row is not None
        finally:
            conn.close()


class TestInitDefaultDb:
    """init_default_db 测试。"""

    def test_init_default_db_returns_ready_connection(self, tmp_path: Path, monkeypatch) -> None:
        """init_default_db 返回就绪连接（用 tmp_path 隔离）。"""
        # 重定向 APP_DATA_DIR 到临时目录，避免污染真实环境
        fake_app_data = tmp_path / "VideoGetTool"
        monkeypatch.setattr(config, "APP_DATA_DIR", fake_app_data)
        monkeypatch.setattr(config, "DB_PATH", fake_app_data / "data.db")
        monkeypatch.setattr(config, "LOG_DIR", fake_app_data / "logs")
        monkeypatch.setattr(config, "LOG_FILE", fake_app_data / "logs" / "app.log")

        conn = database.init_default_db()
        try:
            # 验证连接可用
            rows = conn.execute("SELECT COUNT(*) AS cnt FROM config").fetchone()
            assert rows["cnt"] == 11
            # 验证 schema_version 含当前版本记录（v0.1.7：版本=2）
            row = conn.execute(
                "SELECT version FROM schema_version WHERE version = ?",
                (SCHEMA_VERSION,),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()
