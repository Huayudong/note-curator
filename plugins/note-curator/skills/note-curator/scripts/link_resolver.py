#!/usr/bin/env python3
"""
link_resolver.py — B07 双链解析与验证（LinkResolver）。

Obsidian 链接在写入前先验证（B07-06/07/08）：
  - 解析顺序：显式相对路径（含子路径后缀匹配）→ 文件名（同名给候选）→
    frontmatter aliases；不以 H1 文本当作文件名。
  - 锚点验证：#标题 在目标文件的标题清单里；#^blockid 在目标的块 ID 里。
  - 状态：resolved / ambiguous（给候选清单）/ broken（含原因）。
  - 计划新建的目标不在此验证（先落地、再引用，见 B04 拆分闭环）。

用法：
    python link_resolver.py --vault V --file 笔记.md [--json] [--strict]
    python link_resolver.py --vault V --check-draft 草稿.md [--json] [--strict]
    python link_resolver.py --vault V --resolve "[[编程/笔记#雪崩]]" [--json]

退出码：0 全部可解析；1 有 ambiguous/broken（--strict 或默认检查模式）。
"""

import argparse
import json
import re
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from scan_vault import parse_frontmatter

# 与 index_vault 口径一致
SKIP_DIRS = {".trash", ".obsidian", ".git", "node_modules", "__pycache__"}

WIKILINK_RE = re.compile(r"(?<!!)!\[\[[^\]]*\]\]|\[\[([^\]]+)\]\]")
BLOCK_ID_RE = re.compile(r"\^([A-Za-z0-9][A-Za-z0-9-]*)\s*$")


def norm_key(text):
    return text.strip().casefold()


def build_link_table(vault):
    """扫描 vault：路径、文件名、别名、标题、块 ID。"""
    table = {"by_path": {}, "by_stem": {}, "by_alias": {}}
    for md in sorted(vault.rglob("*.md")):
        rel_parts = md.relative_to(vault).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        rel = md.relative_to(vault).as_posix()
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        aliases = fm.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.strip("[]").split(",") if a.strip()]
        headings = set()
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", body, re.MULTILINE):
            headings.add(norm_key(m.group(1)))
        block_ids = set()
        for line in body.splitlines():
            m = BLOCK_ID_RE.search(line)
            if m:
                block_ids.add(m.group(1))
        entry = {"path": rel, "aliases": [str(a).strip("\"'") for a in aliases
                                           if str(a).strip()],
                 "headings": sorted(headings), "block_ids": sorted(block_ids)}
        table["by_path"][rel.casefold()] = entry
        table["by_stem"].setdefault(norm_key(md.stem), []).append(entry)
        for alias in entry["aliases"]:
            table["by_alias"].setdefault(norm_key(alias), []).append(entry)
    return table


def parse_wikilink(raw):
    """[[target#anchor|display]] → (target, anchor, display, is_block)。"""
    inner = raw[2:-2]
    display = ""
    if "|" in inner:
        inner, display = inner.split("|", 1)
    anchor = ""
    is_block = False
    if "#" in inner:
        inner, anchor = inner.split("#", 1)
        is_block = anchor.startswith("^")
        anchor = anchor.lstrip("^")
    return inner.strip(), anchor.strip(), display.strip(), is_block


def resolve_target(table, target, source_rel):
    """路径部分 → (status, entry|None, candidates)。"""
    if not target:
        # [[#锚点]]：本文件内锚点
        src = table["by_path"].get(source_rel.casefold())
        return ("resolved", src, []) if src else ("broken", None, [])
    t = target.strip()
    t_md = t if t.lower().endswith(".md") else t + ".md"
    key = t_md.casefold()
    exact = table["by_path"].get(key)
    if exact:
        return "resolved", exact, []
    suffix = [e for k, e in table["by_path"].items() if k.endswith("/" + key)]
    if len(suffix) == 1:
        return "resolved", suffix[0], []
    if len(suffix) > 1:
        return "ambiguous", None, [e["path"] for e in suffix]
    stem_hits = table["by_stem"].get(norm_key(Path(t).name), [])
    if len(stem_hits) == 1:
        return "resolved", stem_hits[0], []
    if len(stem_hits) > 1:
        return "ambiguous", None, sorted(e["path"] for e in stem_hits)
    alias_hits = table["by_alias"].get(norm_key(t), [])
    if len(alias_hits) == 1:
        return "resolved", alias_hits[0], []
    if len(alias_hits) > 1:
        return "ambiguous", None, sorted(e["path"] for e in alias_hits)
    return "broken", None, []


