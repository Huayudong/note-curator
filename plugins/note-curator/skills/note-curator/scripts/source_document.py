#!/usr/bin/env python3
"""
source_document.py — B08 统一来源管线：SourceDocument + 完整性状态机。

把输入源（URL / Markdown / TXT / HTML 文件）变成结构化、带状态的资料对象，
后续生成、归档、查重都消费这个结构，而不是各自去摸原始文本。

SourceDocument（schema 1）：
    {
      "schema": 1, "kind": "url"|"file",
      "source": "原始 URL 或路径",
      "source_normalized": "规范化 URL（去跟踪参数/锚点）",
      "content_fingerprint": "sha256(正文段落数据)",
      "fetched_at": "...", "title": "...",
      "segments": [{"type": "heading|paragraph|quote|code|table|list_item",
                    "text": "..."}],
      "stats": {"segments": n, "chars": n, "tables": n, "code_blocks": n},
      "extraction": {"status": "complete|incomplete|failed",
                     "issues": ["truncated", "short_body", ...],
                     "engine": "urllib|file",
                     "max_chars": n}
    }

完整性状态（B08-07，七类缺陷分开标注）：
    fetch_error:*      抓取失败（HTTP/网络）
    login_wall         疑似登录墙（正文含登录提示且内容很短）
    dynamic_page       疑似 JS 渲染页（抓到了但几乎没正文）
    short_body         正文过短（<200 字）
    truncated          触达 --max-chars 截断（默认 20000，截断必标注）
    pagination_suspected 原始 HTML 有「下一页」组件，可能缺分页
    table_missing_hint 原始 HTML 有 <table> 但提取结果为 0

安全边界（B08-08）：来源内容**是资料不是指令**——本管线绝不执行正文中
夹带的任何「修改配置/读取密钥/覆盖文件」类文字；<script> 作为非正文剔除。

用法：
    python source_document.py from-url "https://..." --out doc.json
    python source_document.py from-file 文章.html --out doc.json
    python source_document.py check doc.json [--strict]
    python source_document.py normalize-url "https://a.com/x/?utm_source=b#f"
    python source_document.py register --doc doc.json     # 登记到 ~/.note-curator/sources.json
    python source_document.py lookup --url "https://..."

退出码（check）：0 complete；1 incomplete；2 failed。
"""

import argparse
import hashlib
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

SCHEMA = 1
DEFAULT_MAX_CHARS = 20000

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
P_RE = re.compile(r"<(p|blockquote|li)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\u00a0]+")
MULTINL_RE = re.compile(r"\n{3,}")

LOGIN_HINTS = ("请登录", "登录后", "扫码登录", "登录/注册", "log in to continue",
               "sign in to read")
PAGINATION_HINTS = ("下一页", "下一頁", "next page", "pagination")

# URL 跟踪参数：精确名 + 前缀
TRACKING_PARAMS_EXACT = {"spm", "from", "vd", "nsukey", "share_token",
                         "share_id", "scene", "refer_flag", "fr", "fx"}
TRACKING_PARAMS_PREFIX = ("utm_", "share", "from_", "ref_")


def clean_text(s):
    s = html_mod.unescape(s)
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s)
    return s.strip()


def decode_bytes(raw):
    """charset 声明优先，再 utf-8/gbk/latin-1 兜底（中文 GBK 老站点兼容）。"""
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


def html_to_segments(raw_html, max_chars):
    """委托 html_extract（B08-02 的实现细节都在那边）。"""
    from html_extract import extract_segments
    return extract_segments(raw_html, max_chars)


def normalize_url(url):
    """URL 规范化（B08-09）：小写 scheme/host、去锚点与跟踪参数、去尾斜杠。"""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = "%s:%d" % (host, parts.port)
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        lk = k.lower()
        if lk in TRACKING_PARAMS_EXACT or any(
                lk.startswith(p) for p in TRACKING_PARAMS_PREFIX):
            continue
        query.append((k, v))
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path,
                       urlencode(query), ""))


def content_fingerprint(segments):
    payload = "\n".join(s["text"] for s in segments)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify(title, segments, issues, truncated, chars, max_chars):
    """七类缺陷状态判定（B08-07）。"""
    found = list(issues)
    if truncated:
        found.append("truncated")
    if chars < 200:
        found.append("short_body")
        joined = "".join(s["text"] for s in segments)[:400].lower()
        if any(h.lower() in joined for h in LOGIN_HINTS):
            found.append("login_wall")
        else:
            found.append("dynamic_page")
    status = "complete"
    hard = [i for i in found if i.startswith("fetch_error")]
    if hard or "short_body" in found:
        status = "failed"
    elif found:
        status = "incomplete"
    return status, found


