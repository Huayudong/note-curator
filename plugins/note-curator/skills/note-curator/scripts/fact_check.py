#!/usr/bin/env python3
"""
fact_check.py — B04 事实保真与篇幅检查。

三件事（全部确定性、可复现）：
  1. 关键事实保留（B04-03/05）：从来源材料提取 SourceFact——数字与单位、
     百分比、日期、限定词（可能/通常/仅…时/预计）、否定词——逐一核对
     草稿是否保留；语义级核对仍由 Agent 与人工负责，本脚本只兜底
     「静默丢失/篡改」。
  2. 篇幅软预算（B04-11）：中文按字（一般 600-1200），英文按词
     （350-700）；超过硬上限（zh 1500 / en 900）标记 needs_split_review。
     预算是软约束：不硬凑字数，也不为达标删必要条件。
  3. 尾部链接清单违规（B01/B03 双链约定）：检测「相关笔记/关联/
     Related/See also」等文末小节，命中即违规——生成内容不允许用
     文末堆链接代替正文知识点建链。

CLI：
    python fact_check.py --source src.md --draft draft.md [--lang auto] [--json] [--strict]

退出码：0 通过；1 --strict 且有关键事实缺失；2 尾部链接清单违规（阻断）。
"""

import argparse
import json
import re
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from langdetect import detect_language_detail

# ---------- SourceFact 抽取（B04-03） ----------

NUMBER_RE = re.compile(
    r"\d[\d,\.]*\s*(?:%|万|亿|千|百万|十亿|ms|s|min|分钟|小时|天|周|月|年|"
    r"GB|MB|KB|TB|GiB|MiB|px|秒|倍|条|个|人|次|元|美元|词|字)?", re.IGNORECASE)
DATE_RE = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{4}[-/]\d{2}[-/]\d{2}|\d{4} 年(?:度)?")
ZH_LIMIT_RE = re.compile(
    r"可能|或许|大概|通常|一般|往往|某些条件下|在[^。，；]{0,12}条件下|仅在|"
    r"预计|估计|据[^。，；]{0,8}(?:统计|报道|测算)|未必|不一定|倾向于|有望")
EN_LIMIT_RE = re.compile(
    r"\b(?:maybe|perhaps|possibly|probably|usually|often|generally|typically|"
    r"estimated?|roughly|approximately|around|about|up to|at least|only(?: under)?|"
    r"may|might|could|likely|reportedly|according to)\b", re.IGNORECASE)
NEG_RE = re.compile(
    r"无法|不能|不会|没有|不适用|不支持|不宜|禁止|不得|并未|并非|"
    r"cannot|can't|won't|do(?:es)? not|"
    r"not (?:applicable|supported|possible)", re.IGNORECASE)

ZH = "zh"
EN = "en"

BUDGET = {
    ZH: {"soft_low": 600, "soft_high": 1200, "hard_high": 1500, "unit": "字"},
    EN: {"soft_low": 350, "soft_high": 700, "hard_high": 900, "unit": "words"},
}

TAIL_HEADER_RE = re.compile(
    r"^#{1,6}\s*(?:相关笔记|相关|关联|延伸阅读|参考资料之外的?相关|related(?: notes| links)?|"
    r"see also|further reading)\s*[:：]?\s*$", re.IGNORECASE | re.MULTILINE)


def _norm_ws(text):
    """比较用归一：全角数字/空白折叠（不做单位换算，B10 再扩展）。"""
    return re.sub(r"\s+", "", text)


def extract_facts(source_text):
    """从来源提取 SourceFact 清单：[{kind, text}]。"""
    facts = []
    seen = set()

    def add(kind, text):
        text = text.strip()
        key = (kind, _norm_ws(text))
        if text and key not in seen:
            seen.add(key)
            facts.append({"kind": kind, "text": text})

    dates = []
    for m in DATE_RE.finditer(source_text):
        add("date", m.group(0))
        dates.append(m.span())
    # 数字从「抹掉日期」后的文本里提取，避免 2026-09-30 被拆成 30、09 等伪事实
    masked = list(source_text)
    for start, end in dates:
        for i in range(start, end):
            masked[i] = " "
    masked_text = "".join(masked)
    for m in NUMBER_RE.finditer(masked_text):
        token = m.group(0)
        # 纯序号/年份之外的数字才算事实；纯 1-2 位小数字易误报，保留 ≥2 位或带单位
        digits = re.sub(r"\D", "", token)
        if len(digits) >= 2 or (token and token[-1].isalpha()) or "%" in token:
            add("number", token)
    for m in ZH_LIMIT_RE.finditer(source_text):
        add("limit", m.group(0))
    for m in EN_LIMIT_RE.finditer(source_text):
        add("limit", m.group(0))
    for m in NEG_RE.finditer(source_text):
        add("negation", m.group(0))
    return facts


