# 架构

## 三层

```
┌──────────────────────────────────────────────┐
│ DSH Web GUI                                   │
│   client.js  —— 6 个页签，纯 JS + React.createElement，无构建
└───────────────┬──────────────────────────────┘
                │ 宿主内部通道（面板 → /novel-forge/api）
┌───────────────▼──────────────────────────────┐
│ index.js（Host, Node）                        │
│   /novel-forge/health · /novel-forge/api      │
│   novel_* Agent 工具（17 个）                  │
│   子进程调用 engine/run.py                     │
└───────────────┬──────────────────────────────┘
                │ stdin/stdout JSON（一次调用一个命令）
┌───────────────▼──────────────────────────────┐
│ engine/run.py（Python, 唯一依赖 python-docx）  │
│   scan report apply verify status dump        │
│   rewrite kb plot style                       │
└──────────────────────────────────────────────┘
```

HTTP 直连 `/novel-forge/*` 对浏览器一律 403（宿主策略）——那是给面板内部通道用的，不是公开 API。想在脚本里用引擎，直接调 `engine/run.py` 或 Python 包。

## 数据流

1. `scan`：读主稿 → 生成 `rounds/第N轮/扫描.json` + `改动清单.md`；写 `status.json.last_score`。
2. `report`：读 `扫描.json`，给面板/工具返回结构化报告 + Markdown 预览。
3. `apply`：拿审批 `decisions` → 从主稿基线逐段替换/删除 → 校验锚点 → 写 `稿子_第N轮.docx` + 逐条对照 → 自动 `verify`。
4. `verify`：新稿 vs 主稿，跑 9 项 gate，写 `体检.json`。
5. 应用结果永远落在 `rounds/`，`input/` 的主稿只读。

## finding 生命周期

```
scanners/aiflavor 产出 finding
   → 报告（quote / why / suggestion / action / severity / rule）
   → 面板勾选「批准」→ decisions（replacement 或 delete）
   → apply 校验锚点（finding.quote 必须仍等于目标段全文）
   → 写新稿 + verify
```

- finding `id` 目前是内容指纹：改字后重扫会变，所以"已驳回"记不住（见 Issue #5）。
- `rewrite prepare` 也要求 `finding.quote == 目标段全文`——命中句不是整段的 finding 不能直接进改写契约。

## 数据目录

```
<数据目录>/小说工坊/projects/<书>/
├─ config.json          schema / title / main_draft / current_round / chapter_pattern
├─ rules/
│  ├─ rules.json        banned_terms / facts / ai_patterns / allow_duplicates / allow_patterns
│  │                    do_not_touch / watch_terms / thresholds / voice / notes
│  ├─ entities.json     characters / factions / places / items / terms（改写机检白名单）
│  ├─ ai-flavor.json    v4 指标阈值/词表/模式策略
│  └─ ai-flavor-baseline.json  本书基线（首次扫描生成）
├─ input/               主稿（只读）
├─ rounds/第N轮/
│  ├─ 扫描.json  改动清单.md  稿子_第N轮.docx  体检.json  改写提案.json
│  ├─ 请求/RW-*.json    rewritten/ proposal
│  └─ 历史/             重扫/重复应用时归档的旧产物
├─ kb/sources/          大纲.txt / 知识库.txt / 番外.txt（文件名决定 authority/spoiler）
├─ plot/sources/        细纲 md；plot/第N章.json 节拍卡
└─ styles/samples/      文风样本；styles/<风格>/profile.json
```

## 安全模型

| 约束 | 实现在哪 |
|---|---|
| 扫描只读 | `scanners.py` 只读、不写主稿 |
| 不覆盖主稿 | `apply.py` 只写 `rounds/` |
| 锚点失效整批拒绝 | `apply.py` 应用前逐条比对原文 |
| 重扫/重复应用归档 | `store.py` / `apply.py` → `历史/<时间戳>__*` |
| 原子写 | `store.write_json`（tmp → fsync → os.replace） |
| 坏 JSON 容错 | `store.read_json` 返回默认值并备份 `.corrupt-<时间戳>` |
| 改写不自动落稿 | `rewrite.py` 只写提案；应用走 `apply` |
| 番外剧透隔离 | `kb.py` 默认 `include_spoilers=false` |

## 已知工程债

- `index.js` 1353 行、`client.js` 61KB、`scanners.py` 30KB，尚未拆模块。
- `novel_foreshadow` / `novel_continue` 只写在 Host JS，引擎 CLI 没有对应子命令，也没有自测。
- `client.js` 里的 `PlaceholderTab` 已无调用（死代码）。
- 面板测试为零（只有引擎端到端自测）。
