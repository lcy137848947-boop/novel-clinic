# -*- coding: utf-8 -*-
"""v4 A 部分指标在 6 号稿上的实测（用于方案评审，不写回项目）。"""
from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE))
sys.stdout.reconfigure(encoding="utf-8")

from novel_engine.model import cjk_count, dialogue_spans, load_book, split_sentences  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit("用法：python tools/probe_v4_metrics.py <主稿路径.docx|.md|.txt>")
BOOK = Path(sys.argv[1])
if not BOOK.exists():
    raise SystemExit(f"主稿不存在：{BOOK}")

TRANSITION = ["然而", "于是", "不禁", "仿佛", "竟然", "此外", "值得注意的是", "显然", "不由得", "顿时"]
GRANDEUR = ["标志着", "见证了", "体现了", "证明了", "至关重要", "关键转折点", "不可磨灭", "深深植根于", "彰显了", "象征着", "反映了"]
PROMO = ["充满活力", "令人叹为观止", "开创性", "极致", "震撼", "史诗级"]
HOLLOW = ["未来可期", "一切才刚刚开始", "故事还在继续", "等待着他的", "无人知晓", "谁也不知道"]


def sentence_cjk(s: str) -> int:
    return cjk_count(s)


def main() -> None:
    book = load_book(BOOK)
    cjk = book.cjk
    print(f"book: {len(book.chapters)} chapters, cjk={cjk}, paras={len(book.paragraphs)}")
    rows = []
    for ch in book.chapters:
        sents = []
        para_short = []
        for p in ch.paragraphs:
            ss = split_sentences(p.text)
            if not ss:
                continue
            sents.extend(ss)
            if ss:
                para_short.append(sum(1 for s in ss if sentence_cjk(s) <= 8) / len(ss))
        if not sents:
            continue
        lens = [sentence_cjk(s) for s in sents]
        ratio_short = statistics.mean(para_short) if para_short else 0
        std = statistics.pstdev(lens) if len(lens) > 1 else 0

        def per_k(count: int) -> float:
            return count / (ch.cjk or 1) * 1000

        s3 = len(re.findall(r"他[^，。]{1,4}了一下", ch.text))
        s5 = ch.text.count("——")
        s6 = len(re.findall(r"[^\s，]{2,6}[、，][^\s，]{2,6}[、，和与及][^\s，]{2,6}", ch.text))
        s7 = len(re.findall(r"不[只仅是][^。]{0,20}(?:而是|更是|而且)", ch.text))
        dlg = sum(cjk_count(p.text[s:e]) for p in ch.paragraphs for s, e in dialogue_spans(p.text))
        dlg_ratio = dlg / (ch.cjk or 1)
        w1 = sum(ch.text.count(w) for w in TRANSITION)
        w2 = sum(ch.text.count(w) for w in GRANDEUR)
        w3 = sum(ch.text.count(w) for w in PROMO)
        w4 = sum(1 for t in HOLLOW if t in ch.text)
        rows.append({
            "ch": ch.index, "title": ch.title, "cjk": ch.cjk,
            "S1": round(ratio_short, 3), "S2": round(std, 1),
            "S3": round(per_k(s3), 2), "S5": round(per_k(s5), 2),
            "S6": s6, "S7": s7, "S8": round(dlg_ratio, 3),
            "W1": round(per_k(w1), 2), "W2": round(per_k(w2), 2), "W3": round(per_k(w3), 2), "W4": w4,
        })

    # S4 相邻段首句同头率（近似：相邻段首句前 2 字相同）
    s4_ch = {}
    for ch in book.chapters:
        firsts = []
        for p in ch.paragraphs:
            ss = split_sentences(p.text)
            if ss:
                firsts.append(re.sub(r"^[“”‘’「」『』\s]+", "", ss[0])[:2])
        pairs = len(firsts) - 1
        same = sum(1 for a, b in zip(firsts, firsts[1:]) if a and a == b)
        s4_ch[ch.index] = same / pairs if pairs else 0
    for r in rows:
        r["S4"] = round(s4_ch.get(r["ch"], 0), 3)

    # 章级表
    hdr = "ch | 字 | S1短句 | S2句长std | S3他X一下 | S4同头 | S5破折号 | S6三段 | S7否定排比 | S8对白比 | W1过渡 | W2拔高 | W3宣传 | W4空结尾"
    print(hdr)
    for r in rows:
        print(f"{r['ch']:>2} | {r['cjk']:>4} | {r['S1']:>6} | {r['S2']:>7} | {r['S3']:>8} | {r['S4']:>6} | {r['S5']:>7} | {r['S6']:>5} | {r['S7']:>8} | {r['S8']:>6} | {r['W1']:>5} | {r['W2']:>5} | {r['W3']:>5} | {r['W4']:>5}")

    def agg(key, fn):
        vals = [r[key] for r in rows]
        return fn(vals)

    print("\n== 全书聚合 ==")
    for key, name in [("S1", "短句密度"), ("S2", "句长方差"), ("S3", "他X了一下/千字"), ("S4", "首句同头率"),
                      ("S5", "破折号/千字"), ("S6", "三段式/章"), ("S7", "否定排比/章"), ("S8", "对白比"),
                      ("W1", "过渡词/千字"), ("W2", "拔高词/千字"), ("W3", "宣传词/千字"), ("W4", "空结尾/章")]:
        vals = [r[key] for r in rows]
        print(f"{name:<14} 均值={statistics.mean(vals):>7.3f}  中位={statistics.median(vals):>7.3f}  最小={min(vals):>7.3f}  最大={max(vals):>7.3f}")

    # 按文档默认阈值命中统计
    print("\n== 按 v4 默认阈值，命中黄/红区的章 ==")
    checks = [
        ("S1 短句密度", "S1", lambda v: "绿" if v < 0.35 else "黄" if v <= 0.50 else "红"),
        ("S2 句长std", "S2", lambda v: "绿" if v > 6.0 else "黄" if v >= 4.0 else "红"),
        ("S3 他X/千字", "S3", lambda v: "绿" if v < 1.0 else "黄" if v <= 2.5 else "红"),
        ("S4 同头率", "S4", lambda v: "绿" if v < 0.20 else "黄" if v <= 0.35 else "红"),
        ("S5 破折号/千字", "S5", lambda v: "绿" if v < 1.5 else "黄" if v <= 3.0 else "红"),
        ("S6 三段式/章", "S6", lambda v: "绿" if v < 3 else "黄" if v <= 6 else "红"),
        ("S7 否定排比/章", "S7", lambda v: "绿" if v < 1 else "黄" if v <= 2 else "红"),
        ("W1 过渡词/千字", "W1", lambda v: "绿" if v < 2.0 else "黄" if v <= 4.0 else "红"),
        ("W2 拔高词/千字", "W2", lambda v: "绿" if v < 0.8 else "黄" if v <= 2.0 else "红"),
        ("W3 宣传词/千字", "W3", lambda v: "绿" if v < 1.0 else "黄" if v <= 2.5 else "红"),
        ("W4 空结尾/章", "W4", lambda v: "绿" if v == 0 else "黄" if v == 1 else "红"),
    ]
    for name, key, classify in checks:
        counts = {"绿": 0, "黄": 0, "红": 0}
        for r in rows:
            counts[classify(r[key])] += 1
        print(f"{name:<16} 绿{counts['绿']:>2} 黄{counts['黄']:>2} 红{counts['红']:>2}")


if __name__ == "__main__":
    main()
