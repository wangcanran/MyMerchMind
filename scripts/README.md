# 脚本说明

## sync-github-issues.sh — 同步 Milestones 与 Issues 到 GitHub

在 GitHub 仓库中创建 **4 个 Milestones** 和 **12 个 Issues**（与 `docs/` 中文档一致）。

### 使用前

1. 已安装 [GitHub CLI](https://cli.github.com/)（`brew install gh`）。
2. 登录 GitHub：
   ```bash
   gh auth login
   ```
   选择 HTTPS 或 SSH，按提示完成登录。

### 执行

在项目根目录执行：

```bash
chmod +x scripts/sync-github-issues.sh
./scripts/sync-github-issues.sh
```

执行后可在以下页面查看：

- https://github.com/SherryWang2005/ECommerceAgent/issues  
- https://github.com/SherryWang2005/ECommerceAgent/milestones  

### 注意

- 若仓库中已存在同名 Milestone 或大量 Issue，请先到 GitHub 上核对，避免重复创建。
- 本脚本会创建新的 Milestone 和 Issue，不会删除已有内容。
