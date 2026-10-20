#!/usr/bin/env python3
"""
style_learn.py — 把（用户改过的）笔记并入现有文风画像，实现持续学习。

核心原则：**信号来自用户的改稿，不来自插件自己的输出。**
默认用法是用户在笔记写入并亲手修改后，说「学习这篇的写法」，
Agent 再用本脚本把改后的版本并入画像。

行为：
    1. 读取现有 profile.json（保留 language / voice.md / 历史）。
    2. 把 --note 指向的笔记追加进画像的语料清单（去重；语言不匹配则拒绝）。
    3. 按清单重算统计（滚动窗口：--sample N 只保留最近 N 篇）。
    4. 覆盖 profile.json 与 profile.md；voice.md 不动，历史记录追加。

用法：
    python style_learn.py --profile ~/.note-curator/style-profiles/zh/profile.json \
        --note "04 人工智能/RAG 向量检索.md"
    # 多篇：--note 可重复；--sample 20 控制滚动窗口

退出码：0 成功；2 全部被拒绝/没有可学习的笔记；1 参数或 IO 错误。
"""

import argparse
import datetime
import hashlib
import json
import sys
import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from pathlib import Path

from langdetect import detect_language_detail
from style_metrics import analyze_corpus, clean_markdown, profile_to_markdown


def is_within(base, path):
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def main():
    ap = argparse.ArgumentParser(description="把用户改过的笔记并入文风画像")
    ap.add_argument("--profile", required=True, help="现有 profile.json 路径")
    ap.add_argument("--note", action="append", required=True,
                    help="笔记路径（vault 内相对路径或绝对路径；可重复传入多篇）")
    ap.add_argument("--sample", type=int, default=0,
                    help="学习后语料最多保留最近 N 篇（0 = 不限制）")
    args = ap.parse_args()

    profile_path = Path(args.profile).expanduser()
    if not profile_path.is_file():
        raise SystemExit("[ERROR] profile.json 不存在: %s" % profile_path)
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("[ERROR] 无法读取画像 JSON: %s" % exc)

    source = profile.get("source", {})
    vault = Path(source.get("vault", ".")).expanduser()
    lang = profile.get("language", "zh")
    existing = list(source.get("files", []))

    revisions = dict(profile.get("revisions", {}))
    now = datetime.datetime.now().isoformat(timespec="seconds")
    added, updated, rejected = [], [], []
    for note in args.note:
        p = Path(note).expanduser()
        if not p.is_absolute():
            p = vault / p
        p = p.resolve()
        if not p.is_file():
            rejected.append((note, "文件不存在"))
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            rejected.append((note, "读取失败: %s" % exc))
            continue
        detail = detect_language_detail(clean_markdown(raw))
        if detail["primary"] not in (lang, "und"):
            rejected.append((note, "语言与画像不符（画像 %s，检测 %s）"
                             % (lang, detail["primary"])))
            continue
        rel = str(p.relative_to(vault)) if is_within(vault, p) else str(p)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        seen = revisions.get(rel)
        if seen and seen.get("hash") == digest:
            continue  # 内容无变化：幂等无操作（B02-07）
        if rel not in existing:
            existing.append(rel)
            added.append(rel)
        else:
            updated.append(rel)
        revisions[rel] = {"hash": digest, "learned_at": now}

    for note, reason in rejected:
        print("[SKIP] %s — %s" % (note, reason), file=sys.stderr)

    if not added and not updated:
        print("[STOP] 没有新增或变化的笔记（相同内容重复学习无操作）。", file=sys.stderr)
        sys.exit(2)

    if args.sample and args.sample > 0 and len(existing) > args.sample:
        def _mtime(rel):
            p = Path(rel)
            if not p.is_absolute():
                p = vault / rel
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0
        ordered = sorted(existing, key=_mtime, reverse=True)
        existing = ordered[:args.sample]
        dropped = ordered[args.sample:]
        print("[INFO] 滚动窗口按样本时间保留最新 %d 篇，淘汰 %d 篇较旧语料"
              % (args.sample, len(dropped)), file=sys.stderr)

    files = []
    for rel in existing:
        p = Path(rel)
        if not p.is_absolute():
            p = vault / rel
        if p.is_file():
            files.append(p)

    refreshed = analyze_corpus(files, max_samples=5, lang=lang)
    for sample in refreshed.get("samples", []):
        sample_path = Path(sample["source"])
        if is_within(vault, sample_path):
            sample["source"] = str(sample_path.relative_to(vault))

    history = list(profile.get("history", []))
    history.append({"at": now, "learned": added, "updated": updated})
    refreshed["history"] = history[-20:]
    refreshed["learned_count"] = (profile.get("learned_count", 0)
                                  + len(added) + len(updated))
    refreshed["created_at"] = profile.get("created_at") or profile.get("generated_at")
    refreshed["source"] = dict(source)
    refreshed["source"]["files"] = existing
    refreshed["revisions"] = {k: v for k, v in revisions.items() if k in set(existing)}

    profile_path.write_text(json.dumps(refreshed, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    (profile_path.parent / "profile.md").write_text(profile_to_markdown(refreshed),
                                                    encoding="utf-8")

    print("[OK] 已学习 %d 篇（新增 %d，刷新 %d），画像语料现为 %d 篇（language: %s）"
          % (len(added) + len(updated), len(added), len(updated),
             len(existing), lang))
    print("     更新：%s" % profile_path)
    print("     voice.md 未改动；若语气判断也要更新，让 Agent 重新阅读样本后修订。")


if __name__ == "__main__":
    main()
