"""签名端到端冒烟脚本（M12/A4）的本地可测部分。

不发起真实网络请求：仅验证
    - 无 Cookie 时返回 SKIP（退出码 2）
    - 参数解析默认值正确（--aweme-id / 环境变量 DOUYIN_TEST_COOKIE）
真实请求路径需在发布前手动执行或经 CI workflow_dispatch 触发
（见 docs/audit/2026-09-05-security-audit-refined-guide.md §9 演进 4）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "signer_live_smoke.py"

pytestmark = pytest.mark.signer


def _load_smoke_module():
    """从脚本路径加载模块（scripts/ 不在包路径中）。"""
    spec = importlib.util.spec_from_file_location("signer_live_smoke", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def smoke_module():
    """加载冒烟脚本模块一次。"""
    return _load_smoke_module()


class TestParseArgs:
    """命令行参数解析。"""

    def test_default_aweme_id(self, smoke_module) -> None:
        """未传 --aweme-id 时使用默认公开作品 ID。"""
        args = smoke_module.parse_args(["--cookie", "x"])
        assert args.aweme_id == smoke_module.DEFAULT_AWEME_ID

    def test_explicit_aweme_id(self, smoke_module) -> None:
        """显式 --aweme-id 生效。"""
        args = smoke_module.parse_args(["--aweme-id", "999"])
        assert args.aweme_id == "999"

    def test_cookie_from_env(self, smoke_module, monkeypatch) -> None:
        """环境变量 DOUYIN_TEST_COOKIE 作为默认 Cookie。"""
        monkeypatch.setenv(smoke_module.ENV_COOKIE, "sessionid=env")
        args = smoke_module.parse_args([])
        assert args.cookie == "sessionid=env"

    def test_cli_cookie_overrides_env(self, smoke_module, monkeypatch) -> None:
        """--cookie 参数优先于环境变量。"""
        monkeypatch.setenv(smoke_module.ENV_COOKIE, "sessionid=env")
        args = smoke_module.parse_args(["--cookie", "sessionid=cli"])
        assert args.cookie == "sessionid=cli"


class TestMainSkip:
    """无 Cookie 时跳过，不发起网络请求。"""

    def test_skip_without_cookie(self, smoke_module, monkeypatch) -> None:
        """无 Cookie → 退出码 2（SKIP）。"""
        monkeypatch.delenv(smoke_module.ENV_COOKIE, raising=False)
        assert smoke_module.main(["--aweme-id", "123"]) == 2

    def test_empty_cookie_skips(self, smoke_module) -> None:
        """--cookie 为空字符串 → 退出码 2（SKIP）。"""
        assert smoke_module.main(["--cookie", "  "]) == 2
