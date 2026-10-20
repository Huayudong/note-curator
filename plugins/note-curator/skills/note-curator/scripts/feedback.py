#!/usr/bin/env python3
"""
feedback.py — B10-08/09 用户反馈与缺陷→回归任务管道。

反馈分类（B10-09）：content_error（内容错误）/ style_mismatch（风格不符）/
structure（结构不便）/ terminology（术语不符）/ other。

反馈默认只存本地（~/.note-curator/feedback.jsonl），不自动上传；
--to-task 把一条反馈转成待办评测任务存根（evals/tasks/pending/），
供纳入下一轮冻结评测（B10-08：实际失败转成回归任务）。

用法：
    python feedback.py add --category style_mismatch --note "句长偏长" \
        [--draft draft.md] [--profile profile.json]
    python feedback.py list [--last 10]
    python feedback.py to-task --id 3 --out evals/tasks/pending/task-x.json

退出码：0 成功；2 没有该条目。
"""

import argparse
import json
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

CATEGORIES = ("content_error", "style_mismatch", "structure",
              "terminology", "other")


def feedback_path():
    return nc_core.data_root() / "feedback.jsonl"


def load_all():
    p = feedback_path()
    if not p.is_file():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def cmd_add(args):
    if args.category not in CATEGORIES:
        print("[ERROR] 分类必须是：%s" % "、".join(CATEGORIES), file=sys.stderr)
        sys.exit(1)
    draft_text = ""
    if args.draft and Path(args.draft).is_file():
        draft_text = Path(args.draft).read_text(encoding="utf-8",
                                                errors="ignore")[:2000]
    entries = load_all()
    entry = {
        "id": len(entries) + 1,
        "at": nc_core.now_iso(),
        "category": args.category,
        "note": args.note or "",
        "draft_excerpt": draft_text,
        "profile": args.profile or "",
        "status": "open",
    }
    entries.append(entry)
    p = feedback_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print("[OK] 反馈 #%d 已记录（%s）。默认仅存本地，不自动上传。"
          % (entry["id"], args.category))
    sys.exit(0)


def cmd_list(args):
    entries = load_all()
    for e in entries[-max(args.last, 1):]:
        print("#%d [%s] %s — %s" % (e["id"], e["category"], e.get("status"),
                                    e.get("note", "")[:60]))
    if not entries:
        print("（暂无反馈）")
    sys.exit(0)


def cmd_to_task(args):
    entries = load_all()
    target = None
    for e in entries:
        if e.get("id") == args.id:
            target = e
            break
    if target is None:
        print("[STOP] 没有该反馈：%s" % args.id, file=sys.stderr)
        sys.exit(2)
    task = {
        "schema": 1,
        "origin": "feedback",
        "feedback_id": target["id"],
        "category": target["category"],
        "note": target.get("note", ""),
        "draft_excerpt": target.get("draft_excerpt", ""),
        "status": "pending",
        "created_at": nc_core.now_iso(),
    }
    out = Path(args.out)
    nc_core.atomic_write_text(out, json.dumps(task, ensure_ascii=False, indent=2))
    target["status"] = "converted"
    p = feedback_path()
    with open(p, "w", encoding="utf-8") as handle:
        for e in entries:
            handle.write(json.dumps(e, ensure_ascii=False) + "\n")
    print("[OK] 已生成待办评测任务 -> %s" % out)
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="反馈与回归任务管道（B10）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("add", help="记录反馈")
    p1.add_argument("--category", required=True)
    p1.add_argument("--note", default="")
    p1.add_argument("--draft", help="相关草稿（只存前 2000 字摘录）")
    p1.add_argument("--profile", help="相关画像路径")

    p2 = sub.add_parser("list", help="列出反馈")
    p2.add_argument("--last", type=int, default=10)

    p3 = sub.add_parser("to-task", help="反馈转待办评测任务")
    p3.add_argument("--id", type=int, required=True)
    p3.add_argument("--out", required=True)

    args = ap.parse_args()
    {"add": cmd_add, "list": cmd_list, "to-task": cmd_to_task}[args.cmd](args)


if __name__ == "__main__":
    main()