def check_link(table, raw, source_rel):
    """单条链接 → 报告 dict。"""
    target, anchor, display, is_block = parse_wikilink(raw)
    status, entry, candidates = resolve_target(table, target, source_rel)
    report = {"raw": raw, "target": target, "anchor": anchor,
              "display": display, "status": status,
              "resolved_path": entry["path"] if entry else "",
              "candidates": candidates}
    if status == "resolved" and anchor:
        if is_block:
            if anchor not in entry["block_ids"]:
                report["status"] = "broken"
                report["reason"] = "块 ID 不存在：%s" % anchor
        elif norm_key(anchor) not in entry["headings"]:
            report["status"] = "broken"
            report["reason"] = "标题锚点不存在：%s" % anchor
    if status == "ambiguous":
        report["reason"] = "同名目标有多个，需消歧"
    if status == "broken" and "reason" not in report:
        report["reason"] = "目标不存在：%s" % (target or "(本文件锚点)")
    return report


def collect_links(text):
    """提取正文中的非嵌入 wiki 链接。"""
    links = []
    for m in WIKILINK_RE.finditer(text):
        if m.group(0).startswith("[["):
            links.append(m.group(0))
    return links


def check_document(table, text, source_rel):
    """返回 (reports, unresolved_count)。"""
    reports = []
    unresolved = 0
    for raw in collect_links(text):
        report = check_link(table, raw, source_rel)
        if report["status"] != "resolved":
            unresolved += 1
        reports.append(report)
    return reports, unresolved


def main():
    ap = argparse.ArgumentParser(description="双链解析与验证")
    ap.add_argument("--vault", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="验证该笔记内的全部链接")
    src.add_argument("--check-draft", help="验证草稿中的链接（目标须已存在）")
    src.add_argument("--resolve", help="解析单条链接")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="宽容模式：只报告，不因 ambiguous/broken 退出 1")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print("[ERROR] vault 不存在: %s" % vault, file=sys.stderr)
        sys.exit(1)
    table = build_link_table(vault)

    if args.resolve:
        source_rel = ""
        report = check_link(table, args.resolve if args.resolve.startswith("[[")
                            else "[[%s]]" % args.resolve, source_rel)
        reports, unresolved = [report], 0 if report["status"] == "resolved" else 1
    else:
        doc = Path(args.file or args.check_draft)
        if not doc.is_file():
            print("[ERROR] 文件不存在: %s" % doc, file=sys.stderr)
            sys.exit(1)
        text = doc.read_text(encoding="utf-8", errors="ignore")
        source_rel = ""
        if args.file:
            try:
                source_rel = doc.resolve().relative_to(vault).as_posix()
            except ValueError:
                source_rel = ""
        reports, unresolved = check_document(table, text, source_rel)

    payload = {"total": len(reports), "unresolved": unresolved,
               "links": reports}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            mark = {"resolved": "[OK]", "ambiguous": "[歧义]",
                    "broken": "[断链]"}.get(r["status"], r["status"])
            line = "%s %s -> %s" % (mark, r["raw"], r["resolved_path"] or "?")
            if r["status"] == "ambiguous":
                line += "（候选：%s）" % "、".join(r["candidates"])
            elif r["status"] == "broken":
                line += "（%s）" % r.get("reason", "")
            print(line)
        if not reports:
            print("（文档中没有 wiki 链接）")
    strict = not args.report
    sys.exit(0 if unresolved == 0 or not strict else 1)


if __name__ == "__main__":
    main()
