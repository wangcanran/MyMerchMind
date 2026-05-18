在本地把 **ECommerceAgent** 跑起来并做 demo，可以按下面做。

## 1. 进入项目根目录

仓库根目录是包含 `ecommerce_agent` 包的那一层（例如你 clone 下来的 `ECommerceAgent` 文件夹）：

```bash
cd /path/to/ECommerceAgent
```

在 macOS 上如果没有 `python` 命令，用 `**python3**`。

## 2. 一键 Demo（推荐）

```bash
python3 -m ecommerce_agent.main --demo --seed 42 --top-n 5
```

效果：

- 终端会打印完整 Markdown 报告（选品、销量、渠道、库存、滞销、EOQ、避雷记忆等）。
- 默认还会在项目根目录生成 `**demo_report.md**`（可用 `--output` 改路径）。

常用参数：


| 参数                                | 含义                     |
| --------------------------------- | ---------------------- |
| `--demo`                          | 演示模式（会多打一行提示）          |
| `--seed 42`                       | 固定随机种子，结果可复现           |
| `--top-n 5`                       | 榜单条数                   |
| `--as-of 2026-04-14`              | 报告上的日期                 |
| `--output ./my_report.md`         | 报告输出文件                 |
| `--feedback-memory /path/to.json` | 自定义避雷记忆 JSON（不设则用包内默认） |


示例：指定输出文件：

```bash
python3 -m ecommerce_agent.main --demo --seed 42 --top-n 5 --output ./output/demo_report.md
```

## 3. 冒烟测试（验证能跑通）

```bash
python3 ecommerce_agent/tests/test_demo_smoke.py
```

会跑编排器结构检查 + 子进程执行一次 CLI，并比对两次输出是否一致。

## 4. 依赖说明

当前 Demo **只用标准库**，一般不需要 `pip install`。若你本机只有 Python 3，请统一用 `**python3`**。

如果你愿意，我可以根据你机器上的实际路径，把 `cd` 写成你仓库的绝对路径版本（发我 `ECommerceAgent` 在本机的路径即可）。



知识图谱搭建

感觉很需要实验验证吧，目前这个benchmark没有构建得非常好，prompt调优

接入数据和合理利用数据

没有接llm