#!/usr/bin/env python3
"""
index_vault.py — B07 全文分块索引（可增量更新）。

与 scan_vault.py 的分工：scan_vault 输出「标题+开头摘要」给查重初筛；
本脚本把每篇笔记按标题小节切块，保留全文，供检索与证据定位使用。

索引结构（schema 3）：
    {
      "schema": 3, "vault": "...", "generated_at": "...",
      "files": {
        "编程/缓存失效.md": {
          "hash": "sha256", "mtime": 169...,
          "title": "缓存失效", "language": "zh", "aliases": [...],
          "headings": ["## 雪崩", ...],
          "chunks": [{"id": "编程/缓存失效.md#c2", "heading": "## 雪崩",
                       "text": "...", "pos_ratio": 0.62}]
        }
      }
    }

增量模式（--incremental）：按内容哈希比对旧索引——未变化的文件直接复用，
变化的重建，已删除的移除；索引是可重建缓存，不是笔记真源（B07-09）。

用法：
    python index_vault.py --vault V --out index.json
    python index_vault.py --vault V --out index.json --incremental
    python index_vault.py --vault V --out index.json --incremental --json
退出码：0 成功；1 参数错误。
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from langdetect import detect_language_detail
from scan_vault import parse_frontmatter, strip_markup

# 跳过的目录（与 scan_vault 口径一致，另加常见的非笔记目录）
SKIP_DIRS = {".trash", ".obsidian", ".git", "node_modules", "__pycache__"}

SCHEMA = 3
DEFAULT_CHUNK = 600
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def file_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_aliases(fm):
    """frontmatter aliases：行内列表或单值。"""
    aliases = fm.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in aliases.strip("[]").split(",") if a.strip()]
    if not isinstance(aliases, list):
        return []
    return [str(a).strip("\"'") for a in aliases if str(a).strip()]


def extract_title(fm, body, stem):
    title = str(fm.get("title") or "").strip()
    if title:
        return title
    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else stem


def make_chunks(body, rel, max_chunk):
    """按标题切小节；过长小节再按段落对半切。返回 chunk 列表与标题清单。"""
    headings = [m.group(0).strip() for m in HEADING_RE.finditer(body)]
    matches = list(HEADING_RE.finditer(body))
    sections = []
    if matches:
        if matches[0].start() > 0:
            sections.append(("", body[:matches[0].start()]))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            sections.append((m.group(0).strip(), body[m.start():end]))
    else:
        sections = [("", body)]

    chunks = []
    total = max(len(body), 1)
    for heading, text in sections:
        text = text.strip()
        if not text:
            continue
        pieces = [text]
        if len(text) > max_chunk * 2:
            paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
            pieces, buf = [], ""
            for para in paras:
                if buf and len(buf) + len(para) > max_chunk:
                    pieces.append(buf)
                    buf = para
                else:
                    buf = (buf + "\n\n" + para).strip()
            if buf:
                pieces.append(buf)
        start_hint = body.find(text[:40])
        pos = (start_hint / total) if start_hint >= 0 else 0.0
        for j, piece in enumerate(pieces):
            chunks.append({
                "id": "%s#c%d" % (rel, len(chunks) + 1),
                "heading": heading if len(pieces) == 1 else
                           ("%s（%d/%d）" % (heading, j + 1, len(pieces))),
                "text": piece,
                "pos_ratio": round(min(max(pos, 0.0), 1.0), 3),
            })
    return chunks, headings


def build_entry(path, rel, text, max_chunk):
    fm, body = parse_frontmatter(text)
    body_clean = strip_markup(body)
    detail = detect_language_detail(body_clean)
    chunks, headings = make_chunks(body, rel, max_chunk)
    return {
        "hash": file_hash(text),
        "mtime": path.stat().st_mtime,
        "title": extract_title(fm, body, path.stem),
        "language": detail["primary"],
        "aliases": extract_aliases(fm),
        "headings": headings,
        "chunks": chunks,
    }


def iter_notes(vault):
    for md in sorted(vault.rglob("*.md")):
        rel_parts = md.relative_to(vault).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if any(part.lower().startswith(("00 template", "00 attachment"))
               for part in rel_parts):
            continue
        yield md


def main():
    ap = argparse.ArgumentParser(description="全文分块索引（支持增量）")
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True, help="索引 JSON 输出路径")
    ap.add_argument("--incremental", action="store_true",
                    help="复用旧索引：哈希未变的文件不重建")
    ap.add_argument("--max-chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--json", action="store_true", help="统计以 JSON 输出到 stdout")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print("[ERROR] vault 不存在: %s" % vault, file=sys.stderr)
        sys.exit(1)
    out = Path(args.out)

    old_files = {}
    if args.incremental and out.is_file():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            if old.get("schema") == SCHEMA:
                old_files = old.get("files", {})
        except (OSError, ValueError):
            old_files = {}

    files = {}
    added = updated = unchanged = removed = 0
    for md in iter_notes(vault):
        rel = md.relative_to(vault).as_posix()
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        digest = file_hash(text)
        prior = old_files.get(rel)
        if prior and prior.get("hash") == digest:
            files[rel] = prior
            unchanged += 1
            continue
        files[rel] = build_entry(md, rel, text, args.max_chunk)
        if prior:
            updated += 1
        else:
            added += 1
    removed = len([rel for rel in old_files if rel not in files])

    index = {
        "schema": SCHEMA,
        "vault": str(vault),
        "generated_at": nc_core.now_iso(),
        "files": files,
    }
    nc_core.atomic_write_text(out, json.dumps(index, ensure_ascii=False, indent=2))
    stats = {"files": len(files), "added": added, "updated": updated,
             "unchanged": unchanged, "removed": removed}
    if args.json:
        print(json.dumps({"ok": True, **stats}, ensure_ascii=False))
    else:
        print("[OK] 索引完成：%d 篇（新增 %d，更新 %d，未变 %d，移除 %d）-> %s"
              % (stats["files"], added, updated, unchanged, removed, out),
              file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
