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
import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
import safe_yaml
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG = Path.home() / ".note-curator" / "config.yaml"

# 界面文案（按 --lang 选择；JSON 的 message/next 同步切换）
MSGS = {
    "ok": {"zh": ("配置就绪。", ""),
           "en": ("Configuration is ready.", "")},
    "missing_config": {
        "zh": ("尚未找到 note-curator 配置文件。",
               '运行 python scripts/init_setup.py --vault "<vault 路径>" --author "<署名>"'),
        "en": ("No note-curator configuration file found.",
               'Run python scripts/init_setup.py --vault "<vault path>" --author "<your name>"')},
    "config_invalid": {
        "zh": ("配置文件无法读取或解析：%s",
               "检查 config.yaml 是否存在语法错误，或重新运行 init_setup.py 生成配置。"),
        "en": ("Failed to read or parse the configuration: %s",
               "Check config.yaml for syntax errors, or re-run init_setup.py.")},
    "missing_vault_path": {
        "zh": ("配置文件里 vault_path 为空。",
               '运行 python scripts/init_setup.py --vault "<vault 路径>" --author "<署名>"'),
        "en": ("vault_path is empty in the configuration.",
               'Run python scripts/init_setup.py --vault "<vault path>" --author "<your name>"')},
    "vault_not_found": {
        "zh": ("vault 路径不存在：%s",
               "确认路径是否正确；如果要新建，运行 init_setup.py 时加 --create-vault。"),
        "en": ("Vault path does not exist: %s",
               "Check the path; add --create-vault to init_setup.py to create it.")},
    "vault_not_directory": {
        "zh": ("vault_path 指向的不是目录：%s",
               "把 vault_path 改成 Obsidian 知识库的目录。"),
        "en": ("vault_path is not a directory: %s",
               "Point vault_path at your Obsidian vault directory.")},
    "author_missing": {
        "zh": ("配置文件里 frontmatter.author 为空。",
               '在配置文件的 frontmatter.author 填写署名，或运行 init_setup.py --vault "<路径>" --author "<署名>" --force（会重置配置）。'),
        "en": ("frontmatter.author is empty in the configuration.",
               'Fill in frontmatter.author, or re-run init_setup.py --vault "<path>" --author "<name>" --force (resets the config).')},
}


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return re.sub(r"\s+#.*$", "", value).strip()


def parse_config(path):
    """用 safe_yaml 解析完整配置（B01-12/G18）；返回 (vault, author, extras)。

    不支持的 YAML 构造会抛 ValueError，由调用方按「配置无法读取」处理。
    """
    data, warnings = safe_yaml.loads(path.read_text(encoding="utf-8",
                                                    errors="ignore"))
    vault = data.get("vault_path")
    author = (data.get("frontmatter") or {}).get("author")
    extras = {}
    unknown = [k for k in data if k not in safe_yaml.SCHEMA]
    if unknown:
        extras["unknown_fields"] = unknown
    if warnings:
        extras["schema_warnings"] = warnings
    return vault, author, extras


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


def result_for(status, lang, config_path, vault_path="", author="", detail=""):
    message_tpl, next_tpl = MSGS[status][lang]
    return build_result(status, config_path, vault_path, author,
                        message=message_tpl % detail if "%s" in message_tpl else message_tpl,
                        next_step=next_tpl)


def main():
    ap = argparse.ArgumentParser(description="检查 note-curator 配置是否就绪")
    ap.add_argument("--config", help="指定 config.yaml 路径；默认按技能目录 → 用户目录查找")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh", help="提示文案语言，默认 zh")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    config_path = resolve_config(args.config)
    lang = args.lang
    extras = {}

    if not config_path.is_file():
        result = result_for("missing_config", lang, config_path)
    else:
        try:
            vault, author, extras = parse_config(config_path)
        except Exception as exc:
            result = result_for("config_invalid", lang, config_path, detail=exc)
        else:
            vault = vault or ""
            author = author or ""
            expanded = os.path.expandvars(os.path.expanduser(vault)) if vault else ""
            vault_path = Path(expanded) if expanded else None
            if vault_path is not None and not vault_path.is_absolute():
                vault_path = (config_path.parent / vault_path).resolve()

            if not vault:
                result = result_for("missing_vault_path", lang, config_path, author=author)
            elif not vault_path.exists():
                result = result_for("vault_not_found", lang, config_path,
                                    str(vault_path), author, str(vault_path))
            elif not vault_path.is_dir():
                result = result_for("vault_not_directory", lang, config_path,
                                    str(vault_path), author, str(vault_path))
            elif not author:
                result = result_for("author_missing", lang, config_path,
                                    str(vault_path), author)
            else:
                result = result_for("ok", lang, config_path, str(vault_path), author)

    if extras:
        result.update(extras)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        labels = {
            "zh": {"ok": "[OK] 配置就绪", "block": "[BLOCK]",
                   "cfg": "配置", "vault": "vault", "author": "署名", "next": "下一步"},
            "en": {"ok": "[OK] Configuration is ready", "block": "[BLOCK]",
                   "cfg": "config", "vault": "vault", "author": "author", "next": "next"},
        }[lang]
        if result["ok"]:
            print(labels["ok"])
            print("     %s: %s" % (labels["cfg"], result["config_path"]))
            print("     %s: %s" % (labels["vault"], result["vault_path"]))
            print("     %s: %s" % (labels["author"], result["author"]))
        else:
            print("%s %s" % (labels["block"], result["message"]))
            print("        %s: %s" % (labels["cfg"], result["config_path"]))
            if result["vault_path"]:
                print("        vault_path: %s" % result["vault_path"])
            if result["next"]:
                print("        %s: %s" % (labels["next"], result["next"]))

    sys.exit(0 if result["ok"] else 2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[ERROR] check_setup.py 执行失败：%s" % exc, file=sys.stderr)
        sys.exit(1)
