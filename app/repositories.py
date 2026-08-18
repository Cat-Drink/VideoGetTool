"""Repository 层。

封装对 5 张表的 CRUD 操作。每个 Repository 接收 sqlite3.Connection，
方法返回 dataclass 实例。所有写操作在事务中执行。

通用实现约定：
- 行映射：私有方法 _row_to_xxx(row: sqlite3.Row) -> dataclass，按列名访问
- 事务：所有写操作用 `with conn:` 自动提交/回滚
- 类型安全：方法签名用 str 而非枚举（str 枚举兼容），返回 dataclass
- 错误处理：不捕获 sqlite3.Error，向上抛出由调用方处理
"""

from __future__ import annotations

import sqlite3

from app.models import Cookie, Metadata, Task, TaskItem, now_iso

# === 行映射私有函数 ===


def _row_to_task(row: sqlite3.Row) -> Task:
    """将 sqlite3.Row 映射为 Task 实例。"""
    return Task(
        id=row["id"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        status=row["status"],
        total_items=row["total_items"],
        completed_items=row["completed_items"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        download_dir=row["download_dir"],
    )


def _row_to_task_item(row: sqlite3.Row) -> TaskItem:
    """将 sqlite3.Row 映射为 TaskItem 实例。"""
    return TaskItem(
        id=row["id"],
        task_id=row["task_id"],
        aweme_id=row["aweme_id"],
        url=row["url"],
        title=row["title"],
        author=row["author"],
        author_sec_id=row["author_sec_id"],
        type=row["type"],
        duration=row["duration"],
        image_count=row["image_count"],
        cover_url=row["cover_url"],
        status=row["status"],
        downloaded_bytes=row["downloaded_bytes"],
        total_bytes=row["total_bytes"],
        retry_count=row["retry_count"],
        fail_reason=row["fail_reason"],
        local_path=row["local_path"],
        selected_image_indices=row["selected_image_indices"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_cookie(row: sqlite3.Row) -> Cookie:
    """将 sqlite3.Row 映射为 Cookie 实例。"""
    return Cookie(
        id=row["id"],
        content=row["content"],
        label=row["label"],
        status=row["status"],
        last_used=row["last_used"],
        last_check=row["last_check"],
        fail_count=row["fail_count"],
        created_at=row["created_at"],
    )


def _row_to_metadata(row: sqlite3.Row) -> Metadata:
    """将 sqlite3.Row 映射为 Metadata 实例。"""
    return Metadata(
        id=row["id"],
        task_item_id=row["task_item_id"],
        aweme_id=row["aweme_id"],
        title=row["title"],
        desc=row["desc"],
        author=row["author"],
        author_uid=row["author_uid"],
        publish_time=row["publish_time"],
        like_count=row["like_count"],
        comment_count=row["comment_count"],
        share_count=row["share_count"],
        collect_count=row["collect_count"],
        tags=row["tags"],
        raw_json=row["raw_json"],
    )


# === Repository 类 ===


class TaskRepository:
    """任务表 Repository。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, task: Task) -> int:
        """插入任务，返回新记录 id。

        created_at/updated_at 若空则用 now_iso() 填充。
        """
        now = now_iso()
        created_at = task.created_at or now
        updated_at = task.updated_at or now
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO tasks
                    (source_type, source_url, status, total_items,
                     completed_items, created_at, updated_at, download_dir)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.source_type,
                    task.source_url,
                    task.status,
                    task.total_items,
                    task.completed_items,
                    created_at,
                    updated_at,
                    task.download_dir,
                ),
            )
            return cursor.lastrowid

    def get(self, task_id: int) -> Task | None:
        """按 id 查询任务，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def get_by_status(self, status: str) -> list[Task]:
        """按状态查询任务，按 created_at 排序。"""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at", (status,)
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def update_status(self, task_id: int, status: str) -> None:
        """更新任务状态。"""
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), task_id),
            )

    def update_progress(
        self,
        task_id: int,
        completed_items: int,
        total_items: int | None = None,
    ) -> None:
        """更新任务进度。

        total_items 为 None 时只更新 completed_items（用 COALESCE 保留原值）。
        """
        with self._conn:
            self._conn.execute(
                """
                UPDATE tasks
                SET completed_items = ?,
                    total_items = COALESCE(?, total_items),
                    updated_at = ?
                WHERE id = ?
                """,
                (completed_items, total_items, now_iso(), task_id),
            )

    def delete(self, task_id: int) -> None:
        """删除任务（外键 ON DELETE CASCADE 会级联删除 task_items 和 metadata）。"""
        with self._conn:
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def get_pending_for_resume(self) -> list[Task]:
        """查询可恢复的任务（断点续传）。

        返回 status IN ('pending','downloading','paused') 的任务，按 created_at 排序。
        应用启动时扫描可恢复任务。
        """
        rows = self._conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN ('pending', 'downloading', 'paused')
            ORDER BY created_at
            """,
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def get_all(self) -> list[Task]:
        """查询所有任务，按 created_at 排序。"""
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at"
        ).fetchall()
        return [_row_to_task(row) for row in rows]


class TaskItemRepository:
    """任务项表 Repository。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, item: TaskItem) -> int:
        """插入任务项，返回新记录 id。

        created_at/updated_at 若空则用 now_iso() 填充。
        """
        now = now_iso()
        created_at = item.created_at or now
        updated_at = item.updated_at or now
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO task_items
                    (task_id, aweme_id, url, title, author, author_sec_id,
                     type, duration, image_count, cover_url, status,
                     downloaded_bytes, total_bytes, retry_count, fail_reason,
                     local_path, selected_image_indices, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.task_id,
                    item.aweme_id,
                    item.url,
                    item.title,
                    item.author,
                    item.author_sec_id,
                    item.type,
                    item.duration,
                    item.image_count,
                    item.cover_url,
                    item.status,
                    item.downloaded_bytes,
                    item.total_bytes,
                    item.retry_count,
                    item.fail_reason,
                    item.local_path,
                    item.selected_image_indices,
                    created_at,
                    updated_at,
                ),
            )
            return cursor.lastrowid

    def get(self, item_id: int) -> TaskItem | None:
        """按 id 查询任务项，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM task_items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_task_item(row) if row else None

    def get_by_task(self, task_id: int) -> list[TaskItem]:
        """按 task_id 查询所有任务项。"""
        rows = self._conn.execute(
            "SELECT * FROM task_items WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        return [_row_to_task_item(row) for row in rows]

    def get_by_status(self, status: str) -> list[TaskItem]:
        """按状态查询任务项。"""
        rows = self._conn.execute(
            "SELECT * FROM task_items WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
        return [_row_to_task_item(row) for row in rows]

    def update_status(
        self,
        item_id: int,
        status: str,
        fail_reason: str | None = None,
    ) -> None:
        """更新任务项状态。

        fail_reason 非 None 时一并更新（失败时记录原因）。
        """
        now = now_iso()
        with self._conn:
            if fail_reason is not None:
                self._conn.execute(
                    """
                    UPDATE task_items
                    SET status = ?, fail_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, fail_reason, now, item_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE task_items
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, item_id),
                )

    def update_bytes(
        self,
        item_id: int,
        downloaded_bytes: int,
        total_bytes: int | None = None,
    ) -> None:
        """更新下载字节数（分块续传进度持久化）。

        total_bytes 为 None 时只更新 downloaded_bytes（用 COALESCE 保留原值）。
        """
        with self._conn:
            self._conn.execute(
                """
                UPDATE task_items
                SET downloaded_bytes = ?,
                    total_bytes = COALESCE(?, total_bytes),
                    updated_at = ?
                WHERE id = ?
                """,
                (downloaded_bytes, total_bytes, now_iso(), item_id),
            )

    def update_retry(self, item_id: int, retry_count: int) -> None:
        """更新重试次数。"""
        with self._conn:
            self._conn.execute(
                "UPDATE task_items SET retry_count = ?, updated_at = ? WHERE id = ?",
                (retry_count, now_iso(), item_id),
            )

    def reset_for_retry(self, item_id: int) -> None:
        """重置任务项为待下载状态（重新执行用）。

        清空下载进度、失败原因、本地路径与重试计数。
        """
        with self._conn:
            self._conn.execute(
                """
                UPDATE task_items
                SET status = 'pending', downloaded_bytes = 0, total_bytes = 0,
                    fail_reason = NULL, local_path = NULL, retry_count = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso(), item_id),
            )

    def update_url_and_type(
        self,
        item_id: int,
        url: str,
        item_type: str,
        title: str | None = None,
        author: str | None = None,
        duration: str | None = None,
        cover_url: str | None = None,
        image_count: int | None = None,
    ) -> None:
        """更新任务项的下载直链与类型（解析后回填）。

        可选字段（title/author/duration/cover_url/image_count）非 None 时一并更新。
        v0.1.7：新增 image_count 参数，让下载页能立即显示图集图片数。
        """
        now = now_iso()
        with self._conn:
            self._conn.execute(
                """
                UPDATE task_items
                SET url = ?, type = ?,
                    title = COALESCE(?, title),
                    author = COALESCE(?, author),
                    duration = COALESCE(?, duration),
                    cover_url = COALESCE(?, cover_url),
                    image_count = COALESCE(?, image_count),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    url,
                    item_type,
                    title,
                    author,
                    duration,
                    cover_url,
                    image_count,
                    now,
                    item_id,
                ),
            )

    def update_selected_image_indices(self, item_id: int, selected_image_indices: str) -> None:
        """更新任务项的图片级勾选状态（v0.1.7）。

        Args:
            item_id: 任务项 id
            selected_image_indices: JSON 数组字符串，如 "[0,1,3]"；空字符串表示全选
        """
        with self._conn:
            self._conn.execute(
                "UPDATE task_items SET selected_image_indices = ?, updated_at = ? " "WHERE id = ?",
                (selected_image_indices, now_iso(), item_id),
            )

    def delete(self, item_id: int) -> None:
        """删除任务项。"""
        with self._conn:
            self._conn.execute("DELETE FROM task_items WHERE id = ?", (item_id,))

    def get_by_aweme_id(self, aweme_id: str) -> TaskItem | None:
        """按 aweme_id 查询任务项（去重查询）。

        同 aweme_id 多条记录返回最新一条（ORDER BY id DESC LIMIT 1）。
        进队列前查是否已存在。
        """
        row = self._conn.execute(
            "SELECT * FROM task_items WHERE aweme_id = ? ORDER BY id DESC LIMIT 1",
            (aweme_id,),
        ).fetchone()
        return _row_to_task_item(row) if row else None

    def reset_downloading_to_paused(self) -> int:
        """把所有 downloading/processing 状态的任务项重置为 paused。

        应用启动时把中断的下载项重置为 paused（对应设计文档 4.2 节）。

        Returns:
            被重置的记录数
        """
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE task_items SET status = 'paused', updated_at = ? "
                "WHERE status IN ('downloading', 'processing')",
                (now_iso(),),
            )
            return cursor.rowcount


