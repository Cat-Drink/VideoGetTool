"""应用级凭据加密模块（Windows DPAPI）。

审计 H3：Cookie / B 站 Cookie 此前明文落盘 SQLite（WAL 还保留明文副本），
本模块在写入前用 Windows DPAPI（CryptProtectData/CryptUnprotectData）加密，
读取时解密，防止磁盘拷贝/备份/同步/其他用户读取直接拿到明文。

威胁模型（如实声明）：
    - DPAPI 保护的是「磁盘上的静态数据」：备份/同步工具同步 %APPDATA%、
      其他 Windows 用户读取文件、进程崩溃残留的 WAL 等，都无法直接得到明文。
    - 它**不**防同用户会话内的恶意进程：同一 Windows 用户下运行的其他
      进程可用同一账号上下文调用 CryptUnprotectData 解密（DPAPI 用户绑定）。
    - 存储格式带版本前缀：`v1:dpapi:<base64>`，未加密的旧值原样返回，
      支持「读到旧明文 → 立即重写为密文」的惰性迁移。
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
from ctypes import wintypes

logger = logging.getLogger(__name__)

# 密文存储前缀：标识 DPAPI v1 加密
_MARKER = "v1:dpapi:"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    """读取 DATA_BLOB 中 pbData 指向的 cbData 字节。"""
    if not blob.pbData or not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _protect(plain: bytes) -> bytes:
    """调用 CryptProtectData 加密（当前 Windows 用户作用域）。"""
    in_blob = _DATA_BLOB(
        len(plain),
        ctypes.cast(ctypes.create_string_buffer(plain), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    try:
        return _blob_bytes(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect(enc: bytes) -> bytes:
    """调用 CryptUnprotectData 解密。"""
    in_blob = _DATA_BLOB(
        len(enc),
        ctypes.cast(ctypes.create_string_buffer(enc), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
    try:
        return _blob_bytes(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def encrypt_secret(plain: str) -> str:
    """加密明文凭据；空串原样返回，非 Windows 平台直接透传并告警。

    参数:
        plain: 明文 Cookie 字符串。

    返回:
        带 ``v1:dpapi:`` 前缀的密文；非 Windows 平台返回原明文。
    """
    if not plain:
        return plain
    if os.name != "nt":
        logger.warning(
            "非 Windows 平台无法使用 DPAPI，凭据将明文存储（仅测试/开发场景）"
        )
        return plain
    return _MARKER + base64.b64encode(_protect(plain.encode("utf-8"))).decode("ascii")


def decrypt_secret(value: str) -> str:
    """解密存储值；无前缀/旧明文/空值原样返回（兼容惰性迁移）。

    参数:
        value: 数据库中的凭据存储值（可能为密文或旧明文）。

    返回:
        明文凭据字符串。
    """
    if not value or not value.startswith(_MARKER):
        return value
    try:
        payload = base64.b64decode(value[len(_MARKER):])
    except (ValueError, TypeError):
        logger.warning("凭据密文 base64 解码失败，按原值返回")
        return value
    try:
        return _unprotect(payload).decode("utf-8", errors="replace")
    except OSError:
        logger.exception("凭据解密失败（可能跨用户/跨机器），按原值返回")
        return value


def is_encrypted(value: str) -> bool:
    """判断存储值是否为 DPAPI 密文（带版本前缀）。"""
    return bool(value) and value.startswith(_MARKER)
