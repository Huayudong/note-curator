#!/usr/bin/env python3
"""
html_extract.py — HTML → 结构化段落（B08-02）。

保持阅读顺序：表格/代码块先替换为占位符，与标题、段落合并排序后还原。
段落下限 8 字符（B08-02：保留有意义的短块，过滤按钮类噪声）。
"""

import html as html_mod
import re

DROP_TAGS_RE = re.compile(
    r"<(script|style|nav|footer|header|aside|form|noscript|iframe|svg)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_CHARSET_RE = re.compile(
    r"<meta[^>]+charset\s*=\s*[\"']?\s*([\w-]+)", re.IGNORECASE)
TABLE_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
PRE_RE = re.compile(r"<pre\b[^>]*>(.*?)</pre\s*>", re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1\s*>", re.IGNORECASE | re.DOTALL)
P_RE = re.compile(
    r"<(p|blockquote|li)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\u00a0]+")


def clean_text(s):
    s = html_mod.unescape(s)
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s)
    return s.strip()


def decode_bytes(raw):
    """charset 声明优先，再 utf-8/gbk/latin-1 兜底（中文 GBK 站点兼容）。"""
    head = raw[:2048].decode("latin-1", errors="ignore")
    m = META_CHARSET_RE.search(head)
    candidates = []
    if m:
        candidates.append(m.group(1))
    candidates += ["utf-8", "gbk", "latin-1"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def _para_split(text):
    pat = chr(92) + "n" + chr(92) + "s*" + chr(92) + "n"
    return [q for q in re.split(pat, text) if q.strip()]


def extract_segments(raw_html, max_chars):
    """返回 (title, segments, issues_internal, truncated, chars)。"""
    issues = []
    body = DROP_TAGS_RE.sub("", raw_html)
    body = COMMENT_RE.sub("", body)
    n_tables_raw = len(TABLE_RE.findall(raw_html))

    title = ""
    m = TITLE_RE.search(raw_html)
    if m:
        title = clean_text(m.group(1))

    placeholders = {}

    def stash(kind, frag):
        token = "@@NC_%s_%d@@" % (kind.upper(), len(placeholders))
        placeholders[token] = (kind, frag)
        return token

    body = TABLE_RE.sub(lambda mm: stash("table", mm.group(0)), body)
    body = PRE_RE.sub(lambda mm: stash("code", mm.group(1)), body)

    events = []
    for hm in HEADING_RE.finditer(body):
        events.append((hm.start(), "heading", hm.group(0)))
    for pm in P_RE.finditer(body):
        kind = {"p": "paragraph", "blockquote": "quote",
                "li": "list_item"}[pm.group(1).lower()]
        events.append((pm.start(), kind, pm.group(0)))
    for token, item in placeholders.items():
        pos = body.find(token)
        events.append((pos if pos >= 0 else (1 << 30),
                       "ph_" + item[0], item[1]))  # 存 frag 而不是 token
    events.sort(key=lambda item: item[0])

    segments = []
    newline = chr(10)
    for _, kind, frag in events:
        if kind == "ph_table":
            rows = []
            for tr in TR_RE.finditer(frag):
                cells = [clean_text(c.group(1))
                         for c in CELL_RE.finditer(tr.group(1))]
                cells = [c for c in cells if c]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                segments.append({"type": "table",
                                 "text": newline.join(rows)})
        elif kind == "ph_code":
            text = html_mod.unescape(frag).strip()
            if text:
                segments.append({"type": "code", "text": text})
        elif kind == "heading":
            text = clean_text(frag)
            if text:
                segments.append({"type": "heading", "text": text})
        else:
            text = clean_text(frag)
            if len(text) >= 8:
                segments.append({"type": kind, "text": text})

    if n_tables_raw and not any(s["type"] == "table" for s in segments):
        issues.append("table_missing_hint")

    kept = []
    truncated = False
    total = 0
    for seg in segments:
        if total >= max_chars:
            truncated = True
            break
        kept.append(seg)
        total += len(seg["text"])
    chars = sum(len(s["text"]) for s in kept)
    return title, kept, issues, truncated, chars
