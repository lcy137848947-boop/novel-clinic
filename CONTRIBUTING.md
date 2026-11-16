# 贡献指南

## 先跑起来

```bash
python -m pip install -r requirements.txt
python tests/selftest_engine.py      # 期望输出 SELFTEST PASSED
```

测试只操作 `tests/_run/`（由 `tests/fixture/` 复制而来），跑完自动清理，不碰任何真实书稿。

## 目录

| 路径 | 是什么 | 改动后怎么生效 |
|---|---|---|
| `index.js` | Host 半：`/novel-forge` API、`novel_*` 工具、Python 子进程 | 重启 DSH |
| `client.js` | Client 半：面板（纯 JS，无构建） | 刷新页面 |
| `engine/novel_engine/*.py` | Python 引擎（扫描/评分/应用/门禁/知识库/情节/文风/改写） | 立即生效 |
| `tests/fixture/` | 自测用虚构短篇 + 规则 + 知识库 + 细纲 + 文风样本 | — |
| `tests/selftest_engine.py` | 端到端自测 | — |
| `tools/` | 开发脚本（冒烟、探针），不是运行时依赖 | — |

## 改代码前

- **引擎**：优先看 `rules.py`（规则模型）、`scanners.py`（扫描）、`score.py`（评分）、`verify.py`（门禁）、`store.py`（落盘）。
- **数据契约**：`projects/<书>/config.json`、`rules/rules.json`、`rules/entities.json`、`kb/sources/`、`plot/sources/`、`styles/`。改字段要兼容旧数据（读旧写新）。
- **面板**：全部中文写死在 `client.js`；新增文案时集中放，别散落。

## 加规则

- 通用 AI 腔模式在 `rules.py` 的 `DEFAULT_AI`；本书规则在 `projects/<书>/rules/rules.json`（`banned_terms` / `facts` / `ai_patterns` / `allow_patterns` / `do_not_touch`）。
- 新规则要有：`id`、`name`、`severity`、`pattern`、`why`、`suggestion`。`why` 是给作者看的依据，不要写"建议优化"这种空话。
- 加完在 fixture 上验证：`python tests/selftest_engine.py` 仍通过；如果 fixture 需要新内容来触发规则，同时更新 `EXPECTED` 常量。

## 测试要求

- PR 必须让 `python tests/selftest_engine.py` 通过。
- 修 bug 时加一条最小回归断言（写在对应 `[N]` 段里）。
- 不要为了通过测试去改断言期望值，除非 fixture 本身确实变了（并在 PR 说明里写清）。

## PR

- 一个 PR 一件事；标题用「区域: 做了什么」（例：`engine: 规则拆成独立文件`）。
- 说明里写：改了什么、怎么验证、有没有数据格式变更。
- 不提交：`projects/` 下的真实书稿、`plugin-config.json`、`tests/_run/`、`__pycache__`、`.bak*`。
- 提交信息用中文或英文都行，一句话说清。

## 适合第一次贡献

- `good first issue`：面板文案、文档补全、冒烟脚本参数化、英文 README 段落。
- 中等：改写提案面板、伏笔面板、规则拆文件（见 Issues）。

## 行为

- 对稿子内容保持克制：这个项目处理别人的作品，测试只用虚构 fixture。
- 讨论技术就事论事；不评价任何具体作品的好坏。