class CookieRepository:
    """Cookie 池表 Repository。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, cookie: Cookie) -> int:
        """插入 Cookie，返回新记录 id。

        created_at 若空则用 now_iso() 填充。
        """
        created_at = cookie.created_at or now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO cookies
                    (content, label, status, last_used, last_check,
                     fail_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cookie.content,
                    cookie.label,
                    cookie.status,
                    cookie.last_used,
                    cookie.last_check,
                    cookie.fail_count,
                    created_at,
                ),
            )
            return cursor.lastrowid

    def remove(self, cookie_id: int) -> None:
        """删除 Cookie。"""
        with self._conn:
            self._conn.execute("DELETE FROM cookies WHERE id = ?", (cookie_id,))

    def get_valid(self) -> Cookie | None:
        """获取一个有效的 Cookie（轮询策略）。

        返回 status='valid' 且 last_used 最早的（最久未用优先，均衡负载）。
        last_used 为 NULL 的优先返回（视为最久未用）。

        对应设计文档 4.3 节的轮询策略。
        """
        row = self._conn.execute(
            """
            SELECT * FROM cookies
            WHERE status = 'valid'
            ORDER BY last_used IS NULL DESC, last_used ASC
            LIMIT 1
            """,
        ).fetchone()
        return _row_to_cookie(row) if row else None

    def get_by_id(self, cookie_id: int) -> Cookie | None:
        """按 id 查询 Cookie，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM cookies WHERE id = ?", (cookie_id,)).fetchone()
        return _row_to_cookie(row) if row else None

    def update_status(self, cookie_id: int, status: str) -> None:
        """更新 Cookie 状态。"""
        with self._conn:
            self._conn.execute(
                "UPDATE cookies SET status = ? WHERE id = ?",
                (status, cookie_id),
            )

    def update_fail_count(self, cookie_id: int, fail_count: int) -> None:
        """更新连续失败次数。"""
        with self._conn:
            self._conn.execute(
                "UPDATE cookies SET fail_count = ? WHERE id = ?",
                (fail_count, cookie_id),
            )

    def update_last_used(self, cookie_id: int, last_used: str) -> None:
        """更新最后使用时间。"""
        with self._conn:
            self._conn.execute(
                "UPDATE cookies SET last_used = ? WHERE id = ?",
                (last_used, cookie_id),
            )

    def test_all(self) -> list[Cookie]:
        """返回待测 Cookie 列表（status != 'invalid'）。

        实际测试逻辑在爬虫层里程碑实现，本里程碑只提供数据查询。
        """
        rows = self._conn.execute(
            "SELECT * FROM cookies WHERE status != 'invalid' ORDER BY id"
        ).fetchall()
        return [_row_to_cookie(row) for row in rows]

    def get_all(self) -> list[Cookie]:
        """查询所有 Cookie，按 created_at 排序。"""
        rows = self._conn.execute("SELECT * FROM cookies ORDER BY created_at").fetchall()
        return [_row_to_cookie(row) for row in rows]


