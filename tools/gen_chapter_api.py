# -*- coding: utf-8 -*-
"""用 DeepSeek API 生成章节，生成后跑「硬门禁」；不达标自动带着问题清单重写。

设计目标：把「不能水、不能 AI 腔」变成可执行的检查，而不是口头叮嘱。
  - 写之前：prompt 里锁死文风（无内心独白 / 无解释旁白 / 对话生活化 / 动作锚点）
  - 写之后：机器检查（禁用词 / 设定红线 / 禁梗 / 必含气味+肢体+黑话 / 字数 / 文风粘性）
  - 不达标：把失败项回喂给模型重写，最多 --retries 轮

用法示例（在插件目录下）：
  python tools/gen_chapter_api.py \
    --project "<你的数据目录>/projects/<书名>" \
    --chapter-key 第30章 --title 出港 \
    --beats-file "plot/sources/第30章_细纲.md" \
    --out "plot/sources/第30章_正文_v1.md" \
    --target-chars 2200 \
    --anchors "尾巴,獠牙,长牙,长毛,兽爪" \
    --jargon "妈的,老子,操,滚,屁,扯淡" \
    --style 干句 --min-adhesion 80 --min-dialogue 0.08 \
    --model deepseek-v4-pro --temperature 1.2 --retries 1

  --prompt-only   # 只打印将要发给 API 的 prompt，不调用
  --dry-guard     # 只对已有文本跑门禁：--check-file 文件

Key 来源：环境变量 DEEPSEEK_API_KEY，缺省读 C:\\Users\\<user>\\.dsh\\.credentials.yaml 的 refs。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR / "engine"))
sys.stdout.reconfigure(encoding="utf-8")

from novel_engine.model import cjk_count  # noqa: E402
from novel_engine.rules import load_project, load_rules  # noqa: E402
from novel_engine import style as style_engine  # noqa: E402

API_URL = "https://api.deepseek.com/chat/completions"

# ---------------------------------------------------------------- 硬门禁口径
CLICHE = [
    "菊花一紧", "胖爷", "瞳孔微缩", "倒吸一口凉气", "刹那间", "不禁", "顿时",
    "空气中弥漫", "这意味着", "换句话说", "也就是说", "仿佛在说", "像是在告诉",
    "似乎想说", "空气仿佛凝固", "心中一暖", "一阵温暖", "意味深长", "不易察觉",
    "嘴角勾起", "眼底闪过", "仿佛在诉说",
]
EXPLAIN_RE = re.compile(r"(这说明|这意味着|这说明他|换句话说|也就是说|仿佛在告诉|像是在说|似乎在暗示|这就是他|这表明)")
MONOLOGUE_RE = re.compile(r"(他感到|她感到|心里一阵|心中一暖|暗暗想|心里想|一阵恐惧|一阵温暖|他觉得自己)")
ODOR_RE = re.compile(r"(味|腥|臭|香|霉|烟|酒气|机油|汗|铁锈|血|盐|酸|馊|焦|潮)")
DIALOGUE_RE = re.compile(r"“[^”]{1,200}”")
DEFAULT_ANCHORS = ["尾巴", "獠牙", "长牙", "兽牙", "兽爪", "指甲", "指节", "鳞", "毛", "茧", "掌心", "喉结", "下颌", "脊椎", "腕骨", "手背"]
DEFAULT_JARGON = ["妈的", "他妈", "他妈的", "老子", "操", "滚", "屁", "傻", "扯淡", "放屁", "去你妈", "他娘的", "甭", "咋", "啥", "得嘞"]


def read_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    cred = pathlib.Path.home() / ".dsh" / ".credentials.yaml"
    if cred.exists():
        m = re.search(r"DEEPSEEK_API_KEY:\s*(\S+)", cred.read_text(encoding="utf-8"))
        if m:
            return m.group(1).strip()
    raise SystemExit("找不到 DEEPSEEK_API_KEY（环境变量或 ~/.dsh/.credentials.yaml）")




def load_anchor_config(project: str) -> dict:
    "读项目级锚点配置（写作规范/文风锚点.json），没配置就用内置默认。"
    proj = pathlib.Path(project)
    cands = [
        proj / "写作规范" / "文风锚点.json",
        proj.parents[1] / "写作规范" / "文风锚点.json" if len(proj.parents) > 1 else None,
    ]
    for cand in cands:
        if cand and cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
    return {}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="小说工坊：API 生成 + 硬门禁")
    ap.add_argument("--project", required=True, help="项目目录")
    ap.add_argument("--chapter-key", default="", help="章键，如 第30章")
    ap.add_argument("--title", default="", help="章标题（不含章号）")
    ap.add_argument("--beats-file", default="", help="细纲/节拍文件（md/txt）")
    ap.add_argument("--beats-text", default="", help="直接给节拍文字")
    ap.add_argument("--out", default="", help="输出 markdown 路径；留空只打印")
    ap.add_argument("--target-chars", type=int, default=2200, help="目标汉字数")
    ap.add_argument("--anchors", default="", help="本章必须出现的肢体锚点，逗号分隔")
    ap.add_argument("--jargon", default="", help="必须出现的底层口语/黑话，逗号分隔")
    ap.add_argument("--style", default="", help="文风档案名（如 干句），用于粘性门禁")
    ap.add_argument("--min-adhesion", type=float, default=80.0)
    ap.add_argument("--min-dialogue", type=float, default=0.0, help="对白占比下限；>0 时低于此值判失败（默认只警告）")
    ap.add_argument("--model", default="deepseek-v4-pro", help="模型；可再给 --fallback-model")
    ap.add_argument("--fallback-model", default="deepseek-flash")
    ap.add_argument("--temperature", type=float, default=1.2)
    ap.add_argument("--retries", type=int, default=1, help="门禁不通过时的重写轮数（默认 1，最多 2 次调用；无进展会自动停）")
    ap.add_argument("--prompt-only", action="store_true", help="只打印 prompt")
    ap.add_argument("--check-file", default="", help="只跑门禁：对已有文本")
    ap.add_argument("--save-prompt", action="store_true", help="把 prompt 存到 <out>.prompt.txt")
    return ap.parse_args()


def project_rules(project: str):
    cfg = load_project(project)
    rules = load_rules(project, cfg)
    return cfg, rules


def build_system_prompt(cfg: dict, rules, beats: str, target_chars: int, anchors: list[str], jargon: list[str], style_name: str) -> str:
    banned = [b.get("term") for b in rules.banned if b.get("term")]
    facts = []
    for rule in rules.facts:
        facts.append(f"- {getattr(rule, 'name', rule.id)}：{getattr(rule, 'why', '')}（禁止写出这类句子）")
    dnt = [x for x in rules.do_not_touch if x]
    lines = []
    lines.append(f"你是《{cfg.get('title') or '这本书'}》的作者本人，正在写正文。你不是在帮别人润色，你就是在写自己的书。")
    lines.append("")
    lines.append("【最高指令】任何一句若满足以下任一条件，就不写：")
    lines.append("1. 替读者下结论（这说明 / 这意味着 / 那是……）")
    lines.append("2. 为了前后连通补一句解释因果")
    lines.append("3. 段末升华、拔高、总结")
    lines.append("4. 与上一句同一个句式（连续排比）")
    lines.append("")
    lines.append("【文风】冷峻、克制、电影感：")
    lines.append("- 极低形容词密度：不堆四字成语，全用大白话；画面靠具体物件，不靠形容词。")
    lines.append("- 感官驱动：视觉（光/颜色/脏污）、听觉（动作声/环境声）、嗅觉（腥/机油/汗/霉）。")
    lines.append("- 对话生活化：底层粗人互怼，带错字、俚语、半截话；不文绉绉，不解释设定。")
    lines.append("- 动作锚点：每段抒情必须挂在一个具体动作上；心理只写生理反应，不写“他感到……”。")
    lines.append("- 禁止：内心独白、解释性旁白、上帝视角总结、网络梗、套话。")
    lines.append("")
    lines.append("【硬性规则】")
    lines.append(f"1. 全章必须至少有一处具体的**气味**描写（不是“空气很臭”，要具体到东西）。")
    lines.append(f"2. 全章必须至少有一处**角色身体细节**，以下词至少出现一个：{'、'.join(anchors)}。")
    lines.append(f"3. 全章必须至少有一句**符合底层身份的黑话/口语**，如：{'、'.join(jargon[:8])}。")
    lines.append("4. 绝对不写内心独白（“他感到一阵温暖/心里想”这类），只写动作、神态、环境。")
    lines.append("5. 禁止解释性旁白（“这说明他们成了朋友”“仿佛在告诉读者”）。")
    lines.append("6. 禁用这些套话/梗：" + "、".join(CLICHE))
    lines.append("7. 引号只用中文全角“”；不用“——”（破折号尽量 0）；不用省略号堆叠。")
    if banned:
        lines.append("8. 禁用词（一个都不许出现）：" + "、".join(banned))
    if facts:
        lines.append("9. 设定红线：")
        lines.extend("   " + x for x in facts)
    if dnt:
        lines.append("10. 作者语感，不许“修”：")
        lines.extend("   - " + x for x in dnt)
    if style_name:
        lines.append(f"11. 文风档案目标：{style_name}。")
    lines.append("")
    lines.append("【本章节拍】")
    lines.append(beats.strip() if beats.strip() else "（没有细纲，按上一章自然推进）")
    lines.append("")
    lines.append(f"【字数】约 {target_chars} 个汉字（±20% 都可以，不必精确）。")
    lines.append("")
    lines.append("【输出】只输出正文，不要标题、不要说明、不要分节小标题；段落之间空一行。")
    return "\n".join(lines)


def chat(messages: list[dict], model: str, temperature: float, key: str, max_tokens: int = 8192) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.95,
        "frequency_penalty": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["choices"][0]["message"].get("content") or "").strip(), data.get("usage") or {}


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text).strip()
    return text


def guard(text: str, rules, *, target_chars: int, anchors: list[str], jargon: list[str],
          style_name: str, project: str, min_adhesion: float, min_dialogue: float = 0.0) -> dict:
    fails: list[str] = []
    warns: list[str] = []
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    cjk = cjk_count(text)
    dialogue_chars = sum(cjk_count(m.group(0)) for m in DIALOGUE_RE.finditer(text))
    dialogue_ratio = dialogue_chars / max(cjk, 1)
    dash = text.count("——")
    metrics = {
        "cjk": cjk,
        "paragraphs": len(paras),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "dash": dash,
        "dash_per_k": round(dash / max(cjk, 1) * 1000, 2),
    }

    # 字数
    lo, hi = int(target_chars * 0.7), int(target_chars * 1.3)
    if not (lo <= cjk <= hi):
        warns.append(f"字数 {cjk} 偏离目标 {target_chars}（放宽区间 {lo}–{hi}，不触发重写）")

    # 禁用词
    hits = [b.get("term") for b in rules.banned if b.get("term") and str(b.get("term")) in text]
    metrics["banned_hits"] = hits
    if hits:
        fails.append("出现禁用词：" + "、".join(hits))

    # 设定红线
    fact_hits = []
    for rule in rules.facts:
        try:
            got = rule.matches(text)
        except Exception:  # noqa: BLE001
            got = []
        if got:
            sev = getattr(rule, "severity", "warn")
            fact_hits.append({"id": rule.id, "severity": sev, "why": getattr(rule, "why", "")})
    metrics["fact_hits"] = fact_hits
    hard_facts = [x for x in fact_hits if x["severity"] == "hard"]
    if hard_facts:
        fails.append("踩设定红线：" + "；".join(f"{x['id']}（{x['why']}）" for x in hard_facts))
    for x in fact_hits:
        if x["severity"] != "hard":
            warns.append(f"设定提醒：{x['id']}（{x['why']}）")

    # 套话/梗
    cliche_hits = [w for w in CLICHE if w in text]
    metrics["cliche_hits"] = cliche_hits
    if cliche_hits:
        fails.append("出现套话/梗：" + "、".join(cliche_hits))

    # 解释性旁白 / 内心独白
    exp = EXPLAIN_RE.findall(text)
    mono = MONOLOGUE_RE.findall(text)
    metrics["explain_hits"], metrics["monologue_hits"] = exp, mono
    if exp:
        fails.append("出现解释性旁白：" + "、".join(sorted(set(exp))))
    if mono:
        fails.append("出现内心独白：" + "、".join(sorted(set(mono))))

    # 三锚点
    odor = ODOR_RE.findall(text)
    anchor_hits = [a for a in anchors if a in text]
    jargon_hits = [j for j in jargon if j in text]
    metrics["odor_hits"], metrics["anchor_hits"], metrics["jargon_hits"] = len(odor), anchor_hits, jargon_hits
    if not odor:
        fails.append("没有气味描写（硬规则 1）")
    if not anchor_hits:
        fails.append("没有角色身体细节（硬规则 2）：候选 " + "、".join(anchors[:8]))
    if not jargon_hits:
        fails.append("没有底层黑话/口语（硬规则 3）")

    # 引号/标点
    if text.count('"') or text.count("'"):
        fails.append("出现半角引号")
    if dash > max(2, int(cjk / 1000 * 2) + 1):
        warns.append(f"破折号偏多（{dash} 处）")
    if "……" in text and text.count("……") > 6:
        warns.append("省略号偏多")

    # 对话比例
    if dialogue_ratio < 0.08:
        msg = f"对白占比偏低（{dialogue_ratio:.1%}）"
        if min_dialogue and dialogue_ratio < min_dialogue:
            fails.append(msg + f"，低于下限 {min_dialogue:.0%}")
        else:
            warns.append(msg)
    elif dialogue_ratio > 0.5:
        warns.append(f"对白占比偏高（{dialogue_ratio:.1%}）")

    # AI 腔规则（rules.ai）
    ai_hits = []
    for rule in rules.ai:
        try:
            got = rule.matches(text)
        except Exception:  # noqa: BLE001
            got = []
        if got:
            ai_hits.append({"id": rule.id, "count": len(got)})
    metrics["ai_rule_hits"] = ai_hits
    if ai_hits:
        warns.append("AI 腔规则命中：" + "、".join(f"{x['id']}×{x['count']}" for x in ai_hits))

    # 文风粘性
    if style_name:
        try:
            res = style_engine.check(project, style_name, text=text)
            metrics["style"] = {"name": style_name, "adhesion": res.get("adhesion"), "verdict": res.get("verdict")}
            if res.get("adhesion") is not None and res["adhesion"] < min_adhesion:
                fails.append(f"文风粘性 {res['adhesion']} < {min_adhesion}（目标 {style_name}）")
        except Exception as error:  # noqa: BLE001
            warns.append(f"文风检查失败：{error}")

    metrics["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"passed": not fails, "fails": fails, "warns": warns, "metrics": metrics}


def main() -> int:
    args = parse_args()
    project = str(pathlib.Path(args.project).resolve())
    cfg, rules = project_rules(project)

    anchor_cfg = load_anchor_config(project)
    global CLICHE, EXPLAIN_RE, MONOLOGUE_RE
    if anchor_cfg.get("banned_cliches"):
        CLICHE = list(anchor_cfg["banned_cliches"])
    regs = anchor_cfg.get("banned_regex") or []
    if len(regs) >= 1:
        EXPLAIN_RE = re.compile(regs[0])
    if len(regs) >= 2:
        MONOLOGUE_RE = re.compile(regs[1])
    body_words = []
    for words in (anchor_cfg.get("hard_anchors", {}).get("body_by_character", {}) or {}).values():
        body_words.extend(words)
    default_anchors = body_words or DEFAULT_ANCHORS
    default_jargon = anchor_cfg.get("hard_anchors", {}).get("jargon") or DEFAULT_JARGON

    anchors = [x.strip() for x in (args.anchors or ",".join(default_anchors)).split(",") if x.strip()]
    jargon = [x.strip() for x in (args.jargon or ",".join(default_jargon)).split(",") if x.strip()]

    # 只跑门禁
    if args.check_file:
        text = pathlib.Path(args.check_file).read_text(encoding="utf-8-sig")
        report = guard(text, rules, target_chars=args.target_chars, anchors=anchors, jargon=jargon,
                       style_name=args.style, project=project, min_adhesion=args.min_adhesion, min_dialogue=args.min_dialogue)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    beats = args.beats_text
    if args.beats_file:
        beats = (pathlib.Path(project) / args.beats_file).read_text(encoding="utf-8-sig") if not pathlib.Path(args.beats_file).is_absolute() else pathlib.Path(args.beats_file).read_text(encoding="utf-8-sig")
    system = build_system_prompt(cfg, rules, beats, args.target_chars, anchors, jargon, args.style)
    user = "按上面的要求，写" + (args.chapter_key or "这一章") + "的正文。只输出正文。"
    if args.prompt_only:
        print("=== SYSTEM ===\n" + system + "\n\n=== USER ===\n" + user)
        return 0

    key = read_key()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    draft = ""
    report = None
    prev_sig = None
    empty_streak = 0
    models = [args.model] + ([args.fallback_model] if args.fallback_model else [])
    for attempt in range(args.retries + 1):
        model = models[min(attempt, len(models) - 1)]
        t0 = time.time()
        content, usage = chat(messages, model, args.temperature, key)
        content = strip_fences(content)
        print(f"[attempt {attempt + 1}] {model} {time.time() - t0:.0f}s cjk={cjk_count(content)} usage={usage}")
        if not content:
            empty_streak += 1
            print("  空输出（可能被推理 token 吃满），换下一个模型")
            if empty_streak >= 2:
                print("  连续空输出，停止（防死磕）")
                break
            continue
        draft = content
        report = guard(draft, rules, target_chars=args.target_chars, anchors=anchors, jargon=jargon,
                       style_name=args.style, project=project, min_adhesion=args.min_adhesion, min_dialogue=args.min_dialogue)
        print("  门禁:", "PASS" if report["passed"] else "FAIL")
        for f in report["fails"]:
            print("   ✗", f)
        for w in report["warns"]:
            print("   !", w)
        sig = tuple(sorted(report["fails"]))
        if sig == prev_sig:
            print("  失败项和上一轮一模一样，再改也是死磕，停止")
            break
        prev_sig = sig
        if report["passed"] or attempt >= args.retries:
            break
        feedback = "你刚才这版没通过作者自己的硬门禁，逐条改，保留节拍、保留字数，只输出改好的完整正文：\n"
        feedback += "\n".join(f"- {f}" for f in report["fails"])
        feedback += "\n\n注意：不要解释、不要加旁白，不要总结，只写具体动作和对话。"
        messages = messages + [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": feedback},
        ]

    if not draft:
        print("生成失败：API 没有返回内容")
        return 2

    if args.out:
        out = pathlib.Path(args.out)
        if not out.is_absolute():
            out = pathlib.Path(project) / out
        out.parent.mkdir(parents=True, exist_ok=True)
        title = "# " + args.chapter_key + ((" " + args.title) if args.title else "")
        paras = [p.strip() for p in draft.splitlines() if p.strip()]
        out.write_text(title + "\n\n" + "\n\n".join(paras) + "\n", encoding="utf-8")
        qa_path = out.with_suffix(".qa.json")
        qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.save_prompt:
            out.with_suffix(".prompt.txt").write_text("=== SYSTEM ===\n" + system + "\n", encoding="utf-8")
        print("正文:", out)
        print("门禁报告:", qa_path)
        print("sha256:", report["metrics"]["sha256"][:16], "| cjk:", report["metrics"]["cjk"])
        print("本次共调用", attempt + 1, "次（硬上限", args.retries + 1, "次）")
    else:
        print("\n" + draft)
    return 0 if (report and report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
