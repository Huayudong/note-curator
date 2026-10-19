#!/usr/bin/env python3
"""
init_setup.py — note-curator 首次初始化：从 config.example.yaml 生成个人 config.yaml。

用法：
    python init_setup.py                                          # 交互模式，逐项询问
    python init_setup.py --vault "D:/Obsidian/MyVault" --author "Ray"
    python init_setup.py --vault "D:/Obsidian/MyVault" --create-vault   # vault 不存在时一并创建

行为：
    1. 读取 skill 根目录的 config.example.yaml 作为模板（保留全部注释）。
    2. 填入 vault_path 与 author，写出个人配置；已存在则拒绝（--force 覆盖）。
       默认写到 ~/.note-curator/config.yaml；若技能目录里已有旧的 config.yaml，
       则沿用旧文件；也可以用 --config <路径> 显式指定。
    3. 校验 vault 目录；不存在且带 --create-vault 时创建（含默认收件箱目录）。

只依赖标准库。config.yaml 含个人路径与署名，已被 .gitignore 排除，请勿提交。
"""

import argparse
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG = Path.home() / ".note-curator" / "config.yaml"


def resolve_config_path(explicit=None) -> Path:
    """显式路径优先；否则沿用技能目录里的旧配置；最后落到用户级配置。"""
    if explicit:
        return Path(explicit).expanduser()
    legacy = SKILL_ROOT / "config.yaml"
    if legacy.exists():
        return legacy
    return USER_CONFIG


def load_example() -> str:
    ex = SKILL_ROOT / "config.example.yaml"
    if not ex.exists():
        print("[ERROR] 找不到 config.example.yaml，请在完整的 skill 目录内运行。", file=sys.stderr)
        sys.exit(1)
    return ex.read_text(encoding="utf-8")


def render_template(tpl: str, vault: str, author: str) -> str:
    """把 vault 与 author 填进模板，只动对应字段行，注释原样保留。"""
    if vault:
        value = vault.replace("\\", "/").replace('"', '\\"')
        tpl = re.sub(r'(?m)^vault_path:\s*".*"', lambda m: 'vault_path: "' + value + '"', tpl, count=1)
    if author:
        value = author.replace("\\", "\\\\").replace('"', '\\"')
        tpl = re.sub(r'(?m)^(\s*)author:\s*".*"', lambda m: m.group(1) + 'author: "' + value + '"', tpl, count=1)
    return tpl


def ask(prompt: str, default: str = "", lang: str = "zh") -> str:
    if lang == "en":
        tip = " (Enter = %s)" % (default if default else "leave empty")
    else:
        tip = "（回车 = %s）" % (default if default else "留空")
    try:
        val = input(prompt + tip + ": ").strip()
    except EOFError:
        hint = ("Non-interactive session; pass --vault <path> --author <name> instead"
                if lang == "en" else
                "非交互环境无法逐项询问，请改用参数：--vault <路径> --author <署名>")
        print("[提示] " + hint, file=sys.stderr)
        sys.exit(1)
    return val or default


# 界面文案：--lang 选择（默认中文）
M = {
    "stop_exists": {"zh": "[STOP] config.yaml 已存在：%s\n       如需重新初始化，加 --force 覆盖；或直接编辑该文件。",
                    "en": "[STOP] config.yaml already exists: %s\n       Add --force to overwrite, or edit the file directly."},
    "header": {"zh": "== note-curator 首次初始化 ==  回车接受括号里的默认值",
               "en": "== note-curator first-time setup ==  press Enter to accept defaults"},
    "ask_vault": {"zh": "知识库根目录（Obsidian vault 的绝对路径）",
                  "en": "Vault root directory (absolute path to your Obsidian vault)"},
    "no_vault_hint": {"zh": "[提示] 未配置 vault 也能用：把链接丢给 skill，它会直接生成笔记内容（不归档）。\n       之后想归档了，再运行本脚本或手填 config.yaml 的 vault_path。",
                      "en": "[Hint] You can use the skill without a vault: it will generate note content without archiving.\n       Run this script again (or fill vault_path) when you want archiving."},
    "ask_author": {"zh": "笔记作者署名（写入每篇笔记的 author 字段）",
                   "en": "Author name (written into each note's author field)"},
    "generated": {"zh": "[OK] 已生成 ", "en": "[OK] Generated "},
    "vault_ok": {"zh": "[OK] vault 目录有效：", "en": "[OK] Vault directory is valid: "},
    "inbox_created": {"zh": "[OK] 已创建知识库收件箱：", "en": "[OK] Created vault inbox: "},
    "vault_missing": {"zh": "[警告] vault 目录尚不存在：%s\n       路径确认无误可加 --force --create-vault 重建；填错了请直接编辑 config.yaml。",
                      "en": "[WARN] Vault directory does not exist yet: %s\n       If the path is right, rerun with --force --create-vault; otherwise edit config.yaml."},
    "next": {"zh": "下一步：把一篇文章丢给 skill 试试，例如「帮我整理这篇文章：<URL>」。",
             "en": "Next: hand the skill an article, e.g. \"organize this article into my notes: <URL>\"."},
}


def main():
    ap = argparse.ArgumentParser(description="note-curator 首次初始化：生成 config.yaml")
    ap.add_argument("--vault", help="知识库根目录（Obsidian vault 绝对路径）")
    ap.add_argument("--author", help="笔记作者署名（写入 frontmatter 的 author 字段）")
    ap.add_argument("--create-vault", action="store_true", help="vault 目录不存在时创建（含默认收件箱）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的配置文件")
    ap.add_argument("--config", help="配置文件路径（默认 ~/.note-curator/config.yaml；技能目录已有 config.yaml 时沿用）")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh", help="提示文案语言，默认 zh")
    args = ap.parse_args()
    t = lambda key: M[key][args.lang]  # noqa: E731

    cfg = resolve_config_path(args.config)
    if cfg.exists() and not args.force:
        print(t("stop_exists") % cfg)
        sys.exit(1)

    vault, author = args.vault, args.author
    if not (vault and author):
        print(t("header"))
    if not vault:
        vault = ask(t("ask_vault"), lang=args.lang)
        if not vault:
            print(t("no_vault_hint"))
    if not author:
        author = ask(t("ask_author"), lang=args.lang)

    vault = vault.strip().strip('"').replace("\\", "/").rstrip("/")
    author = author.strip().strip('"')

    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(render_template(load_example(), vault, author), encoding="utf-8")
    print(t("generated") + str(cfg))

    if vault:
        vp = Path(vault)
        if vp.is_dir():
            print(t("vault_ok") + str(vp))
        elif args.create_vault:
            (vp / "00 Inbox").mkdir(parents=True, exist_ok=True)
            print(t("inbox_created") + str(vp / "00 Inbox"))
        else:
            print(t("vault_missing") % vp)
    print(t("next"))


if __name__ == "__main__":
    main()
