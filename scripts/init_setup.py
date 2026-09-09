#!/usr/bin/env python3
"""
init_setup.py — note-curator 首次初始化：从 config.example.yaml 生成个人 config.yaml。

用法：
    python init_setup.py                                          # 交互模式，逐项询问
    python init_setup.py --vault "D:/Obsidian/MyVault" --author "Ray"
    python init_setup.py --vault "D:/Obsidian/MyVault" --create-vault   # vault 不存在时一并创建

行为：
    1. 读取 skill 根目录的 config.example.yaml 作为模板（保留全部注释）。
    2. 填入 vault_path 与 author，写出 config.yaml；已存在则拒绝（--force 覆盖）。
    3. 校验 vault 目录；不存在且带 --create-vault 时创建（含默认收件箱目录）。

只依赖标准库。config.yaml 含个人路径与署名，已被 .gitignore 排除，请勿提交。
"""

import argparse
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def load_example() -> str:
    ex = SKILL_ROOT / "config.example.yaml"
    if not ex.exists():
        print("[ERROR] 找不到 config.example.yaml，请在完整的 skill 目录内运行。", file=sys.stderr)
        sys.exit(1)
    return ex.read_text(encoding="utf-8")


def render_template(tpl: str, vault: str, author: str) -> str:
    """把 vault 与 author 填进模板，只动对应字段行，注释原样保留。"""
    if vault:
        tpl = re.sub(r'(?m)^vault_path:\s*".*"', 'vault_path: "' + vault + '"', tpl, count=1)
    if author:
        tpl = re.sub(r'(?m)^(\s*)author:\s*".*"', lambda m: m.group(1) + 'author: "' + author + '"', tpl, count=1)
    return tpl


def ask(prompt: str, default: str = "") -> str:
    tip = "（回车 = " + (default if default else "留空") + "）"
    try:
        val = input(prompt + tip + ": ").strip()
    except EOFError:
        print("[提示] 非交互环境无法逐项询问，请改用参数：--vault <路径> --author <署名>", file=sys.stderr)
        sys.exit(1)
    return val or default


def main():
    ap = argparse.ArgumentParser(description="note-curator 首次初始化：生成 config.yaml")
    ap.add_argument("--vault", help="知识库根目录（Obsidian vault 绝对路径）")
    ap.add_argument("--author", help="笔记作者署名（写入 frontmatter 的 author 字段）")
    ap.add_argument("--create-vault", action="store_true", help="vault 目录不存在时创建（含默认收件箱）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 config.yaml")
    args = ap.parse_args()

    cfg = SKILL_ROOT / "config.yaml"
    if cfg.exists() and not args.force:
        print("[STOP] config.yaml 已存在：" + str(cfg))
        print("       如需重新初始化，加 --force 覆盖；或直接编辑该文件。")
        sys.exit(1)

    vault, author = args.vault, args.author
    if not (vault and author):
        print("== note-curator 首次初始化 ==  回车接受括号里的默认值")
    if not vault:
        vault = ask("知识库根目录（Obsidian vault 的绝对路径）")
        if not vault:
            print("[提示] 未配置 vault 也能用：把链接丢给 skill，它会直接生成笔记内容（不归档）。")
            print("       之后想归档了，再运行本脚本或手填 config.yaml 的 vault_path。")
    if not author:
        author = ask("笔记作者署名（写入每篇笔记的 author 字段）")

    vault = vault.strip().strip('"').rstrip("/")
    author = author.strip().strip('"')

    cfg.write_text(render_template(load_example(), vault, author), encoding="utf-8")
    print("[OK] 已生成 " + str(cfg))

    if vault:
        vp = Path(vault)
        if vp.is_dir():
            print("[OK] vault 目录有效：" + str(vp))
        elif args.create_vault:
            (vp / "00 Inbox").mkdir(parents=True, exist_ok=True)
            print("[OK] 已创建知识库收件箱：" + str(vp / "00 Inbox"))
        else:
            print("[警告] vault 目录尚不存在：" + str(vp))
            print("       路径确认无误可加 --force --create-vault 重建；填错了请直接编辑 config.yaml。")
    print("下一步：把一篇文章丢给 skill 试试，例如「帮我整理这篇文章：<URL>」。")


if __name__ == "__main__":
    main()
