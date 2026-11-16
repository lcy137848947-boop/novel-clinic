# 写规则

规则分两层：

| 层 | 位置 | 谁改 |
|---|---|---|
| 通用 AI 腔模式 | `engine/novel_engine/rules.py` 的 `DEFAULT_AI` | 贡献者改代码 |
| 本书规则 | `projects/<书>/rules/rules.json` | 作者改数据（可打包分发） |

## rules.json 字段

```json
{
  "banned_terms": [
    { "term": "旧灯", "replacement": "引路灯", "reason": "本书统一写法" }
  ],
  "facts": [
    {
      "id": "fact.ajia_keeper",
      "name": "阿岬的看守身份不能点破",
      "severity": "hard",
      "scope": "any",
      "patterns": ["阿岬(?:其实就是|就是)[^。！？\\n]{0,10}看守"],
      "why": "这是全书伏笔；点破就废了。",
      "suggestion": "删掉身份判断，改成阿岬的一个动作。",
      "exclude": []
    }
  ],
  "ai_patterns": [
    {
      "id": "ai.explain_rule",
      "name": "替读者总结规矩",
      "severity": "warn",
      "scope": "any",
      "patterns": ["这就是[^。！？\\n]{0,12}规矩"],
      "why": "把规矩总结给读者听，是典型的替代读者下结论。",
      "suggestion": "删掉总结句，让规矩从动作里露出来。"
    }
  ],
  "allow_duplicates": ["这一句是故意重复的"],
  "allow_patterns": ["肉眼可见"],
  "do_not_touch": ["敲船板的节奏：作者语感，不动"],
  "watch_terms": ["白塔"],
  "thresholds": { "hook_weak_below": 45, "voice_tolerance_pct": 10 },
  "voice": { "image_per_10k": 43.6, "sisi": 42, "mengdi": 49, "huran": 29 }
}
```

## 写法要点

1. **`id` 稳定**：`规则族.短名`（`fact.*` / `ai.*` / `pace.*` / `hard.*`），以后要用来做忽略账本。
2. **`why` 写给作者看**：说清为什么是问题、改坏了会怎样，不要写"建议优化"。
3. **`suggestion` 给具体改法**：优先"删/挪进动作"，不要"用更生动的方式表达"。
4. **正则宁窄勿宽**：先在一章上试，确认命中是你要的；宽正则会制造大量误报（S6 三段式就是反面教材，本书误伤 24/27 章）。
5. **误报用白名单**：`allow_duplicates`（整句）、`allow_patterns`（片段）、`do_not_touch`（说明性，不参与匹配）。
6. **`exclude`**：正则命中但属于故意埋线的句子，放进 `exclude` 让规则跳过。
7. **`severity`**：`hard` 进硬伤维度并可能卡门禁；`warn`/`info` 只报告。

## 验证

```bash
python engine/run.py scan --project <项目目录>   # 看 扫描.json 里的 findings
python tests/selftest_engine.py                   # fixture 回归
```

规则包（题材通用规则）的目录结构见 Issue 模板 `rules-pack.yml`；打包分发的能力还在做（Issue #4）。
