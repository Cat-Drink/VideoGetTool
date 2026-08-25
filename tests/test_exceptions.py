"""爬虫层异常类层次结构测试。

验证异常继承关系、实例化、属性携带等基础契约，保证上层 ``except`` 分支
按基类统一兜底时行为正确。
"""

from __future__ import annotations

import pytest

from crawlers.exceptions import (
    CookieInvalidError,
    CrawlerError,
    InvalidURLFormatError,
    NetworkError,
    RateLimitedError,
    SignError,
    UserNotFoundError,
    VerifyRequiredError,
    VideoNotFoundError,
    VideoGetToolError,
)


class TestExceptionHierarchy:
    """异常继承关系测试。"""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            InvalidURLFormatError,
            CookieInvalidError,
            RateLimitedError,
            VideoNotFoundError,
            UserNotFoundError,
            VerifyRequiredError,
            NetworkError,
            SignError,
        ],
    )
    def test_crawler_errors_extend_crawler_error(self, exc_cls: type) -> None:
        """所有爬虫层异常均继承自 CrawlerError。"""
        assert issubclass(exc_cls, CrawlerError)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            CrawlerError,
            InvalidURLFormatError,
            CookieInvalidError,
            RateLimitedError,
            VideoNotFoundError,
            UserNotFoundError,
            VerifyRequiredError,
            NetworkError,
            SignError,
        ],
    )
    def test_all_extend_video_get_tool_error(self, exc_cls: type) -> None:
        """所有自定义异常均继承自 VideoGetToolError，便于顶层统一兜底。"""
        assert issubclass(exc_cls, VideoGetToolError)

    def test_crawler_error_extends_video_get_tool_error(self) -> None:
        """CrawlerError 是 VideoGetToolError 的直接子类。"""
        assert issubclass(CrawlerError, VideoGetToolError)


class TestExceptionInstantiation:
    """异常实例化与消息携带测试。"""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            InvalidURLFormatError,
            CookieInvalidError,
            RateLimitedError,
            VideoNotFoundError,
            UserNotFoundError,
            VerifyRequiredError,
            NetworkError,
        ],
    )
    def test_message_preserved(self, exc_cls: type) -> None:
        """普通爬虫异常保留 message 字符串。"""
        msg = "测试错误信息"
        exc = exc_cls(msg)
        assert str(exc) == msg

    def test_sign_error_default_algorithm_none(self) -> None:
        """SignError 未指定 algorithm 时默认为 None。"""
        exc = SignError("签名失败")
        assert str(exc) == "签名失败"
        assert exc.algorithm is None

    @pytest.mark.parametrize(
        "algorithm",
        ["xbogus", "abogus", "mstoken", "verify_fp"],
    )
    def test_sign_error_carries_algorithm(self, algorithm: str) -> None:
        """SignError 携带 algorithm 属性，便于日志定位。"""
        exc = SignError("签名失败", algorithm=algorithm)
        assert exc.algorithm == algorithm

    def test_raise_and_catch_as_crawler_error(self) -> None:
        """子类异常可被 ``except CrawlerError`` 捕获。"""
        with pytest.raises(CrawlerError):
            raise InvalidURLFormatError("无法识别")

    def test_raise_and_catch_as_video_get_tool_error(self) -> None:
        """子类异常可被 ``except VideoGetToolError`` 顶层捕获。"""
        with pytest.raises(VideoGetToolError):
            raise VerifyRequiredError("需要验证")
