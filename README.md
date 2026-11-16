# Novel Clinic · 小说工坊

> 面向中文小说的**编辑体检工作台**，跑在 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）里。
> A review-first workbench for Chinese web novels: scan → score → approve → apply → gate. It never overwrites your manuscript.

[![selftest](https://github.com/novel-clinic/novel-clinic/actions/workflows/selftest.yml/badge.svg)](https://github.com/novel-clinic/novel-clinic/actions/workflows/selftest.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 它是什么

不是"AI 代写"，是**可复查的编辑体检**：

- 把 `.docx` / `.md` / `.txt` 主稿放进来，扫描出**改动清单**和**编辑健康度评分**；
- 逐条勾选、填写替换文本，应用后生成新稿，自动跑 **9 项门禁体检**；
- 每条问题都能定位到「第几章第几段」，带原文、依据、建议；
- 附带知识库（设定卡）、情节节拍、文风粘性三个辅助面板；
- 扫描只读；应用永远从主稿基线**重新生成**新稿，绝不覆盖 `input/` 里的主稿。

适合：写了 10 万字以上、投平台被拒或数据起不来、知道自己"有 AI 味"但改不动的作者；以及稿子多、需要快速筛硬伤的工作室/编辑。

---

## 快速开始

### 1. 环境

- Windows / macOS / Linux（插件面板运行在 DSH Web GUI；引擎本身跨平台）
- Python 3.10+
- 已安装 DSH 桌面端（插件通过 npm 分发，`@deepseek-ai/dsh-base` 等包在 npm 公开）

### 2. 跑测试（先确认引擎能跑）

```bash
git clone https://github.com/novel-clinic/novel-clinic.git
cd novel-clinic
python -m pip install -r requirements.txt
python tests/selftest_engine.py
```

看到 `SELFTEST PASSED` 就说明引擎、fixture、门禁链全通。测试不碰任何真实书稿（fixture 是虚构短文）。

### 3. 装进 DSH

```bash
# 把仓库放到你喜欢的位置，然后在 DSH profile 里 link 它
# profile 目录通常：~/.dsh/profiles/desktop
```

或者用 `plugin_manager` 以本地目录安装，然后重启 DSH。左侧栏出现「小说工坊」。

数据目录与插件分离（卸载插件不丢数据）：

```
<数据目录>/小说工坊/
├─ projects/<书名>/
│  ├─ config.json          # 主稿路径、章节正则、当前轮次
│  ├─ rules/rules.json     # 禁用词、设定事实、白名单、文风基线、不动清单
│  ├─ input/主稿.docx      # 只读输入
│  ├─ rounds/第N轮/        # 扫描.json / 改动清单.md / 稿子_第N轮.docx / 体检.json
│  ├─ kb/sources/          # 大纲 / 知识库 / 番外
│  ├─ plot/sources/        # 细纲
│  └─ styles/samples/      # 文风样本
└─ 写作规范/
```

默认数据目录是本仓库同级的 `小说工坊/`；用 `plugin-config.json` 或环境变量 `NOVEL_FORGE_DATA` 覆盖。

---

## 界面

六个页签：**项目 / 报告 / 审批 / 知识库 / 情节 / 风格**。

| 页签 | 能做什么 |
|---|---|
| 项目 | 看书名、字数、轮次、评分；点「扫描主稿」生成新一轮改动清单 |
| 报告 | 分项评分、章末钩子、AI 味审计、逐条候选项；勾选「批准」 |
| 审批 | 给每条填「整段替换文本」；应用后自动体检 |
| 知识库 | 来源与卡片、同步、检索设定、生成某章上下文包 |
| 情节 | 节拍卡列表、校验（字数 / 禁忌 / 设定暴露 / 钩子） |
| 风格 | 风格档案、某段文字对某风格的粘性 |

Agent 工具 17 个（`novel_*`），与面板同一套引擎：扫描 / 报告 / 审批 / 体检 / 读章 / 改写契约 / 知识库 / 情节 / 文风 / 伏笔 / 续写。

---

## 架构

```
DSH Web GUI
   └─ client.js            面板（纯 JS + React.createElement，无构建）
        ↕ 宿主内部通道
   index.js                Host：/novel-forge API、novel_* 工具、Python 子进程
        ↕ stdin/stdout JSON
   engine/run.py           Python 引擎（唯一第三方依赖：python-docx）
        └─ novel_engine/*.py
```

详见 [docs/architecture.md](docs/architecture.md)。

**安全模型**（写进代码，不靠自觉）：

- 扫描只读主稿；
- 应用从主稿基线重新生成 `rounds/第N轮/稿子_第N轮.docx`，不覆盖主稿；
- 应用前逐条校验原文锚点；锚点失效 → 整批拒绝，不写出新稿；
- 重扫 / 重复应用会把上一版产物移进 `rounds/<轮>/历史/`，不静默覆盖；
- AI 改写只产出提案（`rounds/<轮>/改写提案.json`），必须走审批才会落进新稿。

---

## 评分与门禁

编辑健康度 = 硬门禁 25% + 设定一致性 15% + 重复冗余 15% + AI 腔 20% + 节奏与钩子 15% + 文风保真 10%。

9 项门禁：章数/章标题不变、无空章、禁用词为 0、直引号为 0、无未授权重复长段、字数变化与改动一致、已批改动全部生效、文风指纹未漂移、AI 味审计（W2/W4）。

分数是**编辑参考**，不是平台分。

---

## 已知不足（欢迎 PR）

- **改写提案没有面板入口**：`rewrite prepare/submit/list` 目前只有 Agent 工具和 CLI，作者要审提案得在聊天里做。
- **伏笔账 / 续写闭环只有工具，没有面板**（`novel_foreshadow` / `novel_continue` 写在 Host JS，引擎 CLI 里还没有对应子命令）。
- **没有新建/删除书的功能**：只能手动复制 `projects/` 下的文件夹。
- **UI 只有中文**（`locale/en.json` 只有插件名与描述）。
- **generate 模式未接入**（v3 状态机 / snapshot / ±5% 硬卡）。
- 没有 diff 视图、没有发布前质检、没有联网取样。

路线见 [CHANGELOG.md](CHANGELOG.md) 与 Issues。

---

## 贡献

先读 [CONTRIBUTING.md](CONTRIBUTING.md)。最小闭环：

```bash
python -m pip install -r requirements.txt
python tests/selftest_engine.py
```

改完测试通过再提 PR。适合上手的 issue 已打 `good first issue`。

---

## 许可

[MIT](LICENSE)。

> 名字沿革：仓库叫 `novel-clinic`（编辑门诊），插件包名仍是 `@local/dsh-novel-forge`，因为 DSH profile 里已按这个名字登记；改名需要重装插件，暂不动。
> 与 GitHub 上同名的其他 "novel-forge" 项目无关。
