#!/usr/bin/env python3
"""
check_setup.py — 检查 note-curator 是否已经完成配置。

每次整理任务开始前运行；只读，不修改任何文件。
支持 --json，方便 Agent 解析。

退出码：
    0 = 配置就绪
    2 = 需要用户先完成配置
    1 = 脚本异常
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG = Path.home() / ".note-curator" / "config.yaml"


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return re.sub(r"\s+#.*$", "", value).strip()


def parse_config(path):
    """只解析 vault_path 和 frontmatter.author，避免引入 YAML 依赖。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    vault = None
    author = None
    in_frontmatter = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^frontmatter:\s*(?:#.*)?$", line):
            in_frontmatter = True
            continue
        if in_frontmatter and line and not line[0].isspace():
            in_frontmatter = False
        match = re.match(r"^vault_path:\s*(.*)$", line)
        if match:
            vault = unquote(match.group(1))
            continue
        if in_frontmatter:
            match = re.match(r"^\s+author:\s*(.*)$", line)
            if match:
                author = unquote(match.group(1))
    return vault, author


def resolve_config(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    candidates = [SKILL_ROOT / "config.yaml", USER_CONFIG]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return USER_CONFIG


def build_result(status, config_path, vault_path="", author="", message="", next_step=""):
    return {
        "ok": status == "ok",
        "status": status,
        "config_path": str(config_path),
        "vault_path": vault_path,
        "author": author,
        "message": message,
        "next": next_step,
    }


def main():
    ap = argparse.ArgumentParser(description="检查 note-curator 配置是否就绪")
    ap.add_argument("--config", help="指定 config.yaml 路径；默认按技能目录 → 用户目录查找")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    config_path = resolve_config(args.config)

    if not config_path.is_file():
        result = build_result(
            "missing_config", config_path,
            message="尚未找到 note-curator 配置文件。",
            next_step='运行 python scripts/init_setup.py --vault "<vault 路径>" --author "<署名>"',
        )
    else:
        try:
            vault, author = parse_config(config_path)
        except Exception as exc:
            result = build_result(
                "config_invalid", config_path,
                message="配置文件无法读取或解析：%s" % exc,
                next_step="检查 config.yaml 是否存在语法错误，或重新运行 init_setup.py 生成配置。",
            )
        else:
            vault = vault or ""
            author = author or ""
            expanded = os.path.expandvars(os.path.expanduser(vault)) if vault else ""
            vault_path = Path(expanded) if expanded else None
            if vault_path is not None and not vault_path.is_absolute():
                vault_path = (config_path.parent / vault_path).resolve()

            if not vault:
                result = build_result(
                    "missing_vault_path", config_path, author=author,
                    message="配置文件里 vault_path 为空。",
                    next_step='运行 python scripts/init_setup.py --vault "<vault 路径>" --author "<署名>"',
                )
            elif not vault_path.exists():
                result = build_result(
                    "vault_not_found", config_path, str(vault_path), author,
                    message="vault 路径不存在：%s" % vault_path,
                    next_step="确认路径是否正确；如果要新建，运行 init_setup.py 时加 --create-vault。",
                )
            elif not vault_path.is_dir():
                result = build_result(
                    "vault_not_directory", config_path, str(vault_path), author,
                    message="vault_path 指向的不是目录：%s" % vault_path,
                    next_step="把 vault_path 改成 Obsidian 知识库的目录。",
                )
            elif not author:
                result = build_result(
                    "author_missing", config_path, str(vault_path), author,
                    message="配置文件里 frontmatter.author 为空。",
                    next_step='在配置文件的 frontmatter.author 填写署名，或运行 init_setup.py --vault "<路径>" --author "<署名>" --force（会重置配置）。',
                )
            else:
                result = build_result(
                    "ok", config_path, str(vault_path), author,
                    message="配置就绪。",
                )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print("[OK] 配置就绪")
            print("     配置：%s" % result["config_path"])
            print("     vault：%s" % result["vault_path"])
            print("     署名：%s" % result["author"])
        else:
            print("[BLOCK] %s" % result["message"])
            print("        配置：%s" % result["config_path"])
            if result["vault_path"]:
                print("        vault_path：%s" % result["vault_path"])
            if result["next"]:
                print("        下一步：%s" % result["next"])

    sys.exit(0 if result["ok"] else 2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[ERROR] check_setup.py 执行失败：%s" % exc, file=sys.stderr)
        sys.exit(1)
