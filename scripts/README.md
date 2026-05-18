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

---

## Benchmark 与仿真实验

开发依赖（pytest、PyYAML）：

```bash
pip install -r requirements-dev.txt
```

### L1：YAML 场景断言

场景文件位于 `benchmark/fixtures/scenarios/`。运行：

```bash
python3 -m pytest benchmark/test_scenarios.py -v
```

### L2：库存滚动仿真（noop vs 周期 Agent）

使用默认场景 `benchmark/fixtures/scenarios/minimal_rules.yaml`，输出 JSON 到 `benchmark/results/sim_comparison.json`（目录已保留，具体 JSON 默认被 gitignore）：

```bash
python3 benchmark/run_simulation.py --days 90 --decision-interval 7 --lead-time 3
```

### L3：编排器摘要回归（固定 seed）

首次生成快照或有意更新行为基线时：

```bash
UPDATE_SNAPSHOTS=1 python3 -m pytest benchmark/test_snapshots.py -v
```

日常校验：

```bash
python3 -m pytest benchmark/ -v
```
