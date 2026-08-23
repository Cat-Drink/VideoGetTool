"""config 模块测试。"""

from __future__ import annotations

import os
from pathlib import Path

from app import config


class TestConfigPaths:
    """配置路径常量测试。"""

    def test_app_data_dir_uses_appdata(self) -> None:
        """APP_DATA_DIR 应指向 %APPDATA%/XieFengShiYing/。"""
        expected = Path(os.environ.get("APPDATA", str(Path.home()))) / "XieFengShiYing"
        assert expected == config.APP_DATA_DIR

    def test_db_path_under_app_data_dir(self) -> None:
        """DB_PATH 应指向 %APPDATA%/XieFengShiYing/data.db。"""
        assert config.DB_PATH == config.APP_DATA_DIR / "data.db"

    def test_log_file_under_log_dir(self) -> None:
        """LOG_FILE 应指向 %APPDATA%/XieFengShiYing/logs/app.log。"""
        assert config.LOG_FILE == config.LOG_DIR / "app.log"
        assert config.LOG_DIR == config.APP_DATA_DIR / "logs"

    def test_default_download_dir(self) -> None:
        """DEFAULT_DOWNLOAD_DIR 应指向 ~/Downloads/XieFengShiYing。"""
        assert Path.home() / "Downloads" / "XieFengShiYing" == config.DEFAULT_DOWNLOAD_DIR


class TestDefaultConfigs:
    """默认配置测试。"""

    def test_default_configs_has_10_keys(self) -> None:
        """DEFAULT_CONFIGS 应包含 10 个键。"""
        assert len(config.DEFAULT_CONFIGS) == 10

    def test_default_configs_values_are_strings(self) -> None:
        """DEFAULT_CONFIGS 的值均为字符串。"""
        for value in config.DEFAULT_CONFIGS.values():
            assert isinstance(value, str)

    def test_default_configs_keys(self) -> None:
        """DEFAULT_CONFIGS 应包含指定的 6 个键。"""
        expected_keys = {
            "download_dir",
            "concurrency",
            "chunk_size",
            "retry_count",
            "metadata_format",
            "onboarding_done",
            "notification_enabled",
            "sound_enabled",
            "sound_choice",
            "sound_volume",
        }
        assert set(config.DEFAULT_CONFIGS.keys()) == expected_keys

    def test_default_concurrency(self) -> None:
        """默认并发数为 3。"""
        assert config.DEFAULT_CONCURRENCY == 3
        assert config.DEFAULT_CONFIGS["concurrency"] == "3"

    def test_default_chunk_size(self) -> None:
        """默认分块大小为 1MB。"""
        assert config.DEFAULT_CHUNK_SIZE == 1024 * 1024
        assert config.DEFAULT_CONFIGS["chunk_size"] == str(1024 * 1024)

    def test_default_retry_count(self) -> None:
        """默认重试次数为 3。"""
        assert config.DEFAULT_RETRY_COUNT == 3
        assert config.DEFAULT_CONFIGS["retry_count"] == "3"

    def test_default_metadata_format(self) -> None:
        """默认元数据格式为 json。"""
        assert config.DEFAULT_METADATA_FORMAT == "json"
        assert config.DEFAULT_CONFIGS["metadata_format"] == "json"

    def test_default_onboarding_done_false(self) -> None:
        """默认首次引导未完成。"""
        assert config.DEFAULT_CONFIGS["onboarding_done"] == "false"


class TestEnsureAppDirs:
    """ensure_app_dirs 测试。"""

    def test_ensure_app_dirs_creates_directories(self, tmp_path: Path, monkeypatch) -> None:
        """ensure_app_dirs 应创建 APP_DATA_DIR 和 LOG_DIR。"""
        # 重定向到临时目录
        fake_app_data = tmp_path / "XieFengShiYing"
        fake_log_dir = fake_app_data / "logs"
        monkeypatch.setattr(config, "APP_DATA_DIR", fake_app_data)
        monkeypatch.setattr(config, "LOG_DIR", fake_log_dir)

        # 初始不存在
        assert not fake_app_data.exists()
        assert not fake_log_dir.exists()

        # 调用后应存在
        config.ensure_app_dirs()
        assert fake_app_data.exists()
        assert fake_log_dir.exists()

    def test_ensure_app_dirs_idempotent(self, tmp_path: Path, monkeypatch) -> None:
        """重复调用 ensure_app_dirs 不报错。"""
        fake_app_data = tmp_path / "XieFengShiYing"
        fake_log_dir = fake_app_data / "logs"
        monkeypatch.setattr(config, "APP_DATA_DIR", fake_app_data)
        monkeypatch.setattr(config, "LOG_DIR", fake_log_dir)

        config.ensure_app_dirs()
        config.ensure_app_dirs()  # 第二次调用不报错
        assert fake_app_data.exists()
        assert fake_log_dir.exists()

    def test_ensure_app_dirs_creates_nested_parents(self, tmp_path: Path, monkeypatch) -> None:
        """ensure_app_dirs 应创建多级父目录。"""
        fake_app_data = tmp_path / "a" / "b" / "c" / "XieFengShiYing"
        fake_log_dir = fake_app_data / "logs"
        monkeypatch.setattr(config, "APP_DATA_DIR", fake_app_data)
        monkeypatch.setattr(config, "LOG_DIR", fake_log_dir)

        config.ensure_app_dirs()
        assert fake_app_data.exists()
        assert fake_log_dir.exists()
