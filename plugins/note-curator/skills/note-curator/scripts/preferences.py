#!/usr/bin/env python3
"""
preferences.py — B06 偏好状态机与个人偏好管理。

数据（都在 profile.json 内，随画像走）：
    preferences: [{id, type, value, scope{language, source_event},
                   status: active|rejected|superseded|forgotten,
                   enabled: bool, disabled_reason?, evidence, created_at}]
    learning_events: [...learn_edit.py 产生]

状态机（方案 §5.6）：
    - candidate → confirm → active（用户显式确认即生效）
    - active --disable--> active+enabled=false（可逆停用，不等于拒绝）
    - rejected / forgotten 不可用开关恢复
    - 同 type 同方向的新证据跨笔记累计 evidence；同域冲突报告 superseded 建议

CLI：
    list / disable / enable / forget / export / import / conflicts

退出码：0 成功；2 没有该对象或被拒绝；1 参数错误。
"""

import argparse
import json
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具


def load_profile(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit("[ERROR] profile.json 不存在: %s" % p)
    return p, json.loads(p.read_text(encoding="utf-8"))


def save_profile(path, profile):
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def find_pref(profile, pref_id):
    for pref in profile.get("preferences", []):
        if pref.get("id") == pref_id:
            return pref
    return None


def learning_mode(profile):
    """学习模式：explicit（默认）/ assisted / auto / off。"""
    return profile.get("learning_mode", "explicit")


def evidence_for(profile, pref_type, direction=None):
    """跨笔记独立证据计数：同一 type（与方向）来自不同 note 的事件数。"""
    notes = set()
    for e in profile.get("learning_events", []):
        for c in e.get("candidates", []):
            if c.get("type") != pref_type or c.get("status") in ("rejected", "undone"):
                continue
            if direction and c.get("direction") != direction:
                continue
            if e.get("undone"):
                continue
            notes.add(e.get("note", ""))
    notes.discard("")
    return len(notes)


def cmd_list(args):
    _, profile = load_profile(args.profile)
    rows = profile.get("preferences", [])
    mode = learning_mode(profile)
    if args.json:
        print(json.dumps({"learning_mode": mode, "preferences": rows},
                         ensure_ascii=False, indent=2))
    else:
        print("学习模式：%s；偏好 %d 条" % (mode, len(rows)))
        for pref in rows:
            state = pref["status"]
            if not pref.get("enabled", True):
                state += "（已停用：%s）" % pref.get("disabled_reason", "")
            print("  %s  [%s] %s  evidence=%d  %s"
                  % (pref["id"], state, pref["type"],
                     pref.get("evidence", 1),
                     json.dumps(pref.get("value", {}), ensure_ascii=False)[:80]))
    sys.exit(0)


def cmd_disable(args):
    path, profile = load_profile(args.profile)
    pref = find_pref(profile, args.pref)
    if pref is None:
        print("[STOP] 没有该偏好：%s" % args.pref, file=sys.stderr)
        sys.exit(2)
    if pref["status"] != "active":
        print("[STOP] 只有 active 偏好可停用（当前 %s）。" % pref["status"],
              file=sys.stderr)
        sys.exit(2)
    pref["enabled"] = False
    pref["disabled_reason"] = args.reason or "用户停用"
    save_profile(path, profile)
    print("[OK] 已停用（可 enable 恢复）：%s" % args.pref)
    sys.exit(0)


def cmd_enable(args):
    path, profile = load_profile(args.profile)
    pref = find_pref(profile, args.pref)
    if pref is None:
        print("[STOP] 没有该偏好：%s" % args.pref, file=sys.stderr)
        sys.exit(2)
    if pref["status"] != "active":
        print("[STOP] rejected/forgotten 偏好不能用开关恢复。", file=sys.stderr)
        sys.exit(2)
    pref["enabled"] = True
    pref.pop("disabled_reason", None)
    save_profile(path, profile)
    print("[OK] 已恢复启用：%s" % args.pref)
    sys.exit(0)


def cmd_forget(args):
    """忘记：删除范围内证据（学习事件 + 候选 + 派生偏好），重建派生状态。"""
    path, profile = load_profile(args.profile)
    pref = find_pref(profile, args.pref)
    source_event = None
    if pref is not None:
        if pref["status"] == "forgotten":
            print("[STOP] 该偏好已忘记（幂等无操作）。", file=sys.stderr)
            sys.exit(2)
        pref["status"] = "forgotten"
        pref["enabled"] = False
        source_event = pref.get("scope", {}).get("source_event")
    events = profile.get("learning_events", [])
    removed_events = 0
    matched_any = pref is not None
    if args.pref.startswith("event:") or source_event:
        target = args.pref.split(":", 1)[1] if ":" in args.pref else source_event
        kept = []
        for e in events:
            if e.get("event_id") == target:
                removed_events += 1
                continue
            kept.append(e)
        if removed_events:
            profile["learning_events"] = kept
            matched_any = True
            for other in profile.get("preferences", []):
                if other.get("scope", {}).get("source_event") == target:
                    other["status"] = "forgotten"
                    other["enabled"] = False
    if not matched_any:
        print("[STOP] 没有可忘记的对象（可能已删除）：%s" % args.pref,
              file=sys.stderr)
        sys.exit(2)
    save_profile(path, profile)
    print("[OK] 已忘记 %s：删除学习事件 %d 条，派生偏好标记 forgotten。" % (args.pref, removed_events))
    print("     画像统计如需重算：重跑 style_profile.py（statistics 由语料派生）。")
    sys.exit(0)


def cmd_export(args):
    """导出偏好与必要元数据；不含原文证据与生成基线（方案 §10.4）。"""
    _, profile = load_profile(args.profile)
    payload = {
        "schema": 1,
        "exported_at": nc_core.now_iso(),
        "language": profile.get("language", "zh"),
        "learning_mode": learning_mode(profile),
        "preferences": [{k: v for k, v in pref.items()
                         if k not in ("scope",) or True}
                        for pref in profile.get("preferences", [])],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        nc_core.atomic_write_text(args.out, text)
        print("[OK] 已导出 %d 条偏好 -> %s（不含原文证据）"
              % (len(payload["preferences"]), args.out))
    else:
        print(text)
    sys.exit(0)


def cmd_import(args):
    path, profile = load_profile(args.profile)
    incoming = json.loads(Path(args.file).read_text(encoding="utf-8"))
    prefs = incoming.get("preferences", [])
    existing = {p.get("id") for p in profile.get("preferences", [])}
    added = 0
    for pref in prefs:
        if pref.get("id") in existing:
            continue
        profile.setdefault("preferences", []).append(pref)
        existing.add(pref.get("id"))
        added += 1
    if incoming.get("learning_mode"):
        profile["learning_mode"] = incoming["learning_mode"]
    save_profile(path, profile)
    print("[OK] 导入 %d 条（跳过重复 %d 条）" % (added, len(prefs) - added))
    sys.exit(0)


def cmd_conflicts(args):
    """同语言同 type 但方向/取值矛盾的 active 偏好报告。"""
    _, profile = load_profile(args.profile)
    active = [p for p in profile.get("preferences", [])
              if p["status"] == "active" and p.get("enabled", True)]
    conflicts = []
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a["type"] != b["type"]:
                continue
            if a["type"] == "sentence_length" and \
                    a["value"].get("direction") != b["value"].get("direction"):
                conflicts.append({"type": a["type"], "a": a["id"], "b": b["id"],
                                  "why": "句长方向相反",
                                  "suggestion": "更具体或更新的保留，另一个标 superseded"})
            elif a["type"] == "avoid_phrase" and \
                    a["value"].get("phrase") != b["value"].get("phrase"):
                continue
    if args.json:
        print(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2))
    else:
        for c in conflicts:
            print("[冲突] %s：%s vs %s —— %s"
                  % (c["type"], c["a"], c["b"], c["suggestion"]))
        if not conflicts:
            print("（无冲突）")
    sys.exit(0 if not conflicts else 0)


def main():
    ap = argparse.ArgumentParser(description="个人偏好管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("list", help="列出偏好")
    p1.add_argument("--profile", required=True)
    p1.add_argument("--json", action="store_true")

    p2 = sub.add_parser("disable", help="可逆停用（不等于拒绝）")
    p2.add_argument("--profile", required=True)
    p2.add_argument("--pref", required=True)
    p2.add_argument("--reason")

    p3 = sub.add_parser("enable", help="恢复启用")
    p3.add_argument("--profile", required=True)
    p3.add_argument("--pref", required=True)

    p4 = sub.add_parser("forget", help="忘记：删除事件证据并废弃派生偏好")
    p4.add_argument("--profile", required=True)
    p4.add_argument("--pref", help="偏好 ID 或 event:<event_id>")

    p5 = sub.add_parser("export", help="导出偏好（不含原文证据）")
    p5.add_argument("--profile", required=True)
    p5.add_argument("--out")

    p6 = sub.add_parser("import", help="导入偏好（按 ID 去重合并）")
    p6.add_argument("--profile", required=True)
    p6.add_argument("--file", required=True)

    p7 = sub.add_parser("conflicts", help="报告 active 偏好间冲突")
    p7.add_argument("--profile", required=True)
    p7.add_argument("--json", action="store_true")

    args = ap.parse_args()
    {"list": cmd_list, "disable": cmd_disable, "enable": cmd_enable,
     "forget": cmd_forget, "export": cmd_export, "import": cmd_import,
     "conflicts": cmd_conflicts}[args.cmd](args)


if __name__ == "__main__":
    main()
