#!/usr/bin/env python3
"""
find_duplicates.py — 对一篇新笔记在全库做查重，输出候选命中清单。

设计说明（重要）：
真正的「语义相似度」需要 embedding 模型，但本 skill 不假定环境装了这类库，
也不应擅自调用外部 API（隐私/费用）。因此本脚本只做**可复现的关键词级初筛**：
  - 对新笔记提取关键词（高频实词 + 标题词）
  - 与库中每篇笔记做 Jaccard / 词频重叠打分
  - 输出 Top-N 候选及其重叠度（0~1）

最终的「是否真为重复 / 该合并哪些段落 / 语义相似度」由 LLM 在拿到候选清单后
结合两篇正文做语义判断。本脚本只负责把 300+ 篇缩小到少数几个候选，供 LLM 精读。

这样划分职责：脚本=确定性初筛，LLM=语义裁决与合并建议。两者都不越界。

用法:
    # 用 scan 产出的索引
    python find_duplicates.py --index index.json --query-file new_note.md
    # 或直接传查询文本
    python find_duplicates.py --index index.json --query "大模型 Transformer 自注意力机制"
    # 控制候选数与阈值
    python find_duplicates.py --index index.json --query "..." --top 5 --min-score 0.15

输出 JSON（按 score 降序）:
    [
      {"title":"LLM 大模型","path":"04 人工智能/LLM 大模型.md","score":0.42,
       "overlap_terms":["大模型","transformer","注意力"], "body":"<摘要>"},
      ...
    ]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from langdetect import detect_language

# 中文停用词（轻量版，够用即可）
STOPWORDS = set("""
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 那
与 及 或 等 把 被 让 从 向 为 以 对 按 据 由 给 跟 和 与 因为 所以 但是 如果 虽然 然后 而
什么 怎么 哪 哪些 这个 那个 这些 那些 可以 可能 需要 应该 进行 通过 使用 利用 基于 根据
内容 进行 一些 许多 很多 非常 比较 更加 更加 例如 比如 即 也就是 也就是
the a an of to in on is are for and with that this it as be by at
""".split())

# 把中英文混排文本切成「词/token」：英文按单词、中文按 2-3 字滑动 + 单字
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-+.]*|\d+|[\u4e00-\u9fff]")


def _stem_en(word: str) -> str:
    """轻量英文词形归一（零依赖）：复数/时态/派生后缀折叠，提升查重召回。

    只追求「同词根归一」，不追求语言学正确；中文 token 原样返回。
    """
    w = word.lower().removesuffix("'s")
    if re.fullmatch(r"[a-z]+", w):
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("sses"):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        if w.endswith("ation") and len(w) > 7:
            w = w[:-5] + "ate"
        if w.endswith("ing") and len(w) > 5:
            w = w[:-3]
        elif w.endswith("ed") and len(w) > 4:
            w = w[:-2]
        if w.endswith("al") and len(w) > 6:
            w = w[:-2]
        if w.endswith("e") and len(w) > 4:
            w = w[:-1]
        # 双写辅音折叠：running -> runn -> run，与 runs 对齐
        if len(w) > 4 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
    return w


def tokenize(text: str):
    """混合分词：英文整词（归一化词形）、中文 2-gram + 单字，去停用词、去纯标点。"""
    text = text.lower()
    raw = WORD_RE.findall(text)
    # 重组连续中文段做 2-gram
    tokens = []
    buf = []
    for t in raw:
        if "\u4e00" <= t[0] <= "\u9fff":
            buf.append(t)
        else:
            if buf:
                tokens.extend(_zh_ngrams(buf))
                buf = []
            if t not in STOPWORDS and len(t) > 1 or t.isdigit():
                tokens.append(_stem_en(t))
    if buf:
        tokens.extend(_zh_ngrams(buf))
    return [t for t in tokens if t and t not in STOPWORDS]


def _zh_ngrams(chars):
    """对一段连续中文字符生成 2-gram（+少量单字）。"""
    out = []
    for i in range(len(chars) - 1):
        out.append(chars[i] + chars[i + 1])
    if len(chars) <= 3:
        out.extend(chars)  # 短串补单字
    return out


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def overlap_coef(a: set, b: set) -> float:
    """重叠系数：|A∩B| / min(|A|,|B|)。对「查询短、库笔记长」更友好。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def find_dup(index, query_text, top=5, min_score=0.15, lang="auto"):
    """查重初筛。lang=auto 时按查询语言过滤同语言笔记；all 不过滤。"""
    q_tokens = tokenize(query_text)
    q_set = set(q_tokens)
    q_freq = Counter(q_tokens)
    query_lang = detect_language(query_text)
    if lang == "auto":
        lang = query_lang

    hits = []
    for note in index:
        if lang != "all" and note.get("language", query_lang) != lang:
            continue
        title_tokens = tokenize(note.get("title", "") or "")
        n_tokens = tokenize(note.get("title", "") + " " + note.get("body", ""))
        n_set = set(n_tokens)
        title_set = set(title_tokens)
        # 综合分：jaccard 主、overlap 兜底（避免短查询漏检），标题命中再加权
        j = jaccard(q_set, n_set)
        o = overlap_coef(q_set, n_set)
        score = max(j, 0.6 * o) + min(0.05 * len(q_set & title_set), 0.15)
        if score < min_score:
            continue
        overlap_terms = sorted(q_set & n_set, key=lambda t: -q_freq.get(t, 0))[:12]
        hits.append({
            "title": note.get("title"),
            "path": note.get("path"),
            "language": note.get("language"),
            "score": round(score, 3),
            "overlap_terms": overlap_terms,
            "body": note.get("body", "")[:300],
        })
    hits.sort(key=lambda x: -x["score"])
    return hits[:top]


def main():
    ap = argparse.ArgumentParser(description="对新笔记在全库做查重初筛。")
    ap.add_argument("--index", required=True, help="scan_vault.py 产出的索引 JSON")
    ap.add_argument("--query", help="查询文本（与 --query-file 二选一）")
    ap.add_argument("--query-file", help="读取该文件作为查询文本")
    ap.add_argument("--top", type=int, default=5, help="返回候选数（默认 5）")
    ap.add_argument("--min-score", type=float, default=0.15, help="最低分数阈值（默认 0.15）")
    ap.add_argument("--lang", choices=["auto", "zh", "en", "all"], default="auto",
                    help="只在同语言笔记中查重（auto=跟随查询语言）；all 不过滤")
    ap.add_argument("--out", help="可选：写入文件；不给则打到 stdout")
    args = ap.parse_args()

    if args.query_file:
        query_text = open(args.query_file, encoding="utf-8").read()
    elif args.query:
        query_text = args.query
    else:
        print("[ERROR] 必须提供 --query 或 --query-file", file=sys.stderr)
        sys.exit(1)

    index = json.load(open(args.index, encoding="utf-8"))
    hits = find_dup(index, query_text, top=args.top, min_score=args.min_score, lang=args.lang)
    data = json.dumps(hits, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(data, encoding="utf-8")
        print(f"[OK] {len(hits)} 个候选 -> {args.out}", file=sys.stderr)
    else:
        print(data)


if __name__ == "__main__":
    main()
