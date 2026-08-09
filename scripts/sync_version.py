#!/usr/bin/env python3
"""版本号自动同步脚本。

支持三种模式：
  sync - 同步 pyproject.toml 的版本号到其他文件
  check - 检查所有版本号是否一致
  validate-tag - 验证版本号与 git tag 是否一致
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


class VersionConfig(NamedTuple):
    """版本号文件配置。"""

    file_path: Path
    pattern: re.Pattern[str]
    replacement_template: str
    description: str


# 版本号文件配置清单（6 个文件）
VERSION_CONFIGS = [
    VersionConfig(
        file_path=PROJECT_ROOT / "pyproject.toml",
        pattern=re.compile(r'^version = "([0-9.]+)"', re.MULTILINE),
        replacement_template='version = "{version}"',
        description="pyproject.toml",
    ),
    VersionConfig(
        file_path=PROJECT_ROOT / "backend" / "app.py",
        pattern=re.compile(r'version="([0-9.]+)"'),
        replacement_template='version="{version}"',
        description="backend/app.py",
    ),
    VersionConfig(
        file_path=PROJECT_ROOT / "frontend" / "package.json",
        pattern=re.compile(r'"version":\s*"([0-9.]+)"'),
        replacement_template='"version": "{version}"',
        description="frontend/package.json",
    ),
    VersionConfig(
        file_path=PROJECT_ROOT / "frontend" / "src-tauri" / "tauri.conf.json",
        pattern=re.compile(r'"version":\s*"([0-9.]+)"'),
        replacement_template='"version": "{version}"',
        description="frontend/src-tauri/tauri.conf.json",
    ),
    VersionConfig(
        file_path=PROJECT_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs",
        pattern=re.compile(r'"(0\.\d+\.\d+)"\.to_string\(\)'),
        replacement_template='"{version}".to_string()',
        description="frontend/src-tauri/src/lib.rs",
    ),
    VersionConfig(
        file_path=PROJECT_ROOT / "installer.iss",
        pattern=re.compile(r'#define MyAppVersion "([0-9.]+)"'),
        replacement_template='#define MyAppVersion "{version}"',
        description="installer.iss",
    ),
]


def get_version_from_pyproject() -> str:
    """从 pyproject.toml 读取版本号。"""
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def extract_version(file_path: Path, pattern: re.Pattern[str]) -> str | None:
    """从文件中提取版本号。"""
    try:
        content = file_path.read_text(encoding="utf-8")
        match = pattern.search(content)
        return match.group(1) if match else None
    except Exception as e:
        print(f"[FAIL] read file failed {file_path}: {e}", file=sys.stderr)
        return None


def sync_version(target_version: str) -> bool:
    """同步版本号到所有文件。

    Args:
        target_version: 目标版本号 (e.g., "0.3.2")

    Returns:
        是否成功同步
    """
    # 验证版本号格式
    if not re.fullmatch(r"\d+\.\d+\.\d+", target_version):
        print(f"[FAIL] invalid version format: {target_version}", file=sys.stderr)
        return False

    print(f"Syncing version to {target_version}...\n")

    success_count = 0
    for config in VERSION_CONFIGS:
        if not config.file_path.exists():
            print(f"[FAIL] {config.description}: file not found {config.file_path}")
            continue

        try:
            content = config.file_path.read_text(encoding="utf-8")
            new_content = config.pattern.sub(
                config.replacement_template.format(version=target_version),
                content,
                count=1,
            )

            if new_content == content:
                print(f"[WARN] {config.description}: version marker not found")
                continue

            config.file_path.write_text(new_content, encoding="utf-8")
            print(f"[OK] {config.description}")
            success_count += 1
        except Exception as e:
            print(f"[FAIL] {config.description}: {e}", file=sys.stderr)

    print(
        f"\nSuccessfully synced {success_count}/{len(VERSION_CONFIGS)}"
        f" files to version {target_version}"
    )
    return success_count == len(VERSION_CONFIGS)


def check_versions() -> tuple[bool, dict[str, str | None]]:
    """检查所有版本号是否一致。

    Returns:
        (是否一致, {文件名: 版本号})
    """
    versions = {}
    for config in VERSION_CONFIGS:
        version = extract_version(config.file_path, config.pattern)
        versions[config.description] = version

    # 获取非 None 的版本号集合
    valid_versions = {v for v in versions.values() if v is not None}

    is_consistent = len(valid_versions) <= 1
    return is_consistent, versions


def print_version_report(versions: dict[str, str | None]) -> None:
    """打印版本号检查报告。"""
    print("\n[INFO] Version check report:\n")
    for desc, version in versions.items():
        if version is None:
            print(f"  [FAIL] {desc}: version not found")
        else:
            print(f"  [OK] {desc}: {version}")


def validate_tag(tag: str) -> bool:
    """验证版本号与 git tag 是否一致。

    Args:
        tag: git tag (e.g., "v0.3.2" or "0.3.2")

    Returns:
        是否一致
    """
    # 去掉 v 前缀
    tag_version = tag.lstrip("v")

    if not re.fullmatch(r"\d+\.\d+\.\d+", tag_version):
        print(f"[FAIL] invalid tag version format: {tag_version}", file=sys.stderr)
        return False

    print(f"Validating version consistency with tag {tag} (version: {tag_version})...\n")

    is_consistent, versions = check_versions()
    print_version_report(versions)

    # 检查每个版本是否都与 tag 匹配
    mismatches = []
    for desc, version in versions.items():
        if version is None:
            mismatches.append((desc, "version not found", tag_version))
        elif version != tag_version:
            mismatches.append((desc, version, tag_version))

    if mismatches:
        print("\n[FAIL] version check failed! mismatches found:\n")
        for desc, actual, expected in mismatches:
            print(f"  {desc}:")
            print(f"    actual: {actual}")
            print(f"    expected: {expected}\n")
        return False

    print(f"\n[OK] all versions match tag {tag}")
    return True


def main() -> int:
    """主函数。"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sync_version.py sync         # sync pyproject.toml version to other files")
        print("  python sync_version.py check        # check version consistency")
        print("  python sync_version.py validate-tag <tag>  # validate consistency with git tag")
        return 1

    mode = sys.argv[1]

    if mode == "sync":
        version = get_version_from_pyproject()
        success = sync_version(version)
        return 0 if success else 1

    elif mode == "check":
        is_consistent, versions = check_versions()
        print_version_report(versions)
        if not is_consistent:
            print("\n[FAIL] versions inconsistent")
            return 1
        print("\n[OK] all versions consistent")
        return 0

    elif mode == "validate-tag":
        if len(sys.argv) < 3:
            print("Usage: python sync_version.py validate-tag <tag>", file=sys.stderr)
            return 1
        tag = sys.argv[2]
        success = validate_tag(tag)
        return 0 if success else 1

    else:
        print(f"[FAIL] unknown mode: {mode}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
