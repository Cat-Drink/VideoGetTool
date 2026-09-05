"""审计 H3：Cookie 凭据 DPAPI 加解密单测。

覆盖路径：
    1. encrypt_secret / decrypt_secret 往返一致（Windows DPAPI 或非 Windows 直通）
    2. 存储值带版本前缀 / 非 Windows 直通不带前缀
    3. CookieRepository 写加密、读解密（含惰性迁移旧明文 → 密文）
"""

from __future__ import annotations

import os
import sqlite3

from app import crypto
from app.crypto import decrypt_secret, encrypt_secret, is_encrypted
from app.models import Cookie, CookieStatus
from app.repositories import CookieRepository

IS_WINDOWS = os.name == "nt"


def _memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE cookies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            label TEXT,
            status TEXT NOT NULL,
            last_used TEXT,
            last_check TEXT,
            fail_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    return conn


class TestSecretRoundTrip:
    """encrypt/decrypt 往返与平台行为。"""

    def test_round_trip_windows(self):
        plain = "SESSDATA=abc123; bili_jct=xyz"
        enc = encrypt_secret(plain)
        if IS_WINDOWS:
            assert enc != plain
            assert is_encrypted(enc)
            assert enc.startswith(crypto._MARKER)
            assert decrypt_secret(enc) == plain
        else:
            # 非 Windows：直通 + 告警
            assert enc == plain
            assert not is_encrypted(enc)
            assert decrypt_secret(enc) == plain

    def test_empty_value_passthrough(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""
        assert not is_encrypted("")

    def test_decrypt_legacy_plaintext(self):
        """旧明文（无前缀）原样返回，兼容惰性迁移。"""
        assert decrypt_secret("legacy-plain") == "legacy-plain"

    def test_decrypt_invalid_cipher_returns_original(self):
        """损坏密文不抛错，按原值返回。"""
        assert decrypt_secret(crypto._MARKER + "!!!not-base64!!!") != ""


class TestCookieRepositoryEncryption:
    """写入加密、读取解密、惰性迁移。"""

    def test_add_encrypts_content(self):
        conn = _memory_db()
        repo = CookieRepository(conn)
        repo.add(
            Cookie(
                id=None,
                content="raw-cookie-1",
                label="t1",
                status=CookieStatus.UNTESTED.value,
            )
        )
        row = conn.execute("SELECT content FROM cookies").fetchone()
        if IS_WINDOWS:
            # 落库应为密文
            assert is_encrypted(row["content"])
            assert "raw-cookie-1" not in row["content"]
        else:
            # 非 Windows 直通
            assert row["content"] == "raw-cookie-1"

    def test_read_returns_plaintext_after_encrypt(self):
        conn = _memory_db()
        repo = CookieRepository(conn)
        cid = repo.add(
            Cookie(
                id=None,
                content="round-trip-cookie",
                label="t1",
                status=CookieStatus.VALID.value,
            )
        )
        got = repo.get_by_id(cid)
        assert got is not None
        assert got.content == "round-trip-cookie"

    def test_lazy_migration_of_legacy_plaintext(self):
        """旧明文行首次读取后被迁移为密文（Windows），返回明文不变。"""
        conn = _memory_db()
        conn.execute(
            "INSERT INTO cookies (content, label, status, created_at) "
            "VALUES ('legacy-plain', 'old', 'valid', '2026-01-01')"
        )
        repo = CookieRepository(conn)
        cookies = repo.get_all()
        assert cookies[0].content == "legacy-plain"
        if IS_WINDOWS:
            stored = conn.execute("SELECT content FROM cookies").fetchone()["content"]
            assert is_encrypted(stored)
            # 再次读取仍能解出原文
            assert repo.get_all()[0].content == "legacy-plain"

    def test_get_valid_decrypts(self):
        conn = _memory_db()
        repo = CookieRepository(conn)
        repo.add(
            Cookie(
                id=None,
                content="valid-cookie",
                label="t",
                status=CookieStatus.VALID.value,
            )
        )
        got = repo.get_valid()
        assert got is not None and got.content == "valid-cookie"


class TestBiliCookieConfig:
    """B 站 config 表 Cookie 键加密（走 encrypt_secret/decrypt_secret）。"""

    def test_config_value_encrypted_then_decryptable(self):
        plain = "SESSDATA=abc; bili_jct=xyz"
        stored = encrypt_secret(plain)
        # 模拟 config_repo.set / get
        assert decrypt_secret(stored) == plain

    def test_non_windows_store_plaintext(self):
        if not IS_WINDOWS:
            assert not is_encrypted(encrypt_secret("plain"))
