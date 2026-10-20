#!/usr/bin/env python3
"""
search_notes.py — B07 知识检索：全文分块召回 + 跨语言概念桥接。

输入 index_vault.py 的分块索引；对查询做词项召回，输出**候选**：
    - 同语言命中：标题/别名/正文块重合度打分，附证据块与位置（pos_ratio）；
    - 跨语言命中：查询词命中概念桥（language-packs/*/concepts.json）时，
      用对应外语概念检索另一语言的笔记，结果标 cross_language 与桥接词。

设计边界（B07-04/05）：检索只给候选与证据；重复/补充/关联/矛盾由 Agent
结合两篇正文裁决，相似分不等于合并概率。可选 embedding 是独立增强，
不存在时基础路径完整可用（B07-02/07 验收）。

用法：
    python search_notes.py --index index.json --query "缓存失效 恢复演练" \
        [--top 5] [--lang auto|zh|en|all] [--min-score 0.12] [--json]
退出码：0 有候选；2 无候选；1 参数错误。
"""

import argparse
import json
import re
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from find_duplicates import tokenize, STOPWORDS, WORD_RE
from langdetect import detect_language
from resource_pack import load_pack

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_coef(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def load_concepts(lang):
    """加载概念桥：[{zh, en}]。语言键是 zh/en（pack 目录映射在 resource_pack）。"""
    pack_lang = "zh" if lang == "zh-CN" else lang
    pack, _ = load_pack(pack_lang)
    if not pack:
        return []
    from resource_pack import pack_path
    path = pack_path(pack_lang, "concepts.json")
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [c for c in items if c.get("zh") and c.get("en")]


def concept_bridges(query_text, lang, concepts):
    """查询文本命中的概念桥：返回 [(对方语言词, 本方词)]。"""
    bridges = []
    q = query_text.lower()
    for c in concepts:
        mine = str(c.get(lang) or "")
        theirs_lang = "en" if lang == "zh" else "zh"
        theirs = str(c.get(theirs_lang) or "")
        if mine and mine.lower() in q:
            bridges.append((theirs_lang, theirs, mine))
    return bridges


def score_chunk(q_tokens, q_set, chunk, title_set, alias_set):
    c_tokens = tokenize(chunk)
    c_set = set(c_tokens)
    j = jaccard(q_set, c_set)
    o = overlap_coef(q_set, c_set)
    score = max(j, 0.6 * o)
    extra = q_set & (title_set | alias_set)
    score += min(0.05 * len(extra), 0.15)
    return score, c_set


def search(index, query_text, top=5, lang="auto", min_score=0.12):
    concepts = load_concepts("zh") or load_concepts("en")
    query_lang = detect_language(query_text)
    if lang == "auto":
        lang = query_lang

    q_tokens = tokenize(query_text)
    q_set = set(q_tokens)
    results = []
    bridges = concept_bridges(query_text, lang, concepts) if lang in ("zh", "en") else []

    for rel, entry in index.get("files", {}).items():
        note_lang = entry.get("language", "")
        if lang != "all" and note_lang not in (lang, "und"):
            continue
        title_set = set(tokenize(entry.get("title", "")))
        alias_set = set(tokenize(" ".join(entry.get("aliases", []))))
        best = None
        for chunk in entry.get("chunks", []):
            score, _ = score_chunk(q_tokens, q_set, chunk.get("text", ""),
                                   title_set, alias_set)
            if best is None or score > best[0]:
                best = (score, chunk)
        if best:
            score, chunk = best
            if score >= min_score:
                results.append({
                    "path": rel,
                    "title": entry.get("title"),
                    "language": note_lang,
                    "score": round(score, 3),
                    "evidence": {
                        "chunk_id": chunk["id"],
                        "heading": chunk.get("heading", ""),
                        "pos_ratio": chunk.get("pos_ratio", 0),
                        "excerpt": chunk["text"][:160],
                    },
                    "cross_language": False,
                })

    # 跨语言概念桥：查询词命中本方概念 → 用对方概念检索另一语言笔记
    if lang in ("zh", "en"):
        other_lang = "en" if lang == "zh" else "zh"
        for theirs_lang, theirs, mine in bridges:
            b_tokens = tokenize(theirs)
            b_set = set(b_tokens)
            for rel, entry in index.get("files", {}).items():
                if entry.get("language") != theirs_lang:
                    continue
                title_set = set(tokenize(entry.get("title", "")))
                alias_set = set(tokenize(" ".join(entry.get("aliases", []))))
                best = None
                for chunk in entry.get("chunks", []):
                    score, _ = score_chunk(b_tokens, b_set,
                                           chunk.get("text", ""),
                                           title_set, alias_set)
                    if best is None or score > best[0]:
                        best = (score, chunk)
                if best and best[0] >= min_score:
                    results.append({
                        "path": rel,
                        "title": entry.get("title"),
                        "language": theirs_lang,
                        "score": round(best[0], 3),
                        "evidence": {
                            "chunk_id": best[1]["id"],
                            "heading": best[1].get("heading", ""),
                            "pos_ratio": best[1].get("pos_ratio", 0),
                            "excerpt": best[1]["text"][:160],
                        },
                        "cross_language": True,
                        "concept_bridge": "%s ↔ %s" % (mine, theirs),
                    })

    seen = set()
    deduped = []
    for r in sorted(results, key=lambda x: -x["score"]):
        key = (r["path"], r["evidence"]["chunk_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped[:top]


def main():
    ap = argparse.ArgumentParser(description="分块索引检索（含跨语言概念桥）")
    ap.add_argument("--index", required=True, help="index_vault.py 产出的索引")
    ap.add_argument("--query", required=True)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--lang", choices=["auto", "zh", "en", "all"], default="auto")
    ap.add_argument("--min-score", type=float, default=0.12)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    index_path = Path(args.index)
    if not index_path.is_file():
        print("[ERROR] 索引不存在: %s" % index_path, file=sys.stderr)
        sys.exit(1)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    hits = search(index, args.query, top=args.top, lang=args.lang,
                  min_score=args.min_score)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    else:
        for h in hits:
            tag = "（跨语言：%s）" % h["concept_bridge"] if h.get("cross_language") else ""
            print("%.3f  %s  %s%s" % (h["score"], h["path"], h["title"], tag))
            print("      证据：%s（位置 %.0f%%）"
                  % (h["evidence"]["heading"] or "正文",
                     h["evidence"]["pos_ratio"] * 100))
    sys.exit(0 if hits else 2)


if __name__ == "__main__":
    main()
