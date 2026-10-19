#!/usr/bin/env python3
"""
fetch_url.py — 抓取 URL 正文，输出清洗后的纯文本，供 LLM 消化。

设计说明：
正文提取做到 100% 通用很难，本脚本采取「稳健优先」策略：
  1. 只用标准库（urllib），不引入 readability/goose 等。
  2. 去掉 <script>/<style>/<nav>/<footer>/<header>/<aside>/<form> 等明显非正文块。
  3. 取 DOM 中文本最密集的若干 <p> / <li> / <h*> 拼接为正文。
  4. 输出「标题 + 正文」，正文已去 HTML 实体、折叠空白。

对于 JS 渲染的页面（正文需执行 JS 才出现）本脚本抓不到——此时 skill 应
回退让 LLM 用自带的 WebFetch / web_reader 工具去读。脚本顶部会在失败时
给出明确提示。

用法:
    python fetch_url.py "https://example.com/article"
    python fetch_url.py "https://..." --out article.txt
    python fetch_url.py "https://..." --max-chars 8000   # 正文截断字数（默认 10000）
"""

import argparse
import html
import re
import sys
import urllib.request
import urllib.error

# 明确剔除的标签（整块连标签一起去）
DROP_TAGS = re.compile(
    r"<(script|style|nav|footer|header|aside|form|noscript|iframe|svg)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# 注释
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
# 正文候选标签
BLOCK_RE = re.compile(r"<(p|li|h[1-6]|blockquote|pre)[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
MULTINL_RE = re.compile(r"\n{3,}")


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # 编码探测：优先声明的 charset，否则尝试 utf-8 再退 gbk
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def clean_text(s: str) -> str:
    s = html.unescape(s)
    s = TAG_RE.sub("", s)
    s = WHITESPACE_RE.sub(" ", s)
    return s.strip()


def extract(raw_html: str, max_chars: int):
    # 去除非正文块
    body = DROP_TAGS.sub("", raw_html)
    body = COMMENT_RE.sub("", body)

    title = ""
    m = TITLE_RE.search(raw_html)
    if m:
        title = clean_text(m.group(1))
    h1 = H1_RE.search(raw_html)
    if h1 and not title:
        title = clean_text(h1.group(1))

    # 收集正文块，按文本量排序取头部，保留原文顺序
    blocks = []
    for m in BLOCK_RE.finditer(body):
        txt = clean_text(m.group(2))
        if len(txt) >= 20:  # 过滤掉短的噪声
            blocks.append(txt)
    # 简单去重相邻重复
    dedup = []
    prev = None
    for b in blocks:
        if b == prev:
            continue
        dedup.append(b)
        prev = b

    text = "\n\n".join(dedup)
    text = MULTINL_RE.sub("\n\n", text)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…[正文已截断]"
    return title, text


def main():
    ap = argparse.ArgumentParser(description="抓取 URL 并提取正文纯文本。")
    ap.add_argument("url", help="要抓取的 URL")
    ap.add_argument("--out", help="可选：写入文件；不给则打到 stdout")
    ap.add_argument("--max-chars", type=int, default=10000, help="正文截断字数（默认 10000）")
    ap.add_argument("--timeout", type=int, default=20, help="HTTP 超时秒数（默认 20）")
    args = ap.parse_args()

    try:
        raw = fetch(args.url, timeout=args.timeout)
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.reason}（该站点可能需要 JS 渲染或拒绝抓取，请改用 WebFetch/web_reader 工具）", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] 抓取失败：{e}（可改用 WebFetch/web_reader 工具重试）", file=sys.stderr)
        sys.exit(2)

    title, text = extract(raw, args.max_chars)
    if len(text) < 80:
        # 正文太短，很可能是 JS 渲染页
        print(f"[WARN] 提取到的正文过短（{len(text)} 字），可能是 JS 渲染页面。建议改用 WebFetch/web_reader 工具。", file=sys.stderr)

    out = f"# {title}\n来源: {args.url}\n\n{text}\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(out)
        print(f"[OK] 标题: {title}\n[OK] 正文 {len(text)} 字 -> {args.out}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
