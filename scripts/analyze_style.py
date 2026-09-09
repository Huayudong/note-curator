#!/usr/bin/env python3
"""
analyze_style.py — 分析 vault 中已有笔记的排版风格，输出一份「风格摘要」供 LLM 模仿。

为什么需要它：每次新建笔记前，先看同目录（或同领域）其它笔记怎么写的——
标题层级用 # 还是 ##？列表用 - 还是 + ？是否常用引用块、表格、代码块？
frontmatter 有哪些字段？——然后照着这个风格写，新笔记才不会「画风突变」。

只依赖标准库。脚本只做统计（确定性），「怎么模仿」由 LLM 决定。

用法:
    # 分析某个目录下的笔记风格（用于该目录新建笔记时模仿）
    python analyze_style.py --vault "F:/.../东东的知识星球" --dir "04 人工智能"
    # 也可以分析单篇笔记（用于合并到它时对齐其风格）
    python analyze_style.py --vault "..." --target "04 人工智能/RAG 向量检索算法.md"
    # 可选：取该目录下最近 N 篇（默认 8）做样本，避免太老的笔记干扰
    python analyze_style.py --vault "..." --dir "04 人工智能" --sample 8

输出（stdout，markdown 文本，供 LLM 直接读取）:
    - frontmatter 字段清单与典型示例
    - 标题层级偏好（是否用 H1、主层级是 H2 还是 H3）
    - 列表标记偏好（- / + / *）
    - 强调用法（**加粗**、*斜体*、==高亮==）
    - 结构元素频率（引用块 >、表格 |、代码块 ```、wiki双链 [[ ]]）
    - 一段「风格示例片段」节选自真实笔记
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter_keys(text: str):
    """返回 frontmatter 里出现过的字段名集合。"""
    keys = []
    m = FRONTMATTER_RE.match(text)
    if not m:
        return keys
    for line in m.group(1).splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            key = line.split(":", 1)[0].strip()
            if key and not key.startswith("-"):
                keys.append(key)
    return keys


def detect_features(body: str):
    """统计一篇笔记正文的排版特征，返回 Counter。"""
    f = Counter()
    # 先剥离代码块，避免把代码里的 # 注释误判为标题/列表
    body_nocode = re.sub(r"```[\s\S]*?```", "", body)
    body_nocode = re.sub(r"`[^`\n]*`", "", body_nocode)
    # 标题层级
    for level in range(1, 7):
        cnt = len(re.findall(rf"^{'#'*level}\s+\S", body_nocode, re.MULTILINE))
        if cnt:
            f[f"H{level}"] = cnt
    # 列表标记（基于去代码块后的文本）
    f["list-dash"] = len(re.findall(r"^\s*-\s+", body_nocode, re.MULTILINE))
    f["list-plus"] = len(re.findall(r"^\s*\+\s+", body_nocode, re.MULTILINE))
    f["list-star"] = len(re.findall(r"^\*\s+", body_nocode, re.MULTILINE))
    # 有序列表
    f["list-ordered"] = len(re.findall(r"^\s*\d+\.\s+", body_nocode, re.MULTILINE))
    # 强调
    f["bold"] = len(re.findall(r"\*\*[^*]+\*\*", body))
    f["italic"] = len(re.findall(r"(?<!\*)\*[^*]+\*(?!\*)", body))
    f["highlight"] = len(re.findall(r"==[^=]+==", body))
    # 结构元素
    f["blockquote"] = len(re.findall(r"^\s*>\s?", body, re.MULTILINE))
    f["table"] = body.count("|---") + body.count("| ---")  # 表头分隔行
    f["codeblock"] = len(re.findall(r"```", body)) // 2
    f["wikilink"] = len(re.findall(r"\[\[[^\]]+\]\]", body))
    f["inline_code"] = len(re.findall(r"`[^`\n]+`", body))
    return f


def pick_sample_dir(vault: Path, dir_name: str, sample_n: int):
    """取目录下按修改时间倒序的若干 .md（跳过模板/回收站）。"""
    d = vault / dir_name
    if not d.is_dir():
        return []
    SKIP = {".trash", ".obsidian"}
    files = [p for p in d.rglob("*.md")
             if not any(part in SKIP for part in p.relative_to(vault).parts)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:sample_n]


def pick_sample_file(vault: Path, target_rel: str):
    p = vault / target_rel
    return [p] if p.exists() else []


def summarize(files):
    """汇总多篇文章的特征，输出风格摘要文本。"""
    if not files:
        return "[WARN] 未找到可分析的笔记样本。"

    fm_keys = Counter()
    feat_total = Counter()
    headings_count = 0
    sample_snippet = ""
    n = 0
    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(text.strip()) < 50:
            continue
        n += 1
        fm_keys.update(parse_frontmatter_keys(text))
        m = FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
        feat_total.update(detect_features(body))
        if not sample_snippet and body.strip():
            # 取第一段非空、长度适中的片段作为示例
            for seg in re.split(r"\n{2,}", body.strip()):
                seg = seg.strip()
                if 60 <= len(seg) <= 300 and not seg.startswith("```"):
                    sample_snippet = seg
                    break

    if n == 0:
        return "[WARN] 样本笔记内容过少，无法分析。"

    # 推断主标题层级（去掉 H1，因为 H1 常是文件标题）
    h_levels = {k: v for k, v in feat_total.items() if k.startswith("H")}
    main_h = max(h_levels, key=h_levels.get) if h_levels else "(无标题层级)"
    # 推断列表偏好
    lists = {k: feat_total.get(k, 0) for k in ("list-dash", "list-plus", "list-star", "list-ordered")}
    main_list = max(lists, key=lists.get) if any(lists.values()) else "(少用列表)"

    lines = []
    lines.append(f"# 排版风格摘要（基于 {n} 篇同类笔记统计）")
    lines.append("")
    lines.append("## frontmatter 字段（按频率）")
    if fm_keys:
        for k, c in fm_keys.most_common():
            lines.append(f"- `{k}` × {c}")
    else:
        lines.append("- （样本无统一 frontmatter）")
    lines.append("")
    lines.append("## 标题层级")
    for k in sorted(h_levels):
        lines.append(f"- `{k}` × {h_levels[k]}")
    lines.append(f"- **主层级推断**：{main_h}（新笔记正文标题尽量对齐此层级）")
    lines.append("")
    lines.append("## 列表与强调")
    lines.append(f"- 列表主标记：`{main_list}`（dash=-，plus=+，star=*，ordered=数字.）")
    lines.append(f"- 加粗 `**...**`：{feat_total.get('bold', 0)}  次")
    lines.append(f"- 斜体 `*...*`：{feat_total.get('italic', 0)} 次")
    lines.append(f"- 高亮 `==...==`：{feat_total.get('highlight', 0)} 次")
    lines.append("")
    lines.append("## 结构元素使用频率")
    for k, label in [("blockquote", "引用块 >"), ("table", "表格"), ("codeblock", "代码块 ```"),
                     ("wikilink", "双链 [[ ]]"), ("inline_code", "行内代码 ` `")]:
        lines.append(f"- {label}：{feat_total.get(k, 0)} 次")
    lines.append("")
    lines.append("## 风格示例片段（节选自真实笔记，模仿其排版）")
    lines.append("")
    lines.append("```markdown")
    lines.append(sample_snippet if sample_snippet else "(未取到合适片段)")
    lines.append("```")
    lines.append("")
    lines.append("## 模仿要点")
    lines.append("- 新笔记的 frontmatter 至少包含上面高频字段；标题层级用推断的主层级起头；列表、强调、结构元素的使用密度向样本对齐。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="分析 vault 笔记排版风格，供新笔记模仿。")
    ap.add_argument("--vault", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="分析该目录下笔记的风格")
    g.add_argument("--target", help="分析单篇笔记的风格（合并时对齐它）")
    ap.add_argument("--sample", type=int, default=8, help="目录模式取最近 N 篇（默认 8）")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"[ERROR] vault 不存在: {vault}", file=sys.stderr)
        sys.exit(1)

    if args.dir:
        files = pick_sample_dir(vault, args.dir, args.sample)
    else:
        files = pick_sample_file(vault, args.target)

    print(summarize(files))


if __name__ == "__main__":
    main()
