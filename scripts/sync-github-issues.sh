#!/usr/bin/env bash
# 在 GitHub 仓库中创建 4 个 Milestones 和 12 个 Issues（需先执行 gh auth login）
set -e
REPO="SherryWang2005/ECommerceAgent"
cd "$(dirname "$0")/.."

echo ">>> 创建 Milestones ..."
gh api repos/$REPO/milestones -f title="M1: 基础设施与数据打通" -f description="让 Agent 能够「看见」公司库存实时状态，并「听见」市场流行趋势。" --method POST
gh api repos/$REPO/milestones -f title="M2: 选品 Agent" -f description="基于市场趋势与历史表现，推荐下一季爆款或补位款。" --method POST
gh api repos/$REPO/milestones -f title="M3: 库存管理 Agent" -f description="自动预警断货风险，智能处理呆滞库存。" --method POST
gh api repos/$REPO/milestones -f title="M4: 销量回顾 Agent" -f description="总结过去，并把教训自动喂给选品 Agent。" --method POST

echo ">>> 创建 Issues（关联到对应 Milestone）..."
create_issue() {
  local title=$1
  local milestone=$2
  local body_file=$3
  if [[ -f "$body_file" ]]; then
    gh issue create --repo "$REPO" --title "$title" --body-file "$body_file" --milestone "$milestone"
  else
    gh issue create --repo "$REPO" --title "$title" --body "详见仓库 docs/issues/ 下对应文档。" --milestone "$milestone"
  fi
}

create_issue "Issue 1.1: 内部 ERP/OMS 接口集成" "M1: 基础设施与数据打通" "docs/issues/issue-1.1-erp-oms集成.md"
create_issue "Issue 1.2: 外部趋势抓取工具（Scraper）" "M1: 基础设施与数据打通" "docs/issues/issue-1.2-外部趋势抓取.md"
create_issue "Issue 1.3: 商品多维标签化（Tagging）" "M1: 基础设施与数据打通" "docs/issues/issue-1.3-商品多维标签化.md"
create_issue "Issue 2.1: 流行趋势映射逻辑" "M2: 选品 Agent" "docs/issues/issue-2.1-流行趋势映射.md"
create_issue "Issue 2.2: 竞品差异化分析（Gap Analysis）" "M2: 选品 Agent" "docs/issues/issue-2.2-竞品差异化分析.md"
create_issue "Issue 2.3: 首单定量策略建议" "M2: 选品 Agent" "docs/issues/issue-2.3-首单定量策略.md"
create_issue "Issue 3.1: 动态库存预警系统（Alerting）" "M3: 库存管理 Agent" "docs/issues/issue-3.1-动态库存预警.md"
create_issue "Issue 3.2: 滞销品清理决策树" "M3: 库存管理 Agent" "docs/issues/issue-3.2-滞销品清理决策.md"
create_issue "Issue 3.3: 智能补货计算器" "M3: 库存管理 Agent" "docs/issues/issue-3.3-智能补货计算器.md"
create_issue "Issue 4.1: 多维度销售复盘看板" "M4: 销量回顾 Agent" "docs/issues/issue-4.1-多维度销售复盘看板.md"
create_issue "Issue 4.2: 退货率深度归因" "M4: 销量回顾 Agent" "docs/issues/issue-4.2-退货率深度归因.md"
create_issue "Issue 4.3: 策略迭代反馈环" "M4: 销量回顾 Agent" "docs/issues/issue-4.3-策略迭代反馈环.md"

echo ">>> 完成。请在 GitHub 仓库的 Issues / Milestones 页面查看。"
echo "    https://github.com/$REPO/issues"
echo "    https://github.com/$REPO/milestones"
