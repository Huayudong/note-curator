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
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from nc_core import atomic_write_text  # B12-04 manifest 写入

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


def _validate_concepts(pack_dir, warnings):
    path = pack_dir / "concepts.json"
    if not path.is_file():
        return
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        warnings.append("concepts.json 无法解析: %s" % exc)
        return
    for i, item in enumerate(items):
        if not {"zh", "en"} <= set(item):
            warnings.append("concepts.json 第 %d 条缺 zh/en 键" % (i + 1))


def _read_manifest(pack_dir):
    path = Path(pack_dir) / "manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def hash_text_file(path):
    """按归一化换行后的 UTF-8 内容哈希：CRLF 与 LF 视为同一内容，
    Windows 工作副本与 CI 检出的行尾差异不影响完整性校验（B12-04）。"""
    text = Path(path).read_text(encoding="utf-8")
    text = text.replace(chr(13) + chr(10), chr(10))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_manifest(pack_dir):
    """B12-04：包内 manifest.json 记录每个文件的 sha256；不一致即拒绝。"""
    manifest = _read_manifest(pack_dir)
    if manifest is None:
        return True, []  # 无 manifest 的内置包按原样信任
    files = manifest.get("files") or {}
    for rel, digest in files.items():
        target = Path(pack_dir) / rel
        if not target.is_file():
            return False, ["manifest 列出的文件缺失: %s" % rel]
        actual = hash_text_file(target)
        if actual != digest:
            return False, ["文件完整性不符: %s" % rel]
    return True, []


def write_manifest(pack_dir):
    """为包目录生成 manifest.json（发包前调用）。"""
    pack_dir = Path(pack_dir)
    files = {}
    for f in sorted(pack_dir.rglob("*")):
        if f.is_file() and f.name != "manifest.json":
            rel = f.relative_to(pack_dir).as_posix()
            files[rel] = hash_text_file(f)
    manifest = _read_manifest(pack_dir) or {}
    manifest["files"] = files
    manifest.setdefault("pack_version", "0.0.0")
    manifest.setdefault("channel", "stable")
    atomic_write_text(pack_dir / "manifest.json",
                      json.dumps(manifest, ensure_ascii=False,
                                  indent=2) + chr(10))
    return manifest


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
        # B12-03 限额：规则数量/模式长度/词条规模/包体积受限
        if len(rules) > 200:
            errors.append("rules 数量 %d 超过上限 200" % len(rules))
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
            status = rule.get("status", "stable")
            if status not in ("stable", "candidate", "deprecated"):
                errors.append("rules[%s] status 非法: %r" % (rid, status))
            pattern = rule.get("pattern")
            if pattern is not None:
                if len(str(pattern)) > 500:
                    errors.append("rules[%s] pattern 超过 500 字符上限" % rid)
                else:
                    try:
                        import re
                        re.compile(str(pattern))
                    except re.error as exc:
                        errors.append("rules[%s] pattern 无法编译: %s" % (rid, exc))
    terms = pack.get("terms") or {}
    for key, value in terms.items():
        if isinstance(value, list) and len(value) > 500:
            errors.append("terms.%s 数量 %d 超过上限 500" % (key, len(value)))
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
        if path.stat().st_size > 2 * 1024 * 1024:
            return None, ["pack.json 超过 2MB 体积上限（B12-03）"]
        pack = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return None, ["语言包无法解析 %s: %s" % (path, exc)]
    ok_manifest, manifest_problems = verify_manifest(path.parent)
    if not ok_manifest:
        return None, ["完整性校验未通过（B12-04）：%s" % "；".join(manifest_problems)]
    errors = validate_pack(pack, lang)
    if errors:
        return None, ["语言包校验未通过 %s：%s" % (path, "；".join(errors))]
    # B12-05/10：渠道与规则状态过滤
    channel = os.environ.get("NC_PACK_CHANNEL", "stable")
    manifest = _read_manifest(path.parent)
    pack_channel = (manifest or {}).get("channel", "stable")
    if pack_channel != channel:
        warnings.append("渠道不匹配：包为 %s，当前渠道 %s（candidate 规则不生效）"
                        % (pack_channel, channel))
    kept = []
    for rule in pack.get("rules", []):
        status = rule.get("status", "stable")
        if status == "deprecated":
            warnings.append("规则 %s 已废弃，未加载" % rule.get("id"))
            continue
        if status == "candidate" and channel != "experimental":
            warnings.append("规则 %s 为 candidate，仅 experimental 渠道加载"
                            % rule.get("id"))
            continue
        kept.append(rule)
    pack["rules"] = kept
    _validate_terminology(path.parent, warnings)
    _validate_examples(path.parent, warnings)
    _validate_concepts(path.parent, warnings)
    return pack, warnings


