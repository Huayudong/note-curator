#!/usr/bin/env python3
"""
resource_pack.py — 语言包加载与校验（B03-01）。

语言包放在 <skill>/language-packs/<lang>/ 下：
    pack.json        表达规则与词表（schema_version=1）
    terminology.json 术语首现格式（可选）
    examples.jsonl   带出处的示例句（可选；B03-09 要求记录作者/来源/许可）

load_pack(lang) 返回 (pack | None, warnings)：
  - 缺失或损坏返回 None + 警告，调用方回退到代码内置词表（zero-dep 兜底）；
  - schema 校验不过按损坏处理，绝不带着坏数据继续。

CLI：
    python resource_pack.py --lang zh [--json] [--pack-root DIR]
退出码：0 校验通过；2 校验失败；1 参数错误。
"""

import argparse
import json
import os
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

SKILL_ROOT = Path(__file__).resolve().parent.parent
PACK_ROOT = SKILL_ROOT / "language-packs"
PACK_DIR_NAMES = {"zh": "zh-CN", "en": "en"}

TERMINOLOGY_ITEM_KEYS = {"term", "abbr", "first_mention"}
EXAMPLE_ITEM_KEYS = {"id", "text", "register", "author", "source", "license"}


def pack_root():
    env = os.environ.get("NOTE_CURATOR_PACK_ROOT")
    return Path(env).expanduser() if env else PACK_ROOT


def pack_path(lang, name="pack.json", root=None):
    return (Path(root) if root else pack_root()) / PACK_DIR_NAMES[lang] / name


def _validate_terminology(pack_dir, warnings):
    path = pack_dir / "terminology.json"
    if not path.is_file():
        warnings.append("terminology.json 缺失（可选）")
        return
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        warnings.append("terminology.json 无法解析: %s" % exc)
        return
    for i, item in enumerate(items):
        if not EXAMPLE_ITEM_KEYS & TERMINOLOGY_ITEM_KEYS <= set(item):
            if not {"term", "first_mention"} <= set(item):
                warnings.append("terminology.json 第 %d 条缺 term/first_mention" % (i + 1))


def _validate_examples(pack_dir, warnings):
    path = pack_dir / "examples.jsonl"
    if not path.is_file():
        warnings.append("examples.jsonl 缺失（可选）")
        return
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            warnings.append("examples.jsonl 第 %d 行无法解析: %s" % (lineno, exc))
            continue
        missing = EXAMPLE_ITEM_KEYS - set(item)
        if missing:
            warnings.append("examples.jsonl 第 %d 行缺字段: %s"
                            % (lineno, ",".join(sorted(missing))))
        if not item.get("license") or not item.get("author"):
            warnings.append("examples.jsonl 第 %d 行缺 author/license（B03-09 出处要求）"
                            % lineno)


def validate_pack(pack, lang):
    """返回错误列表；空列表 = 可激活。"""
    errors = []
    if pack.get("schema_version") != 1:
        errors.append("schema_version 必须为 1，实际 %r" % pack.get("schema_version"))
    language = str(pack.get("language", ""))
    if not language.startswith(lang):
        errors.append("language %r 与请求语言 %r 不匹配" % (language, lang))
    terms = pack.get("terms")
    if not isinstance(terms, dict) or not terms:
        errors.append("terms 缺失或为空")
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("rules 缺失或为空")
    else:
        seen_ids = set()
        for i, rule in enumerate(rules):
            rid = rule.get("id")
            if not rid:
                errors.append("rules[%d] 缺 id" % i)
            elif rid in seen_ids:
                errors.append("rules[%d] id 重复: %s" % (i, rid))
            seen_ids.add(rid)
            if not rule.get("guidance"):
                errors.append("rules[%s] 缺 guidance" % rid)
            if rule.get("kind") not in ("deterministic", "contextual", "guidance", None):
                errors.append("rules[%s] kind 非法: %r" % (rid, rule.get("kind")))
    if not pack.get("pack_version"):
        errors.append("pack_version 缺失")
    return errors


def load_pack(lang, root=None):
    """返回 (pack | None, warnings)。损坏/缺失回退 None，绝不带坏数据继续。"""
    warnings = []
    path = pack_path(lang, root=root)
    if not path.is_file():
        return None, ["语言包缺失: %s" % path]
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, ["语言包无法解析 %s: %s" % (path, exc)]
    errors = validate_pack(pack, lang)
    if errors:
        return None, ["语言包校验未通过 %s：%s" % (path, "；".join(errors))]
    _validate_terminology(path.parent, warnings)
    _validate_examples(path.parent, warnings)
    return pack, warnings


def main():
    ap = argparse.ArgumentParser(description="语言包校验与加载")
    ap.add_argument("--lang", choices=sorted(PACK_DIR_NAMES), required=True)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--pack-root", help="语言包根目录（默认 skill 内 language-packs；"
                                        "可用 NOTE_CURATOR_PACK_ROOT 覆盖）")
    args = ap.parse_args()

    pack, warnings = load_pack(args.lang, root=args.pack_root)
    payload = {
        "ok": pack is not None,
        "language": args.lang,
        "pack_version": (pack or {}).get("pack_version"),
        "rules": len((pack or {}).get("rules", [])),
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if pack is not None:
            print("[OK] 语言包可用：%s（v%s，%d 条规则）"
                  % (args.lang, payload["pack_version"], payload["rules"]))
        else:
            print("[FAIL] 语言包不可用：%s" % args.lang)
        for w in warnings:
            print("       [提示] %s" % w)
    sys.exit(0 if pack is not None else 2)


if __name__ == "__main__":
    main()