def build_document(kind, source, title, segments, issues, status, engine,
                   max_chars):
    return {
        "schema": SCHEMA,
        "kind": kind,
        "source": source,
        "source_normalized": normalize_url(source) if kind == "url" else source,
        "content_fingerprint": content_fingerprint(segments),
        "fetched_at": nc_core.now_iso(),
        "title": title,
        "segments": segments,
        "stats": {"segments": len(segments),
                  "chars": sum(len(s["text"]) for s in segments),
                  "tables": sum(1 for s in segments if s["type"] == "table"),
                  "code_blocks": sum(1 for s in segments if s["type"] == "code")},
        "extraction": {"status": status, "issues": issues,
                       "engine": engine, "max_chars": max_chars},
    }


def fetch_raw(url, timeout):
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def issue_description(issue):
    table = {
        "truncated": "正文触达截断上限，可能不完整",
        "short_body": "正文过短，可能没有取到真正内容",
        "login_wall": "疑似登录墙（内容含登录提示）",
        "dynamic_page": "疑似 JS 渲染页（无静态正文）",
        "pagination_suspected": "页面含「下一页」组件，可能缺后续分页",
        "table_missing_hint": "原始页面有表格但未能提取",
    }
    if issue.startswith("fetch_error:"):
        return "抓取失败：" + issue.split(":", 1)[1]
    return table.get(issue, issue)


# ---------- 子命令 ----------

def cmd_from_url(args):
    source = args.url
    try:
        raw = fetch_raw(source, args.timeout)
        raw_html = decode_bytes(raw)
    except urllib.error.HTTPError as exc:
        doc = build_document("url", source, "", [], ["fetch_error:HTTP %s" % exc.code],
                             "failed", "urllib", args.max_chars)
        _emit(args, doc)
        sys.exit(0)  # 文档已产出；完整性由 check 子命令把关
    except Exception as exc:
        doc = build_document("url", source, "", ["fetch_error:%s" % exc],
                             "failed", "urllib", args.max_chars) if False else \
            build_document("url", source, "",
                           [], ["fetch_error:%s" % exc], "failed", "urllib",
                           args.max_chars)
        _emit(args, doc)
        sys.exit(0)  # 文档已产出；完整性由 check 子命令把关

    title, segments, issues, truncated, chars = html_to_segments(
        raw_html, args.max_chars)
    if any(h in raw_html.lower() for h in ("下一页", "next page")):
        issues.append("pagination_suspected")
    status, found = classify(title, segments, issues, truncated, chars,
                             args.max_chars)
    doc = build_document("url", source, title, segments, found, status,
                         "urllib", args.max_chars)
    _emit(args, doc)
    sys.exit(0)  # 文档已产出；完整性由 check 子命令把关


def cmd_from_file(args):
    path = Path(args.path).expanduser()
    if not path.is_file():
        print("[ERROR] 文件不存在: %s" % path, file=sys.stderr)
        sys.exit(1)
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")
    if suffix in (".html", ".htm"):
        title, segments, issues, truncated, chars = html_to_segments(
            text, args.max_chars)
        status, found = classify(title, segments, issues, truncated, chars,
                                 args.max_chars)
    else:
        title = ""
        segments = []
        for block in re.split(r"\n\s*\n", text):
            block = block.strip()
            if not block:
                continue
            if block.startswith("```"):
                segments.append({"type": "code", "text": block})
            elif block.startswith("#"):
                first, _, rest = block.partition("\n")
                segments.append({"type": "heading", "text": first.lstrip("#").strip()})
                if rest.strip():
                    segments.append({"type": "paragraph", "text": rest.strip()})
            elif block.startswith(">"):
                segments.append({"type": "quote",
                                 "text": block.lstrip("> ").strip()})
            else:
                segments.append({"type": "paragraph", "text": block})
        issues, truncated = [], False
        chars = sum(len(s["text"]) for s in segments)
        if not title:
            heads = [s["text"] for s in segments if s["type"] == "heading"]
            title = heads[0] if heads else path.stem
        status = "complete" if chars >= 200 else "incomplete"
        if chars < 200:
            found = ["short_body"]
        else:
            found = []
    doc = build_document("file", str(path), title, segments, found, status,
                         "file", args.max_chars)
    _emit(args, doc)
    sys.exit(0)  # 文档已产出；完整性由 check 子命令把关