class ConfigRepository:
    """配置表 Repository。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, key: str) -> str | None:
        """按 key 查询配置值，无结果返回 None。"""
        row = self._conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        """设置配置值（upsert：已存在则更新，不存在则插入）。"""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO config(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_all(self) -> dict[str, str]:
        """查询所有配置，返回字典。"""
        rows = self._conn.execute("SELECT key, value FROM config").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def delete(self, key: str) -> None:
        """删除配置项。"""
        with self._conn:
            self._conn.execute("DELETE FROM config WHERE key = ?", (key,))

    def get_onboarding_done(self) -> bool:
        """查询首次引导是否完成。

        "true" 时返回 True，其他（含 None）为 False。
        """
        return self.get("onboarding_done") == "true"

    def set_onboarding_done(self, done: bool = True) -> None:
        """设置首次引导完成状态。"""
        self.set("onboarding_done", "true" if done else "false")


class MetadataRepository:
    """元数据表 Repository。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, metadata: Metadata) -> int:
        """插入元数据，返回新记录 id。"""
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO metadata
                    (task_item_id, aweme_id, title, desc, author, author_uid,
                     publish_time, like_count, comment_count, share_count,
                     collect_count, tags, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.task_item_id,
                    metadata.aweme_id,
                    metadata.title,
                    metadata.desc,
                    metadata.author,
                    metadata.author_uid,
                    metadata.publish_time,
                    metadata.like_count,
                    metadata.comment_count,
                    metadata.share_count,
                    metadata.collect_count,
                    metadata.tags,
                    metadata.raw_json,
                ),
            )
            return cursor.lastrowid

    def get(self, metadata_id: int) -> Metadata | None:
        """按 id 查询元数据，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM metadata WHERE id = ?", (metadata_id,)).fetchone()
        return _row_to_metadata(row) if row else None

    def get_by_task_item(self, task_item_id: int) -> Metadata | None:
        """按 task_item_id 查询元数据，无结果返回 None。"""
        row = self._conn.execute(
            "SELECT * FROM metadata WHERE task_item_id = ?", (task_item_id,)
        ).fetchone()
        return _row_to_metadata(row) if row else None
