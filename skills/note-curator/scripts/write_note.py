#!/usr/bin/env python3
"""
write_note.py — 把笔记写入知识库（vault）。支持两种模式：

  1) new（新建）：把内容写到 <vault>/<dir>/<title>.md，文件名非法字符做安全处理。

  2) merge（合并到旧笔记）：按 patch 把变更应用到已有笔记。patch 支持两种操作：
       - append：在某小节末尾或文件末尾追加内容（**默认且最常用**）。
       - edit  ：对原文做精确字符串替换/删除（仅当原笔记确有错误时使用，放开「只增不改」）。
     合并原则（见 references/merge-rules.md）：优先追加补充；只有原内容确有错误才用 edit 改写。
     防重复：append 前会检测「要追加的片段是否已存在」，若已存在则跳过并提示（不再重复写入）。
     默认仅预览（打印 diff），确认后加 --apply 才写盘。
     三字段铁律：合并**一律不动 frontmatter**（author/created/tags，见 references/obsidian-adapter.md）；
     来源留痕以正文文末「来源补充」行呈现。

只依赖标准库。

用法:
    python write_note.py new --vault "F:/.../东东的知识星球" \\
        --dir "04 人工智能" --title "扩散模型" --file new.md
    python write_note.py merge --vault "..." \\
        --target "04 人工智能/LLM 大模型.md" --patch patch.md
    python write_note.py merge --vault "..." --target "..." --patch patch.md --apply

patch 文件格式（merge 模式输入，由 LLM 按 merge-rules.md 生成）:
    ---
    source: "https://example.com/a"          # 来源（必填，缺失填「本地草稿」）；有实际变更时追加为正文文末「来源补充」行
    ---
    ## APPEND <section>                       # 追加到某小节末尾；写 ## APPEND EOF 表示文件末尾
    （要追加的 markdown，原样接在目标小节末尾）

    ## EDIT                                   # 可选：精确替换（仅原笔记有错误时）
    <<<OLD
    原文里需要被替换的精确字符串
    >>>NEW
    替换成的内容（若留空则表示删除该段）

说明：
- 一个 patch 可含多个 ## APPEND 和 ## EDIT 块，按顺序应用。
- 没有小节标题时 ## APPEND 用 EOF；指定的小节不存在时会自动新建该小节再追加。
- 重复检测：若待 append 的片段（去空白后）已存在于旧笔记，则跳过该块并提示 SKIP-DUP。
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A(---\s*\n.*?\n---\s*\n?)(.*)$", re.DOTALL)


def safe_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', " ", title).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = "未命名笔记"
    return name[:120] + ".md"


def today():
    return datetime.date.today().isoformat()


def split_target(text: str):
    """拆成 (frontmatter块(含---), 正文)。无 frontmatter 时 frontmatter 块为空。"""
    m = FRONTMATTER_RE.match(text)
    if m:
        return m.group(1), m.group(2)
    return "", text


def source_footnote(source: str) -> str:
    """合并留痕：来源追加到正文文末，不写 frontmatter（三字段铁律见 obsidian-adapter.md 第 2 节）。"""
    return f"---\n来源补充：{source} - {today()}\n"


# ---------- patch 解析 ----------

class AppendOp:
    def __init__(self, section, fragment):
        self.section = section
        self.fragment = fragment


class EditOp:
    def __init__(self, old, new):
        self.old = old
        self.new = new


def parse_patch(patch_text: str):
    """解析 patch：提取 frontmatter.source 和若干 APPEND/EDIT 操作。"""
    source = ""
    body = patch_text
    m = FRONTMATTER_RE.match(patch_text)
    if m:
        fm = m.group(1)
        body = m.group(2)
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("source:"):
                source = line.split(":", 1)[1].strip().strip('"\'')
    ops = []
    # 按 ## APPEND / ## EDIT 切块
    parts = re.split(r"(?=^## (?:APPEND|EDIT)\b)", body, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## APPEND"):
            # 第一行是 ## APPEND <section>
            head, _, rest = part.partition("\n")
            section = head[len("## APPEND"):].strip() or "EOF"
            ops.append(AppendOp(section, rest.strip()))
        elif part.startswith("## EDIT"):
            # 用 <<<OLD ... >>>NEW 包裹
            em = re.search(r"<<<OLD\s*\n(.*?)\n>>>NEW\s*\n?(.*)$", part, re.DOTALL)
            if em:
                ops.append(EditOp(em.group(1), em.group(2).strip()))
    return source, ops


# ---------- 合并执行 ----------

def find_section_insert_point(body: str, section: str):
    """返回 (插入起始idx, 插入结束idx, 是否新建小节)。
    在指定小节末尾、下一个同级或更高级标题之前插入。"""
    if section in ("", "EOF"):
        return len(body), len(body), False
    sec_level = len(section) - len(section.lstrip("#"))
    start = body.find(section)
    if start == -1:
        # 小节不存在：在文件末尾新建
        return len(body), len(body), True
    after = body.find("\n", start) + 1
    nxt = re.search(r"^(#{1," + str(sec_level) + r"}\s+\S.*)$", body[after:], re.MULTILINE)
    cut = after + nxt.start() if nxt else len(body)
    return after, cut, False


def apply_ops(body: str, ops, verbose=False):
    """依次应用操作，返回 (新正文, 变更日志列表)。变更日志每项: (类型, 描述, 片段)。"""
    log = []
    new_body = body
    for op in ops:
        if isinstance(op, AppendOp):
            frag = op.fragment.strip()
            if not frag:
                continue
            # 重复检测：去空白后比对，避免重复追加
            if _normalized_contains(new_body, frag):
                log.append(("SKIP-DUP", f"片段已存在于笔记，跳过追加（section={op.section}）", frag))
                continue
            start, cut, create = find_section_insert_point(new_body, op.section)
            if op.section in ("", "EOF"):
                new_body = new_body.rstrip() + "\n\n" + frag + "\n"
                log.append(("APPEND", "追加到文件末尾", frag))
            elif create:
                new_body = new_body.rstrip() + f"\n\n{op.section}\n\n" + frag + "\n"
                log.append(("APPEND", f"文件末尾新建小节「{op.section}」并追加", frag))
            else:
                new_body = new_body[:cut].rstrip() + "\n\n" + frag + "\n\n" + new_body[cut:].lstrip()
                log.append(("APPEND", f"追加到小节「{op.section}」末尾", frag))
        elif isinstance(op, EditOp):
            if not op.old:
                log.append(("SKIP", "EDIT 的 OLD 为空，跳过", ""))
                continue
            # 幂等保护：NEW 已存在于笔记（多半是重复应用同一 patch）则跳过，防止反复替换
            if op.new and _normalized_contains(new_body, op.new):
                log.append(("SKIP", "EDIT 的 NEW 已存在于笔记，疑似重复应用，跳过", op.new))
                continue
            if op.old in new_body:
                count = new_body.count(op.old)
                new_body = new_body.replace(op.old, op.new)
                action = "删除" if not op.new else "替换"
                log.append(("EDIT", f"{action}原文（命中 {count} 处）", f"-{op.old}\n+{op.new}"))
            else:
                log.append(("SKIP", "EDIT 的 OLD 未在原文找到，跳过（避免误改）", op.old))
    return new_body, log


def _normalized_contains(haystack: str, needle: str) -> bool:
    """去空白/换行后判断 needle 是否已在 haystack 中，避免格式差异导致的漏判。"""
    def norm(s):
        return re.sub(r"\s+", "", s)
    return norm(needle) in norm(haystack)


def do_new(vault: Path, dir_name: str, title: str, content_file: str):
    target_dir = vault / dir_name
    target_dir.mkdir(parents=True, exist_ok=True)
    fname = safe_filename(title)
    target = target_dir / fname
    if target.exists():
        print(f"[ERROR] 目标文件已存在：{target}（若要合并请用 merge 模式）", file=sys.stderr)
        sys.exit(1)
    content = Path(content_file).read_text(encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    print(f"[OK] 新建笔记：{target}", file=sys.stderr)


def do_merge(vault: Path, target_rel: str, patch_file: str, apply: bool):
    target = vault / target_rel
    if not target.exists():
        print(f"[ERROR] 目标旧笔记不存在：{target}", file=sys.stderr)
        sys.exit(1)
    old = target.read_text(encoding="utf-8")
    patch_text = Path(patch_file).read_text(encoding="utf-8")
    source, ops = parse_patch(patch_text)

    fm_block, body = split_target(old)
    new_body, log = apply_ops(body, ops)
    has_change = any(t.startswith("APPEND") or t == "EDIT" for t, _, _ in log)

    # 三字段铁律：合并一律不动 frontmatter；来源留痕追加到正文文末
    new_text = fm_block + new_body
    if has_change and source:
        foot = source_footnote(source)
        # 同来源同日留痕只保留一行（幂等）
        if not _normalized_contains(new_text, foot):
            new_text = new_text.rstrip() + "\n\n" + foot

    # 预览 diff
    print("=" * 60, file=sys.stderr)
    print(f"合并预览  目标: {target_rel}", file=sys.stderr)
    print(f"操作数: {len(ops)}  有效变更: {sum(1 for t,_,_ in log if t.startswith('APPEND') or t=='EDIT')}", file=sys.stderr)
    print(f"来源留痕: 正文文末「来源补充」行 source={source or '(无)'}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    for t, desc, frag in log:
        marker = "+" if t.startswith("APPEND") else ("~" if t == "EDIT" else "?")
        print(f"[{t}] {marker} {desc}", file=sys.stderr)
        if frag:
            for ln in frag.splitlines():
                print(f"    {marker} {ln}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if not has_change:
        print("[无变更] 没有需要写入的内容（可能全部重复或未命中）。", file=sys.stderr)
        return
    if not apply:
        print("[未写入] 这是预览。确认无误后加 --apply 真正写入。", file=sys.stderr)
    else:
        target.write_text(new_text, encoding="utf-8")
        print(f"[OK] 已合并写入：{target}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="把笔记写入 vault（新建/合并）。")
    sub = ap.add_subparsers(dest="mode", required=True)

    p_new = sub.add_parser("new", help="新建笔记")
    p_new.add_argument("--vault", required=True)
    p_new.add_argument("--dir", required=True, help="vault 内相对目录")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--file", required=True, help="笔记内容文件路径")

    p_mg = sub.add_parser("merge", help="合并到旧笔记（追加/编辑）")
    p_mg.add_argument("--vault", required=True)
    p_mg.add_argument("--target", required=True, help="旧笔记相对 vault 的路径")
    p_mg.add_argument("--patch", required=True, help="patch 文件（含 APPEND/EDIT 操作）")
    p_mg.add_argument("--apply", action="store_true", help="确认后真正写盘（默认仅预览）")

    args = ap.parse_args()
    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"[ERROR] vault 不存在: {vault}", file=sys.stderr)
        sys.exit(1)

    if args.mode == "new":
        do_new(vault, args.dir, args.title, args.file)
    else:
        do_merge(vault, args.target, args.patch, args.apply)


if __name__ == "__main__":
    main()
