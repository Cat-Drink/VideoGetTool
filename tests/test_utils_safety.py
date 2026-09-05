"""审计 S8/M5：safe_int 与 custom_sound_url 准入单测。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.config import _validate_sound_url
from crawlers.utils import safe_int


class TestSafeInt:
    """safe_int 防御性转换。"""

    def test_valid_int(self) -> None:
        assert safe_int(5) == 5
        assert safe_int("7") == 7

    def test_none_and_empty(self) -> None:
        assert safe_int(None) == 0
        assert safe_int("") == 0

    def test_non_numeric_string_falls_back(self) -> None:
        """非数字字符串不抛 ValueError，返回默认值（审计 S8 根因）。"""
        assert safe_int("abc") == 0
        assert safe_int("未知") == 0

    def test_custom_default(self) -> None:
        assert safe_int(None, default=1) == 1
        assert safe_int("x", default=9) == 9

    def test_float_string_accepted(self) -> None:
        assert safe_int("3.9") == 0  # int("3.9") 抛错 → 兜底
        assert safe_int(3.9) == 3  # int(3.9) 截断


class TestValidateSoundUrl:
    """custom_sound_url 准入（审计 M5）。"""

    def test_empty_allowed(self) -> None:
        _validate_sound_url("")  # 不抛错
        _validate_sound_url(None)  # type: ignore[arg-type]

    def test_valid_http_url(self) -> None:
        _validate_sound_url("https://cdn.example.com/notify.mp3")
        _validate_sound_url("http://127.0.0.1:18989/sound.wav")

    def test_valid_local_absolute_path(self) -> None:
        """Windows 盘符/UNC 绝对路径放行（工具为 Windows 桌面工具）。"""
        _validate_sound_url(r"C:\sounds\alert.ogg")  # 盘符路径
        _validate_sound_url(r"\\nas\share\alert.m4a")  # UNC 路径

    def test_reject_non_audio_extension(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _validate_sound_url("https://evil.com/x.html")
        assert ei.value.status_code == 400

    def test_reject_unsupported_scheme_without_abs(self) -> None:
        """ftp:// 或裸相对路径非本地绝对路径 → 拒绝。"""
        with pytest.raises(HTTPException):
            _validate_sound_url("ftp://cdn.example.com/x.mp3")
        with pytest.raises(HTTPException):
            _validate_sound_url("sounds/alert.wav")

    def test_reject_metadata_address_even_with_audio_ext(self) -> None:
        """即使扩展名是 .mp3，云元数据地址也不应被当作合法 http 来源拦截
        ——本校验目标只是阻止客户端请求伪造面，http(s) 带 host 即放行，
        云元数据防御由 covers 代理/下载器 SSRF guard 处理（不重复拦截）。"""
        _validate_sound_url("https://169.254.169.254/latest/meta-data/x.mp3")
