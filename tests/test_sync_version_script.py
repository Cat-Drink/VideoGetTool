"""版本号同步脚本的测试用例。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "sync_version.py"


def test_sync_version_integration(tmp_path: Path) -> None:
    """集成测试：通过 subprocess 调用 sync_version.py 的 check 模式。

    验证脚本能正常启动、读取 6 个版本号文件并报告一致性。
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "check"],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"sync_version.py check 失败\n" f"stdout:\n{result.stdout}\n" f"stderr:\n{result.stderr}"
    )
    # 检查输出中是否包含所有 6 个文件的版本号报告
    assert "所有版本号一致" in result.stdout, f"版本号不一致:\n{result.stdout}"
    assert "✅" in result.stdout, f"输出缺少成功标记:\n{result.stdout}"
    # 检查版本号一致性
    assert "Python 项目配置" in result.stdout
    assert "FastAPI 后端版本" in result.stdout
    assert "前端 npm 配置" in result.stdout
    assert "Tauri 应用配置" in result.stdout
    assert "Rust 版本获取函数" in result.stdout
    assert "Windows 安装程序配置" in result.stdout


def test_version_format_validation() -> None:
    """测试版本号格式验证。"""
    import re

    pattern = re.compile(r"\d+\.\d+\.\d+")

    # 有效版本号
    assert pattern.fullmatch("0.3.2")
    assert pattern.fullmatch("1.0.0")
    assert pattern.fullmatch("10.20.30")

    # 无效版本号
    assert not pattern.fullmatch("0.3")
    assert not pattern.fullmatch("0.3.2.1")
    assert not pattern.fullmatch("v0.3.2")
    assert not pattern.fullmatch("0.3.2-beta")


def test_tag_version_extraction() -> None:
    """测试从 git tag 提取版本号。"""
    # v 前缀的 tag
    tag = "v0.3.2"
    version = tag.lstrip("v")
    assert version == "0.3.2"

    # 没有 v 前缀的 tag
    tag = "0.3.2"
    version = tag.lstrip("v")
    assert version == "0.3.2"


class TestVersionRegexPatterns:
    """测试各文件的版本号提取正则。"""

    def test_pyproject_toml_pattern(self) -> None:
        """pyproject.toml 版本号提取。"""
        pattern = re.compile(r'^version = "([0-9.]+)"', re.MULTILINE)

        content = 'version = "0.3.2"'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"

    def test_app_py_pattern(self) -> None:
        """backend/app.py 版本号提取。"""
        pattern = re.compile(r'version="([0-9.]+)"')

        content = 'app = FastAPI(\n    version="0.3.2",\n)'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"

    def test_package_json_pattern(self) -> None:
        """frontend/package.json 版本号提取。"""
        pattern = re.compile(r'"version":\s*"([0-9.]+)"')

        content = '{\n  "version": "0.3.2",\n}'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"

    def test_tauri_conf_json_pattern(self) -> None:
        """frontend/src-tauri/tauri.conf.json 版本号提取。"""
        pattern = re.compile(r'"version":\s*"([0-9.]+)"')

        content = '{\n  "version": "0.3.2"\n}'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"

    def test_lib_rs_pattern(self) -> None:
        """frontend/src-tauri/src/lib.rs 版本号提取。"""
        pattern = re.compile(r'"(0\.[0-9.]+)"\.to_string\(\)')

        content = 'fn get_app_version() -> String {\n    "0.3.2".to_string()\n}'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"

    def test_installer_iss_pattern(self) -> None:
        """installer.iss 版本号提取。"""
        pattern = re.compile(r'#define MyAppVersion "([0-9.]+)"')

        content = '#define MyAppVersion "0.3.2"'
        match = pattern.search(content)
        assert match is not None
        assert match.group(1) == "0.3.2"


class TestVersionReplacement:
    """测试版本号替换。"""

    def test_pyproject_replacement(self) -> None:
        """pyproject.toml 版本号替换。"""
        pattern = re.compile(r'^version = "([0-9.]+)"', re.MULTILINE)
        template = 'version = "{version}"'

        content = 'version = "0.3.1"'
        new_content = pattern.sub(template.format(version="0.3.2"), content, count=1)
        assert new_content == 'version = "0.3.2"'

    def test_app_py_replacement(self) -> None:
        """backend/app.py 版本号替换。"""
        pattern = re.compile(r'version="([0-9.]+)"')
        template = 'version="{version}"'

        content = 'app = FastAPI(\n    title="...",\n    version="0.3.1",\n)'
        new_content = pattern.sub(template.format(version="0.3.2"), content, count=1)
        assert 'version="0.3.2"' in new_content

    def test_lib_rs_replacement(self) -> None:
        """frontend/src-tauri/src/lib.rs 版本号替换。"""
        pattern = re.compile(r'"(0\.[0-9.]+)"\.to_string\(\)')
        template = '"{version}".to_string()'

        content = 'fn get_app_version() -> String {\n    "0.3.1".to_string()\n}'
        new_content = pattern.sub(template.format(version="0.3.2"), content, count=1)
        assert '"0.3.2".to_string()' in new_content


class TestVersionConsistency:
    """测试版本号一致性检查。"""

    def test_all_versions_match(self) -> None:
        """测试：所有版本号都匹配。"""
        versions = {
            "Python 项目配置": "0.3.2",
            "FastAPI 后端版本": "0.3.2",
            "前端 npm 配置": "0.3.2",
            "Tauri 应用配置": "0.3.2",
            "Rust 版本获取函数": "0.3.2",
            "Windows 安装程序配置": "0.3.2",
        }

        valid_versions = {v for v in versions.values() if v is not None}
        assert len(valid_versions) == 1
        assert valid_versions == {"0.3.2"}

    def test_versions_mismatch(self) -> None:
        """测试：版本号不匹配。"""
        versions = {
            "Python 项目配置": "0.3.2",
            "FastAPI 后端版本": "0.3.2",
            "前端 npm 配置": "0.3.1",  # 不匹配
            "Tauri 应用配置": "0.3.2",
            "Rust 版本获取函数": "0.3.2",
            "Windows 安装程序配置": "0.3.2",
        }

        valid_versions = {v for v in versions.values() if v is not None}
        assert len(valid_versions) > 1

    def test_version_with_none(self) -> None:
        """测试：某个版本号未找到。"""
        versions = {
            "Python 项目配置": "0.3.2",
            "FastAPI 后端版本": None,  # 未找到
            "前端 npm 配置": "0.3.2",
            "Tauri 应用配置": "0.3.2",
            "Rust 版本获取函数": "0.3.2",
            "Windows 安装程序配置": "0.3.2",
        }

        valid_versions = {v for v in versions.values() if v is not None}
        assert len(valid_versions) == 1