def check_retention(source_text, draft_text):
    """逐条核对事实是否在草稿中保留。返回 (report, missing_count)。"""
    facts = extract_facts(source_text)
    draft_norm = _norm_ws(draft_text)
    draft_lower = draft_text.lower()
    results = []
    missing = 0
    for fact in facts:
        if fact["kind"] in ("number", "date"):
            retained = _norm_ws(fact["text"]) in draft_norm
        else:
            # 限定词/否定词：按原文词面（大小写不敏感）核对
            retained = fact["text"].lower() in draft_lower
        results.append({"kind": fact["kind"], "text": fact["text"],
                        "retained": retained})
        if not retained:
            missing += 1
    total = len(results)
    ratio = (total - missing) / total if total else None
    report = {
        "facts_total": total,
        "facts_missing": missing,
        "retention_ratio": round(ratio, 4) if ratio is not None else None,
        "missing": [r for r in results if not r["retained"]],
    }
    return report, missing


# ---------- 篇幅预算（B04-11） ----------

def draft_size(draft_text, lang):
    from style_metrics import clean_markdown
    clean = clean_markdown(draft_text)
    if lang == ZH:
        return len(re.sub(r"\s+", "", clean))
    return len(re.findall(r"[A-Za-z][A-Za-z0-9'-]*", clean))


def check_budget(draft_text, lang):
    budget = BUDGET[lang]
    size = draft_size(draft_text, lang)
    return {
        "lang": lang,
        "unit": budget["unit"],
        "size": size,
        "soft_range": [budget["soft_low"], budget["soft_high"]],
        "hard_high": budget["hard_high"],
        "within_soft": budget["soft_low"] <= size <= budget["soft_high"],
        "needs_split_review": size > budget["hard_high"],
    }


# ---------- 尾部链接清单检测（B01/B03 双链约定） ----------

def check_tail_list(draft_text):
    """检测文末「相关笔记/Related」类小节。返回违规详情（无违规为 None）。"""
    for m in TAIL_HEADER_RE.finditer(draft_text):
        rest = draft_text[m.end():]
        body = rest.split("\n#", 1)[0]
        if re.search(r"\[\[", body):
            return {
                "header": m.group(0).strip(),
                "excerpt": body.strip()[:200],
                "reason": "文末链接清单违反双链约定：链接应写在正文知识点出现的位置",
            }
    return None


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="事实保留 / 篇幅预算 / 尾部清单检查")
    ap.add_argument("--source", required=True, help="来源材料文件")
    ap.add_argument("--draft", required=True, help="生成草稿文件")
    ap.add_argument("--lang", choices=["auto", ZH, EN], default="auto")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="关键事实缺失时退出码 1（默认仅报告）")
    args = ap.parse_args()

    source_text = Path(args.source).read_text(encoding="utf-8", errors="ignore")
    draft_text = Path(args.draft).read_text(encoding="utf-8", errors="ignore")

    lang = args.lang
    if lang == "auto":
        detail = detect_language_detail(source_text)
        lang = detail["primary"] if detail["primary"] in (ZH, EN) else ZH

    retention, missing = check_retention(source_text, draft_text)
    budget = check_budget(draft_text, lang)
    tail = check_tail_list(draft_text)

    report = {
        "ok": missing == 0 and tail is None,
        "retention": retention,
        "budget": budget,
        "tail_violation": tail,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        unit = budget["unit"]
        print("事实保留：%d/%d%s" % (
            retention["facts_total"] - retention["facts_missing"],
            retention["facts_total"],
            "" if retention["retention_ratio"] is None
            else "（%.0f%%）" % (retention["retention_ratio"] * 100)))
        for item in retention["missing"][:10]:
            print("  [缺失] %s：%s" % ({"number": "数字", "date": "日期",
                                      "limit": "限定词",
                                      "negation": "否定"}[item["kind"]],
                                      item["text"]))
        print("篇幅：%d %s（软预算 %d-%d，硬上限 %d）%s" % (
            budget["size"], unit, budget["soft_range"][0],
            budget["soft_range"][1], budget["hard_high"],
            "——超硬上限，需主题与拆分审查" if budget["needs_split_review"] else ""))
        if tail:
            print("[违规] %s" % tail["reason"])
            print("       小节：%s" % tail["header"])
        else:
            print("尾部清单：无违规")

    if args.strict and missing:
        sys.exit(1)
    if tail:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