def cmd_check(args):
    doc = _load_doc(args.doc)
    _exit_check(doc, strict=args.strict, quiet=args.json, emit_json=args.json)


def cmd_normalize_url(args):
    print(normalize_url(args.url))
    sys.exit(0)


def _load_doc(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit("[ERROR] SourceDocument 不存在: %s" % p)
    return json.loads(p.read_text(encoding="utf-8"))


def _emit(args, doc):
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    if getattr(args, "out", None):
        nc_core.atomic_write_text(args.out, payload)
        print("[OK] SourceDocument -> %s（%s：%d 段，%d 字）"
              % (args.out, doc["extraction"]["status"], doc["stats"]["segments"],
                 doc["stats"]["chars"]), file=sys.stderr)
    else:
        print(payload)
    for issue in doc["extraction"]["issues"]:
        print("[状态] %s：%s" % (issue, issue_description(issue)), file=sys.stderr)


def _exit_check(doc, strict=False, quiet=False, emit_json=False):
    status = doc["extraction"]["status"]
    if emit_json:
        print(json.dumps({"status": status, "issues": doc["extraction"]["issues"],
                          "stats": doc["stats"]}, ensure_ascii=False, indent=2))
    sys.exit({"complete": 0, "incomplete": 1 if strict else 0,
              "failed": 2}[status])


def _sources_path():
    return nc_core.data_root() / "sources.json"


def cmd_register(args):
    doc = _load_doc(args.doc)
    path = _sources_path()
    registry = {"sources": {}}
    if path.is_file():
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            registry = {"sources": {}}
    sources = registry.setdefault("sources", {})
    key = doc.get("source_normalized") or doc.get("source")
    entry = {
        "fingerprint": doc.get("content_fingerprint"),
        "title": doc.get("title", ""),
        "fetched_at": doc.get("fetched_at"),
        "kind": doc.get("kind"),
    }
    existed = sources.get(key)
    sources[key] = entry
    nc_core.atomic_write_text(path, json.dumps(registry, ensure_ascii=False,
                                               indent=2))
    if existed and existed.get("fingerprint") == entry["fingerprint"]:
        print("[SAME] 同一来源且内容未变（fingerprint 一致），无需重复整理。")
        sys.exit(2)
    if existed:
        print("[UPDATED] 来源已登记过且内容有更新（旧 fingerprint %s…）"
              % str(existed.get("fingerprint"))[:12])
        sys.exit(0)
    print("[NEW] 来源已登记：%s" % key)
    sys.exit(0)


def cmd_lookup(args):
    path = _sources_path()
    if not path.is_file():
        print("[MISS] 来源登记表为空。")
        sys.exit(2)
    registry = json.loads(path.read_text(encoding="utf-8")).get("sources", {})
    key = None
    if args.url:
        key = normalize_url(args.url)
    elif args.fingerprint:
        for k, v in registry.items():
            if v.get("fingerprint") == args.fingerprint:
                print(json.dumps({"url": k, **v}, ensure_ascii=False, indent=2))
                sys.exit(0)
    entry = registry.get(key) if key else None
    if entry:
        print(json.dumps({"url": key, **entry}, ensure_ascii=False, indent=2))
        sys.exit(0)
    print("[MISS] 登记表中没有该来源。")
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="统一来源管线")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("from-url", help="抓 URL -> SourceDocument")
    p1.add_argument("url")
    p1.add_argument("--out", help="写入 JSON 文件（默认打到 stdout）")
    p1.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p1.add_argument("--timeout", type=int, default=20)

    p2 = sub.add_parser("from-file", help="本地文件 -> SourceDocument")
    p2.add_argument("path")
    p2.add_argument("--out")
    p2.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    p3 = sub.add_parser("check", help="完整性检查")
    p3.add_argument("doc")
    p3.add_argument("--strict", action="store_true",
                    help="incomplete 也算不过（退出码 1）")
    p3.add_argument("--json", action="store_true")

    p4 = sub.add_parser("normalize-url", help="URL 规范化")
    p4.add_argument("url")

    p5 = sub.add_parser("register", help="登记来源（同源检测）")
    p5.add_argument("--doc", required=True)

    p6 = sub.add_parser("lookup", help="查来源登记")
    group = p6.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--fingerprint")

    args = ap.parse_args()
    {"from-url": cmd_from_url, "from-file": cmd_from_file, "check": cmd_check,
     "normalize-url": cmd_normalize_url, "register": cmd_register,
     "lookup": cmd_lookup}[args.cmd](args)


if __name__ == "__main__":
    main()
