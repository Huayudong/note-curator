#!/usr/bin/env python3
"""
scan_vault.py — 扫描 Obsidian vault，输出全部笔记的索引清单。

用途：查重（find_duplicates.py）与建双链都需要「已有笔记的标题/路径/正文」。
本脚本把 vault 扫描结果以 JSON 形式输出到 stdout，供 LLM 或其他脚本消费。

只依赖标准库，无需安装第三方包。

用法:
    python scan_vault.py --vault "F:/file/Obsidian/东东的知识星球"
    python scan_vault.py --vault "..." --out index.json        # 写文件
    python scan_vault.py --vault "..." --max-body 600          # 正文摘要截断字数（默认 800）

输出 JSON 结构（数组，每个元素一篇笔记）:
    [
      {
        "title": "LLM 大模型",
        "path": "04 人工智能/LLM 大模型.md",
        "abspath": "F:/file/Obsidian/东东的知识星球/04 人工智能/LLM 大模型.md",
        "frontmatter": {"author": "...", "tags": [...]},
        "headings": ["## 什么是大模型", "### 参数量"],
        "body": "正文前 N 字摘要..."   # 去掉 frontmatter 后的正文，截断到 max-body
      },
      ...
    ]
"""

import argparse
import json
import re
import sys
import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from pathlib import Path

from langdetect import detect_language


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def parse_frontmatter(text: str):
    """极简 YAML frontmatter 解析：只取常见的标量与 tags 列表。
    返回 (frontmatter_dict, body_without_frontmatter)。"""
    fm = {}
    m = FRONTMATTER_RE.match(text)
    body = text
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if key == "tags":
                    # tags 可能是 [a, b] 或多行列表；这里尽量兼容单行
                    if val.startswith("["):
                        val = val.strip("[]")
                        fm[key] = [t.strip().strip('"\'') for t in val.split(",") if t.strip()]
                    elif not val:
                        fm[key] = []
                    else:
                        fm[key] = [t.strip() for t in val.split() if t.strip()]
                else:
                    fm[key] = val.strip('"\'')
    return fm, body


def extract_headings(body: str):
    return [m.group(0) for m in HEADING_RE.finditer(body)]


def strip_markup(body: str) -> str:
    """轻度清洗：去掉 wiki 链接的方括号保留文字、去掉图片、折叠多余空行。"""
    # 保留双链显示文字：[[目标|显示]] -> 显示；[[目标]] -> 目标
    body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)
    # 去图片 ![](xxx) 和 ![[xxx]]
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"!\[\[[^\]]*\]\]", "", body)
    # 去代码块（避免代码污染摘要）
    body = re.sub(r"```[\s\S]*?```", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def scan_vault(vault: Path, max_body: int = 800):
    results = []
    # 应跳过的目录名（Obsidian 回收站/配置/模板/附件）
    SKIP_DIRS = {".trash", ".obsidian"}
    for md in vault.rglob("*.md"):
        rel = md.relative_to(vault)
        parts = rel.parts
        # 跳过回收站、配置目录、模板目录、附件目录
        if any(p in SKIP_DIRS for p in parts):
            continue
        if any(p.lower().startswith("00 template") or p.lower().startswith("00 attachment") for p in parts):
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        fm, body = parse_frontmatter(text)
        body_clean = strip_markup(body)
        # 跳过几乎无正文的废笔记（如仅含标题的占位文件），避免污染查重
        if len(body_clean) < 30:
            continue
        # 标题优先用 frontmatter 的 title，其次第一级标题，最后文件名
        title = fm.get("title") or ""
        if not title:
            h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            title = h1.group(1).strip() if h1 else md.stem
        results.append({
            "title": title,
            "path": str(rel).replace("\\", "/"),
            "abspath": str(md).replace("\\", "/"),
            "language": detect_language(body_clean),
            "frontmatter": fm,
            "headings": extract_headings(body),
            "body": body_clean[:max_body],
        })
    return results


def main():
    ap = argparse.ArgumentParser(description="扫描 Obsidian vault，输出笔记索引 JSON。")
    ap.add_argument("--vault", required=True, help="vault 根目录绝对路径")
    ap.add_argument("--out", help="可选：把 JSON 写入该文件；不给则打到 stdout")
    ap.add_argument("--max-body", type=int, default=800, help="正文摘要截断字数（默认 800）")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"[ERROR] vault 路径不存在或不是目录: {vault}", file=sys.stderr)
        sys.exit(1)

    index = scan_vault(vault, max_body=args.max_body)
    data = json.dumps(index, ensure_ascii=False, indent=2)

    if args.out:
        Path(args.out).write_text(data, encoding="utf-8")
        print(f"[OK] 扫描完成：{len(index)} 篇笔记 -> {args.out}", file=sys.stderr)
    else:
        print(data)


if __name__ == "__main__":
    main()
