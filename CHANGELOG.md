# 更新日志

## [0.1.0] - 2026-11-16 · 首个开源版

### 开源准备

- 加 `LICENSE`（MIT）、`requirements.txt`、`CONTRIBUTING.md`、`docs/architecture.md`、CI。
- 自测从"依赖私有书稿"改为 **fixture 驱动**：`tests/fixture/` 是一篇 4 章虚构短文（《守灯人》），带规则、实体白名单、知识库来源、细纲、文风样本；`tests/selftest_engine.py` 在它上面跑完整链路（扫描 → 改写契约 → 知识库 → 情节 → 文风 → 审批应用 → 门禁 → 归档/状态/dump/store 回归）。
- 自测的目录复制从 PowerShell 改 `shutil`，Windows / macOS / Linux 都能跑。
- 清理工具脚本里写死的作者路径（`kb_probe.py` / `probe_v4_metrics.py` / `make_style_samples.py` / 四个 `*_smoke.py` / `gen_chapter_api.py` 的 prompt 书名）。
- `package.json`：补 `license`、`scripts.test`、`files`（含 `tests/fixture`），修正描述。

### 修复

- 分享包漏打 `tests/` 的问题（`files` 声明了但包内没有）。
- 文档与代码不一致：工具数量 15 → 17、仅支持 docx → 支持 docx/md/txt、AI 味指标 14 项、门禁 9 项。

### 已知问题

- 改写提案、伏笔账、续写闭环没有面板入口。
- 没有新建/删除书的功能。
- UI 只有中文。
- generate 模式（v3）未接入。
- 面板无自动化测试。

### 历史（开源前，2026-10）

- P0：项目 / 报告 / 审批（应用 + 门禁）；安全模型（不覆盖主稿、锚点校验、原子写、重复操作归档）。
- Phase A：v4 AI 味审计 14 项指标（编辑模式只报告，本书基线校准）。
- Phase B：A.6 改写契约（prepare / submit / 5 类机检 / 2 轮上限 / 只出提案）。
- P1：知识库 sync / search / context（番外剧透隔离）。
- P2：情节节拍卡 import / validate / template / submit；文风样本学习 / 粘性检测。
- 2026-10-26/27：三轮修复（引号判定、章号、finding id、锚点、原子写、重复操作归档、报告回退轮次等）。
