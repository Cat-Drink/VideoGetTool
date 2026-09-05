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

from app.crypto import decrypt_secret, encrypt_secret, is_encrypted
from app.models import (
    Cookie,
    Metadata,
    Subscription,
    SubscriptionItem,
    SubscriptionItemStatus,
    Task,
    TaskItem,
    now_iso,
)

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


def _row_get(row: sqlite3.Row, key: str, default=None):
    """安全读取 sqlite3.Row 列值，列不存在时返回默认值。

    兼容旧表（迁移前部分列可能缺失）的功能。

    Args:
        row: sqlite3.Row 实例
        key: 列名
        default: 列不存在时的默认值

    Returns:
        列值或默认值。
    """
    if key in row.keys():
        return row[key]
    return default


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
        item_types=row["item_types"],
        # v0.4.0：B 站字段，兼容旧表（用 _row_get 判断列是否存在）
        bvid=_row_get(row, "bvid"),
        cid=_row_get(row, "cid"),
        page=_row_get(row, "page") or 0,
        audio_url=_row_get(row, "audio_url") or "",
        dash_merged=_row_get(row, "dash_merged") or "",
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


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    """将 sqlite3.Row 映射为 Subscription 实例。"""
    return Subscription(
        id=row["id"],
        url=row["url"],
        sec_user_id=row["sec_user_id"],
        name=row["name"],
        interval_minutes=row["interval_minutes"],
        enabled=row["enabled"],
        max_items=row["max_items"],
        last_scan_at=row["last_scan_at"],
        last_scan_status=row["last_scan_status"],
        last_scan_error=row["last_scan_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_subscription_item(row: sqlite3.Row) -> SubscriptionItem:
    """将 sqlite3.Row 映射为 SubscriptionItem 实例。"""
    return SubscriptionItem(
        id=row["id"],
        subscription_id=row["subscription_id"],
        aweme_id=row["aweme_id"],
        url=row["url"],
        title=row["title"],
        author=row["author"],
        author_sec_id=row["author_sec_id"],
        type=row["type"],
        duration=row["duration"],
        image_count=row["image_count"],
        cover_url=row["cover_url"],
        publish_time=row["publish_time"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
        rows = self._conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
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
                     local_path, selected_image_indices, item_types,
                     bvid, cid, page, audio_url, dash_merged,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?)
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
                    item.item_types,
                    item.bvid,
                    item.cid,
                    item.page,
                    item.audio_url,
                    item.dash_merged,
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
                "UPDATE task_items SET selected_image_indices = ?, updated_at = ? WHERE id = ?",
                (selected_image_indices, now_iso(), item_id),
            )

    def update_dash_urls(self, item_id: int, url: str, audio_url: str) -> None:
        """更新任务项的视频/音频流 URL（审计 M10：DASH 直链过期重解析回填）。

        Args:
            item_id: 任务项 id
            url: 新的视频流 URL
            audio_url: 新的音频流 URL
        """
        with self._conn:
            self._conn.execute(
                "UPDATE task_items SET url = ?, audio_url = ?, updated_at = ? WHERE id = ?",
                (url, audio_url, now_iso(), item_id),
            )

    def update_dash_merged(self, item_id: int, merged: bool = True) -> None:
        """标记 DASH 音视频流是否已合并完成（v0.4.0）。

        Args:
            item_id: 任务项 id
            merged: True 置 '1'（已合并），False 置 ''（未合并）
        """
        with self._conn:
            self._conn.execute(
                "UPDATE task_items SET dash_merged = ?, updated_at = ? WHERE id = ?",
                ("1" if merged else "", now_iso(), item_id),
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

    def _load_cookie(self, row: sqlite3.Row) -> Cookie:
        """行 → Cookie，content 解密（审计 H3）。

        读到旧版本明文时惰性迁移：原地 UPDATE 为密文后返回明文，
        避免下次读取重复解密；解密失败则按原值返回（不阻断读取）。
        """
        cookie = _row_to_cookie(row)
        raw = row["content"]
        if not raw:
            return cookie
        if not is_encrypted(raw):
            enc = encrypt_secret(raw)
            if enc and cookie.id is not None:
                with self._conn:
                    self._conn.execute(
                        "UPDATE cookies SET content = ? WHERE id = ?",
                        (enc, cookie.id),
                    )
            return cookie
        cookie.content = decrypt_secret(raw)
        return cookie

    def add(self, cookie: Cookie) -> int:
        """插入 Cookie，返回新记录 id。

        content 落库前经 DPAPI 加密（审计 H3）；created_at 若空则用
        now_iso() 填充。
        """
        created_at = cookie.created_at or now_iso()
        encrypted = encrypt_secret(cookie.content) if cookie.content else ""
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO cookies
                    (content, label, status, last_used, last_check,
                     fail_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    encrypted,
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
        return self._load_cookie(row) if row else None

    def get_by_id(self, cookie_id: int) -> Cookie | None:
        """按 id 查询 Cookie，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM cookies WHERE id = ?", (cookie_id,)).fetchone()
        return self._load_cookie(row) if row else None

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
        return [self._load_cookie(row) for row in rows]

    def get_all(self) -> list[Cookie]:
        """查询所有 Cookie，按 created_at 排序。"""
        rows = self._conn.execute("SELECT * FROM cookies ORDER BY created_at").fetchall()
        return [self._load_cookie(row) for row in rows]


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


class SubscriptionRepository:
    """订阅表 + 订阅作品表 Repository（v0.4.1 订阅模式）。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # === 订阅 CRUD ===

    def create(self, sub: Subscription) -> int:
        """插入订阅，返回新记录 id。"""
        now = now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO subscriptions
                    (url, sec_user_id, name, interval_minutes, enabled,
                     max_items, last_scan_at, last_scan_status, last_scan_error,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sub.url,
                    sub.sec_user_id,
                    sub.name,
                    sub.interval_minutes,
                    sub.enabled,
                    sub.max_items,
                    sub.last_scan_at,
                    sub.last_scan_status,
                    sub.last_scan_error,
                    sub.created_at or now,
                    sub.updated_at or now,
                ),
            )
            return cursor.lastrowid

    def get(self, sub_id: int) -> Subscription | None:
        """按 id 查询订阅，无结果返回 None。"""
        row = self._conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return _row_to_subscription(row) if row else None

    def get_by_sec_user_id(self, sec_user_id: str) -> Subscription | None:
        """按 sec_user_id 查询订阅（防止重复订阅）。"""
        row = self._conn.execute(
            "SELECT * FROM subscriptions WHERE sec_user_id = ? ORDER BY id LIMIT 1",
            (sec_user_id,),
        ).fetchone()
        return _row_to_subscription(row) if row else None

    def get_all(self) -> list[Subscription]:
        """查询所有订阅，按创建时间排序。"""
        rows = self._conn.execute("SELECT * FROM subscriptions ORDER BY created_at").fetchall()
        return [_row_to_subscription(row) for row in rows]

    def get_enabled(self) -> list[Subscription]:
        """查询所有启用状态的订阅。"""
        rows = self._conn.execute(
            "SELECT * FROM subscriptions WHERE enabled = 1 ORDER BY created_at"
        ).fetchall()
        return [_row_to_subscription(row) for row in rows]

    def exists_sec_user_id(self, sec_user_id: str) -> bool:
        """检查 sec_user_id 是否已订阅（去重）。"""
        row = self._conn.execute(
            "SELECT 1 FROM subscriptions WHERE sec_user_id = ? LIMIT 1", (sec_user_id,)
        ).fetchone()
        return row is not None

    def update(
        self,
        sub_id: int,
        *,
        name: str | None = None,
        interval_minutes: int | None = None,
        enabled: int | None = None,
        max_items: int | None = None,
        last_scan_at: str | None = None,
        last_scan_status: str | None = None,
        last_scan_error: str | None = None,
    ) -> None:
        """更新订阅字段（仅更新非 None 字段）。"""
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if interval_minutes is not None:
            sets.append("interval_minutes = ?")
            params.append(interval_minutes)
        if enabled is not None:
            sets.append("enabled = ?")
            params.append(enabled)
        if max_items is not None:
            sets.append("max_items = ?")
            params.append(max_items)
        if last_scan_at is not None:
            sets.append("last_scan_at = ?")
            params.append(last_scan_at)
        if last_scan_status is not None:
            sets.append("last_scan_status = ?")
            params.append(last_scan_status)
        if last_scan_error is not None:
            sets.append("last_scan_error = ?")
            params.append(last_scan_error)
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(sub_id)
        with self._conn:
            self._conn.execute(f"UPDATE subscriptions SET {', '.join(sets)} WHERE id = ?", params)

    def delete(self, sub_id: int) -> None:
        """删除订阅（外键 ON DELETE CASCADE 级联删除 subscription_items）。"""
        with self._conn:
            self._conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

    # === 订阅作品 CRUD ===

    def add_item(self, item: SubscriptionItem) -> int:
        """插入订阅作品，返回新记录 id。"""
        now = now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO subscription_items
                    (subscription_id, aweme_id, url, title, author, author_sec_id,
                     type, duration, image_count, cover_url, publish_time,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.subscription_id,
                    item.aweme_id,
                    item.url,
                    item.title,
                    item.author,
                    item.author_sec_id,
                    item.type,
                    item.duration,
                    item.image_count,
                    item.cover_url,
                    item.publish_time,
                    item.status,
                    item.created_at or now,
                    item.updated_at or now,
                ),
            )
            if cursor.lastrowid == 0:
                # 已存在相同 (subscription_id, aweme_id)，忽略并返回既有记录 id
                existing = self._conn.execute(
                    "SELECT id FROM subscription_items "
                    "WHERE subscription_id = ? AND aweme_id = ?",
                    (item.subscription_id, item.aweme_id),
                ).fetchone()
                return existing["id"] if existing else 0
            return cursor.lastrowid

    def get_item(self, item_id: int) -> SubscriptionItem | None:
        """按 id 查询订阅作品。"""
        row = self._conn.execute(
            "SELECT * FROM subscription_items WHERE id = ?", (item_id,)
        ).fetchone()
        return _row_to_subscription_item(row) if row else None

    def get_item_by_aweme_id(self, sub_id: int, aweme_id: str) -> SubscriptionItem | None:
        """按订阅 + aweme_id 查询作品（去重判断）。"""
        row = self._conn.execute(
            "SELECT * FROM subscription_items "
            "WHERE subscription_id = ? AND aweme_id = ? LIMIT 1",
            (sub_id, aweme_id),
        ).fetchone()
        return _row_to_subscription_item(row) if row else None

    def get_items(
        self, sub_id: int, status: str | None = None, limit: int | None = None
    ) -> list[SubscriptionItem]:
        """查询订阅的作品列表。

        status 为 None 时查询全部；否则按状态过滤。默认按创建时间倒序。
        """
        sql = "SELECT * FROM subscription_items WHERE subscription_id = ?"
        params: list = [sub_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_subscription_item(row) for row in rows]

    def get_new_items(self, sub_id: int, limit: int | None = None) -> list[SubscriptionItem]:
        """查询订阅的新作品（status='new'）。"""
        return self.get_items(sub_id, status=SubscriptionItemStatus.NEW.value, limit=limit)

    def count_new_items(self, sub_id: int) -> int:
        """统计订阅的新作品数量。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM subscription_items "
            "WHERE subscription_id = ? AND status = ?",
            (sub_id, SubscriptionItemStatus.NEW.value),
        ).fetchone()
        return row["cnt"] if row else 0

    def count_new_items_map(self) -> dict[int, int]:
        """返回所有订阅的新作品数量映射 {subscription_id: count}。"""
        rows = self._conn.execute(
            "SELECT subscription_id, COUNT(*) AS cnt FROM subscription_items "
            "WHERE status = ? GROUP BY subscription_id",
            (SubscriptionItemStatus.NEW.value,),
        ).fetchall()
        return {row["subscription_id"]: row["cnt"] for row in rows}

    def update_item_status(self, item_id: int, status: str) -> None:
        """更新订阅作品状态。"""
        with self._conn:
            self._conn.execute(
                "UPDATE subscription_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), item_id),
            )

    def update_items_status(self, sub_id: int, from_status: str, to_status: str) -> int:
        """批量更新某订阅下指定旧状态的作品为新状态，返回受影响行数。"""
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE subscription_items SET status = ?, updated_at = ? "
                "WHERE subscription_id = ? AND status = ?",
                (to_status, now_iso(), sub_id, from_status),
            )
            return cursor.rowcount

    def delete_item(self, item_id: int) -> None:
        """删除订阅作品。"""
        with self._conn:
            self._conn.execute("DELETE FROM subscription_items WHERE id = ?", (item_id,))
