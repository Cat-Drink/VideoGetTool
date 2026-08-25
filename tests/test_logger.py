"""logger 模块测试。"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from app import config, logger


class TestSetupLogger:
    """setup_logger 测试。"""

    def test_setup_logger_returns_root_logger(self, tmp_path: Path, monkeypatch) -> None:
        """setup_logger 应返回根 logger。"""
        self._redirect_paths(tmp_path, monkeypatch)
        root = logger.setup_logger()
        assert root is logging.getLogger()

    def test_setup_logger_creates_log_file(self, tmp_path: Path, monkeypatch) -> None:
        """setup_logger 后日志能写入 LOG_FILE。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger()

        test_logger = logger.get_logger("test_module")
        test_logger.info("测试日志消息")

        assert config.LOG_FILE.exists()
        content = config.LOG_FILE.read_text(encoding="utf-8")
        assert "测试日志消息" in content

    def test_log_format_contains_timestamp_level_module(self, tmp_path: Path, monkeypatch) -> None:
        """日志格式应包含时间戳、级别、模块名、行号。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger()

        test_logger = logger.get_logger("test_format_module")
        test_logger.warning("格式测试消息")

        content = config.LOG_FILE.read_text(encoding="utf-8")
        assert "WARNING" in content
        assert "格式测试消息" in content
        # 应包含模块名
        assert "test_format_module" in content
        # 应包含时间戳（ISO 格式年份）
        assert re.search(r"\b20\d{2}\b", content)

    def test_timed_rotating_file_handler_backup_count_7(self, tmp_path: Path, monkeypatch) -> None:
        """TimedRotatingFileHandler 的 backupCount 应为 7。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger()

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].backupCount == 7
        assert file_handlers[0].when.lower() == "midnight"

    def test_setup_logger_no_duplicate_handlers(self, tmp_path: Path, monkeypatch) -> None:
        """重复调用 setup_logger 不产生重复 handler。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger()
        handler_count_1 = len(logging.getLogger().handlers)

        logger.setup_logger()  # 第二次调用
        handler_count_2 = len(logging.getLogger().handlers)

        assert handler_count_1 == handler_count_2

    def test_setup_logger_has_file_and_console_handlers(self, tmp_path: Path, monkeypatch) -> None:
        """setup_logger 应同时配置文件 handler 和控制台 handler。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger()

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        stream_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert len(stream_handlers) == 1

    def test_setup_logger_respects_level(self, tmp_path: Path, monkeypatch) -> None:
        """setup_logger 应设置指定的日志级别。"""
        self._redirect_paths(tmp_path, monkeypatch)
        logger.setup_logger(level=logging.DEBUG)
        assert logging.getLogger().level == logging.DEBUG

    @staticmethod
    def _redirect_paths(tmp_path: Path, monkeypatch) -> None:
        """重定向日志路径到临时目录，避免污染真实环境。"""
        fake_app_data = tmp_path / "VideoGetTool"
        fake_log_dir = fake_app_data / "logs"
        fake_log_file = fake_log_dir / "app.log"
        monkeypatch.setattr(config, "APP_DATA_DIR", fake_app_data)
        monkeypatch.setattr(config, "LOG_DIR", fake_log_dir)
        monkeypatch.setattr(config, "LOG_FILE", fake_log_file)

        # 清空已有 handler，确保测试隔离
        root = logging.getLogger()
        if root.handlers:
            root.handlers.clear()


class TestGetLogger:
    """get_logger 测试。"""

    def test_get_logger_returns_named_logger(self) -> None:
        """get_logger 应返回指定名称的 logger。"""
        log = logger.get_logger("test_named_logger")
        assert log.name == "test_named_logger"

    def test_get_logger_returns_same_instance_for_same_name(self) -> None:
        """同名 logger 应返回同一实例。"""
        log1 = logger.get_logger("same_name")
        log2 = logger.get_logger("same_name")
        assert log1 is log2
