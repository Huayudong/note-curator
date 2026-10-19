#!/usr/bin/env python3
"""
style_profile.py — 从本地已有笔记建立中文文风画像。

用法：
    # 分析某个目录下最近 20 篇笔记
    python style_profile.py --vault "D:/Obsidian/MyVault" --dir "04 人工智能"

    # 分析指定文件
    python style_profile.py --vault "D:/Obsidian/MyVault" --files "a.md,b.md" --name my-style

    # 分析整个 vault
    python style_profile.py --vault "D:/Obsidian/MyVault" --all --name vault

输出：
    <profile_dir>/<name>/profile.json   机器可读的统计画像
    <profile_dir>/<name>/profile.md     人可读的统计摘要
    <profile_dir>/<name>/voice.md       定性画像模板（由 Agent 阅读样本后填写）

默认 profile_dir 是 ~/.note-curator/style-profiles。
只依赖 Python 标准库。
"""

import argparse
import json
import re
import sys
from pathlib import Path

from style_metrics import analyze_corpus, profile_to_markdown

DEFAULT_PROFILE_DIR = Path.home() / ".note-curator" / "style-profiles"
SKIP_DIRS = {".git", ".trash", ".obsidian", "node_modules", "__pycache__"}
VOICE_TEMPLATE = """# 文风画像（定性）

> 由 Agent 阅读 profile.md 和 samples 后填写。只写样本中能观察到的特征，不要凭空编造。
> 这份文件会和 profile.json 一起被后续写作读取。

## 语气与态度

## 句长与节奏

## 用词习惯

## 段落与论证

## 标点习惯

## 要模仿

## 要避免

## 代表句
"""


def slugify(value):
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE)
    value = value.strip("-._")
    return value or "default"


def is_within(base, path):
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def collect_files(vault, args):
    if args.all:
        target = vault
        candidates = vault.rglob("*.md") if not args.no_recursive else vault.glob("*.md")
        mode = "all"
    elif args.dir:
        target = (vault / args.dir).resolve()
        if not is_within(vault, target):
            raise SystemExit("[ERROR] --dir 必须位于 vault 内: %s" % target)
        if not target.is_dir():
            raise SystemExit("[ERROR] 目录不存在: %s" % target)
        candidates = target.rglob("*.md") if not args.no_recursive else target.glob("*.md")
        mode = "dir"
    else:
        target = vault
        files = []
        for item in args.files.split(","):
            item = item.strip()
            if not item:
                continue
            path = (vault / item).resolve()
            if not is_within(vault, path):
                raise SystemExit("[ERROR] --files 只能指向 vault 内的文件: %s" % path)
            if path.is_file():
                files.append(path)
            else:
                print("[WARN] 文件不存在，已跳过: %s" % path, file=sys.stderr)
        if not files:
            raise SystemExit("[ERROR] --files 没有找到可用文件")
        return files, target, "files"

    files = []
    for path in candidates:
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.startswith("."):
            continue
        try:
            if path.stat().st_size < args.min_chars:
                continue
        except OSError:
            continue
        files.append(path)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if args.sample and args.sample > 0:
        files = files[:args.sample]
    if not files:
        raise SystemExit("[ERROR] 没有找到足够大的 .md 文件；可以降低 --min-chars 或检查路径")
    return files, target, mode


def main():
    ap = argparse.ArgumentParser(description="从本地笔记建立中文文风画像")
    ap.add_argument("--vault", required=True, help="知识库根目录")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dir", help="分析该目录下的笔记（相对 vault）")
    group.add_argument("--files", help="分析指定文件，逗号分隔（相对 vault）")
    group.add_argument("--all", action="store_true", help="分析整个 vault")
    ap.add_argument("--sample", type=int, default=20, help="最多取最近 N 篇，默认 20；0 表示全部")
    ap.add_argument("--min-chars", type=int, default=200, help="跳过小于该字符数的文件，默认 200")
    ap.add_argument("--name", help="画像名称；默认按目录名生成")
    ap.add_argument("--profile-dir", help="画像根目录；默认 ~/.note-curator/style-profiles")
    ap.add_argument("--out", help="profile.json 的输出路径；默认 <profile-dir>/<name>/profile.json")
    ap.add_argument("--no-recursive", action="store_true", help="只扫描目标目录第一层")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit("[ERROR] vault 不存在: %s" % vault)

    files, target, mode = collect_files(vault, args)
    name = slugify(args.name or (args.dir if args.dir else ("vault" if args.all else "files")))
    profile_root = Path(args.profile_dir).expanduser() if args.profile_dir else DEFAULT_PROFILE_DIR
    profile_dir = profile_root / name
    profile_path = Path(args.out).expanduser() if args.out else profile_dir / "profile.json"
    profile_dir = profile_path.parent
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile = analyze_corpus(files, max_samples=5)
    for sample in profile.get("samples", []):
        sample_path = Path(sample["source"])
        if is_within(vault, sample_path):
            sample["source"] = str(sample_path.relative_to(vault))
    profile["source"] = {
        "vault": str(vault),
        "target": str(target),
        "mode": mode,
        "files": [str(p.relative_to(vault)) if is_within(vault, p) else str(p) for p in files],
    }

    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = profile_dir / "profile.md"
    markdown_path.write_text(profile_to_markdown(profile), encoding="utf-8")

    voice_path = profile_dir / "voice.md"
    if not voice_path.exists():
        voice_path.write_text(VOICE_TEMPLATE, encoding="utf-8")
        voice_state = "已创建模板"
    else:
        voice_state = "已存在，保留原内容"

    print("[OK] 文风画像已生成")
    print("     统计：%s" % profile_path)
    print("     摘要：%s" % markdown_path)
    print("     定性：%s（%s）" % (voice_path, voice_state))
    print("     样本：%d 篇，共 %d 字" % (
        profile["corpus"]["file_count"], profile["corpus"]["total_chars"]))
    print("[NEXT] 让 Agent 阅读 profile.md 和 samples，补全 voice.md 的语气、用词和段落习惯。")


if __name__ == "__main__":
    main()
