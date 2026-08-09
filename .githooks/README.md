# Git Hooks 配置

本目录包含项目的 Git hooks，用于自动化开发工作流。

## 安装

克隆项目后，首次运行以下命令将 hooks 配置到 Git：

```bash
git config core.hooksPath .githooks
```

这样 Git 会自动使用本目录中的 hooks 而不是默认的 `.git/hooks` 目录。

## 可用的 Hooks

### pre-commit（版本号自动同步）

**触发时机**：执行 `git commit` 前

**作用**：
- 检测 `pyproject.toml` 的版本号是否发生变化
- 如果有变化，自动调用 `scripts/sync_version.py` 同步到其他 5 个文件
- 自动将同步后的文件 add 到 staging
- 继续 commit 流程

**使用示例**：
```bash
# 编辑 pyproject.toml，更改版本号
# git add pyproject.toml
# git commit -m "chore(version): bump to 0.3.3"

# pre-commit 钩子会自动：
# 1. 检测版本号变化
# 2. 同步到其他 5 个文件
# 3. git add 这些文件
# 4. commit 包含所有变化
```

## 跳过 Hooks

如需跳过 pre-commit 钩子（不推荐），可以使用 `--no-verify` 标志：

```bash
git commit --no-verify
```

注意：Release CI 会在 tag 时强制检查版本号一致性，所以即使跳过本地钩子，CI 仍会拒绝不一致的 tag。

## 手动同步

如果需要手动同步版本号（例如 hooks 出现问题），可以运行：

```bash
# 检查版本号一致性
python scripts/sync_version.py check

# 同步 pyproject.toml 版本到其他文件
python scripts/sync_version.py sync

# 验证版本与 git tag 一致性（CI 使用）
python scripts/sync_version.py validate-tag v0.3.2
```

## 故障排除

### 钩子没有执行

确保已运行了 hooks 配置命令：
```bash
git config core.hooksPath .githooks
```

验证配置：
```bash
git config core.hooksPath
# 应输出：.githooks
```

### 钩子执行出错

检查 Python 环境是否可用。钩子使用系统 Python，确保 `python` 命令可用。

### 手动执行钩子测试

```bash
python .githooks/pre-commit
```