def install_pack(lang, src_dir):
    """安装：校验 → 备份当前 → 换装（B12-04）。"""
    import shutil
    src_dir = Path(src_dir)
    pack_file = src_dir / "pack.json"
    if not pack_file.is_file():
        print("[ERROR] 来源目录缺少 pack.json: %s" % src_dir, file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(pack_file.read_text(encoding="utf-8"))
    except ValueError as exc:
        print("[ERROR] pack.json 无法解析: %s" % exc, file=sys.stderr)
        sys.exit(2)
    errors = validate_pack(data, lang)
    if errors:
        print("[STOP] 来源包校验未通过：%s" % "；".join(errors), file=sys.stderr)
        sys.exit(2)
    write_manifest(src_dir)
    dest = pack_path(lang).parent
    dest.mkdir(parents=True, exist_ok=True)
    version = str(data.get("pack_version", "0"))
    if any(dest.iterdir()):
        stamp = "%d" % int(time.time() * 1000)  # 毫秒级，避免同秒冲突
        backup_root = pack_root() / ".backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        bdir = backup_root / ("%s-prev-%s" % (dest.name, stamp))
        shutil.copytree(dest, bdir)
        (backup_root / (dest.name + ".latest")).write_text(bdir.name, encoding="utf-8")
    shutil.rmtree(dest)
    shutil.copytree(src_dir, dest)
    home = str(Path.home())
    shown = str(dest).replace(home, "~") if str(dest).startswith(home) else str(dest)
    print("[OK] 已安装 %s v%s -> %s（上一版本已备份）" % (lang, version, shown))
    sys.exit(0)


def rollback_pack(lang):
    """回退到最近一次安装前的备份（回退本身也可再回退，B12-06）。"""
    import shutil
    dest = pack_path(lang).parent
    name = dest.name
    latest = pack_root() / ".backup" / (name + ".latest")
    if not latest.is_file():
        print("[STOP] 没有可用备份。", file=sys.stderr)
        sys.exit(2)
    src = pack_root() / ".backup" / latest.read_text(encoding="utf-8").strip()
    if not src.is_dir():
        print("[STOP] 备份目录缺失：%s" % src, file=sys.stderr)
        sys.exit(2)
    stamp = "%d" % int(time.time() * 1000)  # 毫秒级，避免同秒冲突
    keep = pack_root() / ".backup" / ("%s-rollback-%s" % (name, stamp))
    if dest.exists():
        shutil.copytree(dest, keep)
    shutil.rmtree(dest)
    shutil.copytree(src, dest)
    (latest.parent / (name + ".latest")).write_text(keep.name, encoding="utf-8")
    home = str(Path.home())
    shown = str(keep).replace(home, "~") if str(keep).startswith(home) else str(keep)
    print("[OK] 已回退 %s（回退前的状态保留在 %s）" % (lang, shown))
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="语言包校验与加载")
    ap.add_argument("--lang", choices=sorted(PACK_DIR_NAMES), required=True)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--pack-root", help="语言包根目录（默认 skill 内 language-packs；"
                                        "可用 NOTE_CURATOR_PACK_ROOT 覆盖）")
    ap.add_argument("--write-manifest", action="store_true",
                    help="为该语言包目录生成完整性清单（发包前，B12-04）")
    ap.add_argument("--install", metavar="SRC",
                    help="安装来源目录的语言包（校验 + 备份 + 换装）")
    ap.add_argument("--rollback", action="store_true",
                    help="回退到最近一次安装前的备份（B12-06）")
    args = ap.parse_args()

    if args.write_manifest:
        manifest = write_manifest(pack_path(args.lang).parent)
        print("[OK] manifest 已生成（%d 个文件）" % len(manifest.get("files", {})))
        sys.exit(0)
    if args.install:
        install_pack(args.lang, args.install)
    if args.rollback:
        rollback_pack(args.lang)

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
