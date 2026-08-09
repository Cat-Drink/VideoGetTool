# 版本号管理指南

本文档说明项目的版本号管理流程，包括本地开发、自动同步和 Release 发布。

## 概述

项目维护 **6 个地方的版本号**，为了确保它们始终保持同步，我们建立了自动化管理机制：

- **本地自动同步**：Git pre-commit 钩子在提交时自动同步版本号
- **CI 强制检查**：Release 流程在 tag 时验证版本号一致性，不一致则拒绝发布

## 版本号维护的 6 个地方

| 文件 | 位置 | 用途 |
|:---|:---|:---|
| `pyproject.toml` | `version = "x.y.z"` | **数据源**（单一真值） |
| `backend/app.py` | `version="x.y.z"` | FastAPI 服务元数据 |
| `frontend/package.json` | `"version": "x.y.z"` | npm 项目配置 |
| `frontend/src-tauri/tauri.conf.json` | `"version": "x.y.z"` | Tauri 应用配置 |
| `frontend/src-tauri/src/lib.rs` | `"x.y.z".to_string()` | Rust 获取版本函数 |
| `installer.iss` | `#define MyAppVersion "x.y.z"` | Windows 安装程序 |

## 工作流

### 开发人员更新版本号的标准流程

```bash
# 1. 编辑 pyproject.toml（修改数据源）
# 例如：0.3.2 → 0.3.3
# vim pyproject.toml

# 2. 暂存 pyproject.toml
git add pyproject.toml

# 3. 提交（pre-commit 钩子自动同步其他 5 个文件）
git commit -m "chore(version): bump to 0.3.3"
# 输出：
#   📝 检测到版本号变化: 0.3.2 → 0.3.3
#   正在自动同步版本号到其他文件...
#   ✅ 版本号已同步并自动 add 到 staging

# 4. 此时 commit 包含所有 6 个文件的更新
git log --stat -1

# 5. 标签并发布
git tag v0.3.3
git push && git push --tags
```

### Git Hooks 安装

首次 clone 项目后，需要配置 Git hooks：

```bash
git config core.hooksPath .githooks
```

验证配置：
```bash
git config core.hooksPath
# 输出：.githooks
```

### 发布流程

当 push tag 时，Release CI 自动触发：

```bash
git tag v0.3.3
git push --tags
# ↓
# Release CI 启动：
# 1. 解析 tag 版本号: v0.3.3 → 0.3.3
# 2. 验证所有 6 个文件版本号都是 0.3.3
# 3. 一致性检查通过 ✅ → 继续打包和发布
# 4. 一致性检查失败 ❌ → CI 中止，发布拒绝
```

## 手动操作

### 查看当前版本号一致性

```bash
python scripts/sync_version.py check
```

输出示例：
```
📋 版本号检查报告:

  ✅ Python 项目配置: 0.3.2
  ✅ FastAPI 后端版本: 0.3.2
  ✅ 前端 npm 配置: 0.3.2
  ✅ Tauri 应用配置: 0.3.2
  ✅ Rust 版本获取函数: 0.3.2
  ✅ Windows 安装程序配置: 0.3.2

✅ 所有版本号一致
```

### 手动同步版本号

如果 pre-commit 钩子被跳过，或需要手动同步：

```bash
python scripts/sync_version.py sync
```

输出示例：
```
正在同步版本号到 0.3.3...

✅ Python 项目配置
✅ FastAPI 后端版本
✅ 前端 npm 配置
✅ Tauri 应用配置
✅ Rust 版本获取函数
✅ Windows 安装程序配置

成功同步 6/6 个文件到版本 0.3.3
```

### 验证版本与 tag 一致性

这是 Release CI 用的命令，可本地测试：

```bash
python scripts/sync_version.py validate-tag v0.3.2
```

输出示例：
```
验证版本号与 tag v0.3.2 (版本: 0.3.2) 的一致性...

📋 版本号检查报告:
  ✅ Python 项目配置: 0.3.2
  ✅ FastAPI 后端版本: 0.3.2
  ✅ 前端 npm 配置: 0.3.2
  ✅ Tauri 应用配置: 0.3.2
  ✅ Rust 版本获取函数: 0.3.2
  ✅ Windows 安装程序配置: 0.3.2

✅ 所有版本号与 tag v0.3.2 一致
```

## 跳过 Pre-Commit 钩子

如果需要跳过本地 pre-commit 钩子（不推荐）：

```bash
git commit --no-verify
```

**重要**：即使跳过本地钩子，Release CI 仍会在 tag 发布时检查版本号一致性。如果不一致，CI 会拒绝发布并输出详细的差异报告。

## 常见问题

### Q: 如何处理版本号不一致的情况？

A: 运行 `python scripts/sync_version.py sync` 然后 `git add` 这些文件再提交。

### Q: 能否使用不同的版本号格式？

A: 不能。所有版本号必须遵循语义化版本格式 `x.y.z`（例如 `0.3.2`）。

### Q: Pre-commit 钩子没有执行？

A: 确保已配置 `git config core.hooksPath .githooks`。

### Q: Release CI 说版本号不一致，怎么办？

A: 
1. 检查各个文件的版本号
2. 修改不一致的文件
3. 提交修改
4. 重新打 tag 并 push

### Q: 需要更新其他地方的版本号吗？

A: 不需要。当前 6 个地方已是完整清单。如果新增了需要维护版本号的文件，请：
1. 更新 `scripts/sync_version.py` 中的 `VERSION_CONFIGS`
2. 更新本文档的版本号维护清单
3. 更新 CI 检查逻辑
4. 提交变更

## 脚本参考

### sync_version.py 用法

```bash
# 检查版本号一致性
python scripts/sync_version.py check

# 同步 pyproject.toml 版本到其他文件
python scripts/sync_version.py sync

# 验证版本与 git tag 一致性（用于 CI）
python scripts/sync_version.py validate-tag <tag>
```

### 位置

- 脚本：`scripts/sync_version.py`
- 钩子：`.githooks/pre-commit`
- 钩子文档：`.githooks/README.md`
- 测试：`tests/test_sync_version_script.py`

## 相关 Issue

- **Issue #33** (ISSUE-12)：应用版本号未同步更新
- 此自动化系统是该 issue 的长期解决方案
