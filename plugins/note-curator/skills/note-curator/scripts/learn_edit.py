#!/usr/bin/env python3
"""
learn_edit.py — B05 改稿学习：把用户对已生成笔记的修改转为偏好候选。

与 style_learn.py 的分工：
  - style_learn.py：把整篇改稿并入统计画像（B02 修订刷新）。
  - learn_edit.py：对比「上次基线/学习版本 → 当前版本」，按差异类别
    提炼**可操作偏好候选**，经用户确认后才生效（默认不自动晋升）。

差异分类（B05-03，确定性启发式）：
    fact        数字/单位/日期变了 → 事实修正（不转文风偏好，B05-07）
    negation    否定词增删 → 事实修正
    structure   标题层级变化 → 结构调整
    formatting  仅空白/标点/列表标记变化 → 排版
    content     段落增删（非以上各类）→ 内容增删
    expression  措辞变化（其余）→ 表达调整

偏好候选（B05-04）：仅从表达/排版类差异提炼（如句长方向、被删的
AI 腔短语、标点习惯），带作用域（语言 + 证据数）与状态 machine：
    candidate → (确认) active / (拒绝) rejected；事件幂等，可撤销（B05-09）。

CLI：
    python learn_edit.py diff  --profile P --note N [--baseline-run RUN_ID]
    python learn_edit.py confirm --profile P --candidate ID
    python learn_edit.py reject  --profile P --candidate ID --reason "..."
    python learn_edit.py undo    --profile P --event ID
    python learn_edit.py candidates --profile P [--json]

退出码：0 成功；2 无差异/无该候选；1 参数错误。
"""

import argparse
import datetime
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from langdetect import detect_language_detail
from style_lang_zh import AI_TELL_PATTERNS

NUMBER_RE = re.compile(r"\d[\d,.]*\s*[%万亿GBMBms秒分天月年]?")
NEG_RE = re.compile(r"不(?:支持|能|会|宜|适用)|无法|并非|cannot|not supported", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
FORMAT_ONLY_RE = re.compile(r"^[\s#*>`\-\d.|，。；：、!?\[\]()\"']*$")


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _para_split(text):
    pat = chr(92) + "n" + chr(92) + "s*" + chr(92) + "n"
    return [q for q in re.split(pat, text) if q.strip()]


def _without_ws(text):
    return re.sub(chr(91) + chr(92) + "s" + chr(93) + "+", "", text)


WHY = {"fact": "数字或否定变化", "structure": "标题层级变化",
       "formatting": "仅空白或标点变化", "content": "段落增删",
       "expression": "措辞调整"}


def classify(before, after):
    """返回 (类别列表, 说明)。事实信号优先；混合改稿并列多类（B06）。"""
    cats = []
    if NUMBER_RE.findall(before) != NUMBER_RE.findall(after):
        cats.append("fact")
    if bool(NEG_RE.search(before)) != bool(NEG_RE.search(after)):
        if "fact" not in cats:
            cats.append("fact")
    if HEADING_RE.findall(before) != HEADING_RE.findall(after):
        cats.append("structure")
    if _without_ws(before) == _without_ws(after):
        cats.append("formatting")
    elif FORMAT_ONLY_RE.match(before) and FORMAT_ONLY_RE.match(after):
        cats.append("formatting")
    else:
        paras_b = len(_para_split(before))
        paras_a = len(_para_split(after))
        if paras_b != paras_a:
            cats.append("content")
        elif not cats or _without_numbers(before) != _without_numbers(after):
            cats.append("expression")
    if not cats:
        cats.append("expression")
    return cats, "、".join(WHY.get(c, c) for c in cats)


def _without_numbers(text):
    return re.sub(NUMBER_RE, "", _without_ws(text))


def load_profile(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit("[ERROR] profile.json 不存在: %s" % p)
    return p, json.loads(p.read_text(encoding="utf-8"))


def base_text_for(profile_path, profile, note_path, baseline_run=None):
    """取比较基线：优先生成基线文件，其次上次学习修订的哈希对应内容快照。"""
    if baseline_run:
        b = nc_core.data_root() / "baselines" / ("%s.json" % baseline_run)
        if b.is_file():
            return json.loads(b.read_text(encoding="utf-8")).get("content", "")
        raise SystemExit("[ERROR] 找不到生成基线: %s" % b)
    rev = (profile.get("revisions") or {}).get(str(note_path))
    if rev and rev.get("snapshot") is not None:
        return rev["snapshot"]
    return None


def extract_expression_candidates(before, after, lang):
    """从表达类差异提炼候选：被删除的 AI 腔短语、句长方向。"""
    candidates = []
    removed_lines = [l for l in before.splitlines() if l and l not in after.splitlines()]
    seen_groups = set()
    for line in removed_lines:
        for group, pattern in AI_TELL_PATTERNS.items():
            if group in seen_groups:
                continue
            if re.search(pattern, line):
                seen_groups.add(group)
                candidates.append({
                    "type": "avoid_phrase",
                    "phrase": line.strip()[:60],
                    "tell_group": group,
                    "why": "用户改稿删掉了「%s」类表达" % group,
                })
                break
    def avg_len(text):
        sents = [s for s in re.split(r"[。！？.!?]", text) if s.strip()]
        if not sents:
            return 0
        return sum(len(re.sub(r"\s+", "", s)) for s in sents) / len(sents)
    b_len, a_len = avg_len(before), avg_len(after)
    if b_len and abs(a_len - b_len) / b_len >= 0.25:
        direction = "shorter" if a_len < b_len else "longer"
        candidates.append({
            "type": "sentence_length",
            "direction": direction,
            "why": "改稿后平均句长 %.0f→%.0f（%s）" % (b_len, a_len, direction),
        })
    return candidates


def cmd_diff(args):
    profile_path, profile = load_profile(args.profile)
    note = Path(args.note).expanduser().resolve()
    if not note.is_file():
        raise SystemExit("[ERROR] 笔记不存在: %s" % note)
    current = note.read_text(encoding="utf-8", errors="ignore")
    base = base_text_for(profile_path, profile, note, args.baseline_run)
    if base is None:
        print("[STOP] 没有可比较的基线（先跑 write_note 生成，或先 style_learn 建立修订快照）。",
              file=sys.stderr)
        sys.exit(2)
    if hashlib.sha256(base.encode("utf-8")).hexdigest() == \
            hashlib.sha256(current.encode("utf-8")).hexdigest():
        print("[STOP] 与基线内容一致，没有改稿差异（不产生学习证据）。", file=sys.stderr)
        sys.exit(2)

    detail = detect_language_detail(current)
    lang = profile.get("language", detail["primary"])
    sm = difflib.SequenceMatcher(None, base.splitlines(), current.splitlines())
    categories = {}
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        before = "\n".join(base.splitlines()[i1:i2])
        after = "\n".join(current.splitlines()[j1:j2])
        cats, why = classify(before, after)
        for cat in cats:
            categories[cat] = categories.get(cat, 0) + 1
        changes.append({"category": "+".join(cats), "why": why,
                        "before_excerpt": before.strip()[:80],
                        "after_excerpt": after.strip()[:80]})

    # 偏好候选仅来自表达/排版类（B05-04/07：事实修正不转文风偏好）
    pref_candidates = []
    if categories.get("expression") or categories.get("formatting"):
        pref_candidates = extract_expression_candidates(base, current, lang)

    event_id = "%s-%s" % (note.stem[:24], nc_core.new_run_id())
    event = {
        "event_id": event_id,
        "note": str(note),
        "base_hash": nc_core.sha256_text(base),
        "new_hash": nc_core.sha256_text(current),
        "categories": categories,
        "changes": changes[:20],
        "candidates": pref_candidates,
        "snapshot": current,
        "at": now_iso(),
    }
    for i, c in enumerate(pref_candidates, 1):
        c["candidate_id"] = "%s#%d" % (event_id, i)
    mode = profile.get("learning_mode", "explicit")
    if mode == "off":
        print("[STOP] 学习已关闭（config style.learning_mode: off），本次改稿不记录。",
              file=sys.stderr)
        sys.exit(2)

    events = profile.setdefault("learning_events", [])
    for e in events:
        if e.get("base_hash") == event["base_hash"] and \
                e.get("new_hash") == event["new_hash"]:
            print("[STOP] 该差异已记录（事件 %s），幂等无操作。" % e.get("event_id"),
                  file=sys.stderr)
            sys.exit(2)
    events.append(event)
    profile["learning_events"] = events[-50:]

    # B06-01：auto 模式下，跨 ≥2 篇独立笔记的同类表达候选自动生效
    if mode == "auto":
        per_key = {}
        for e in events:
            if e.get("undone"):
                continue
            for c in e.get("candidates", []):
                if c.get("status") in ("rejected", "undone"):
                    continue
                key = (c.get("type"),
                       c.get("tell_group") or c.get("phrase") or c.get("direction"))
                per_key.setdefault(key, {"notes": set(), "refs": []})
                per_key[key]["notes"].add(e.get("note", ""))
                per_key[key]["refs"].append((e, c))
        for key, info in per_key.items():
            if len(info["notes"]) >= 2:
                e0, c0 = info["refs"][0]
                prefs = profile.setdefault("preferences", [])
                if not any(p.get("type") == c0.get("type")
                           and p.get("value", {}).get("phrase") == c0.get("phrase")
                           for p in prefs):
                    prefs.append({
                        "id": nc_core.new_run_id(),
                        "type": c0.get("type"),
                        "value": {k: v for k, v in c0.items()
                                  if k not in ("_event", "candidate_id", "status")},
                        "scope": {"language": profile.get("language", "zh"),
                                  "source_event": e0.get("event_id")},
                        "status": "active",
                        "evidence": len(info["notes"]),
                        "auto_confirmed": True,
                        "created_at": now_iso(),
                    })
                    print("[AUTO] 证据达标（%d 篇独立笔记），已自动生效：%s"
                          % (len(info["notes"]), c0.get("type")), file=sys.stderr)
    revs = profile.setdefault("revisions", {})
    rel = str(note)
    revs[rel] = {"hash": event["new_hash"],
                 "learned_at": event["at"],
                 "snapshot": None}  # 快照存事件里，避免画像膨胀
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    if args.json:
        print(json.dumps(event, ensure_ascii=False, indent=2))
    else:
        print("[OK] 差异已记录（event: %s）" % event_id)
        for cat, n in sorted(categories.items()):
            print("  %s x%d" % (cat, n))
        for c in pref_candidates:
            print("  [候选] %s：%s" % (c["type"], c["why"]))
        print("  确认：learn_edit.py confirm --profile ... --candidate 编号；"
              "候选不确认不生效。")
    sys.exit(0)


def cmd_confirm(args):
    profile_path, profile = load_profile(args.profile)
    events = profile.get("learning_events", [])
    candidates = []
    for e in events:
        for c in e.get("candidates", []):
            c = dict(c)
            c["_event"] = e["event_id"]
            candidates.append(c)
    matched = None
    for i, c in enumerate(candidates):
        if c.get("candidate_id") == args.candidate or str(i + 1) == args.candidate:
            matched = c
            break
    if matched is None:
        print("[STOP] 没有该候选：%s（先跑 diff，或用 candidates 查看编号）"
              % args.candidate, file=sys.stderr)
        sys.exit(2)
    prefs = profile.setdefault("preferences", [])
    pref = {
        "id": nc_core.new_run_id(),
        "type": matched["type"],
        "value": {k: v for k, v in matched.items()
                  if k not in ("_event", "candidate_id")},
        "scope": {"language": profile.get("language", "zh"),
                  "source_event": matched["_event"]},
        "status": "active",
        "evidence": 1,
        "created_at": now_iso(),
    }
    prefs.append(pref)
    profile["preferences"] = prefs[-100:]
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print("[OK] 偏好已生效：%s（%s）" % (pref["id"], pref["type"]))
    sys.exit(0)


def cmd_reject(args):
    profile_path, profile = load_profile(args.profile)
    active_events = {p.get("scope", {}).get("source_event")
                     for p in profile.get("preferences", [])}
    for e in profile.get("learning_events", []):
        for c in e.get("candidates", []):
            if c.get("candidate_id") != args.candidate:
                continue
            if e.get("event_id") in active_events:
                print("[STOP] 该候选已确认生效；请先撤销学习事件 %s，再拒绝候选。"
                      % e["event_id"], file=sys.stderr)
                sys.exit(2)
            c["status"] = "rejected"
            c["reject_reason"] = args.reason or ""
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print("[OK] 候选已拒绝：%s" % args.candidate)
            sys.exit(0)
    print("[STOP] 没有该候选：%s" % args.candidate, file=sys.stderr)
    sys.exit(2)


def cmd_undo(args):
    profile_path, profile = load_profile(args.profile)
    events = profile.get("learning_events", [])
    target = None
    for e in events:
        if e.get("event_id") == args.event:
            target = e
            break
    if target is None:
        print("[STOP] 没有该学习事件：%s" % args.event, file=sys.stderr)
        sys.exit(2)
    if target.get("undone"):
        print("[STOP] 该事件已撤销过（幂等无操作）。", file=sys.stderr)
        sys.exit(2)
    target["undone"] = True
    for c in target.get("candidates", []):
        c["status"] = "undone"
    profile["preferences"] = [p for p in profile.get("preferences", [])
                              if p.get("scope", {}).get("source_event") != args.event]
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print("[OK] 已撤销学习事件 %s：候选与派生偏好一并移除（差异记录保留）。"
          % args.event)
    sys.exit(0)


def cmd_candidates(args):
    _, profile = load_profile(args.profile)
    rows = []
    for e in profile.get("learning_events", []):
        for i, c in enumerate(e.get("candidates", []), 1):
            c.setdefault("candidate_id", "%s#%d" % (e["event_id"], i))
            rows.append({"candidate_id": c["candidate_id"],  # 已在 diff 时存储
                         "event": e["event_id"],
                         "type": c["type"], "why": c.get("why", ""),
                         "status": c.get("status", "candidate"),
                         "undone": bool(e.get("undone"))})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print("%s  [%s] %s — %s" % (r["candidate_id"], r["status"],
                                        r["type"], r["why"]))
        if not rows:
            print("（暂无候选）")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="改稿差异分类与偏好候选（B05）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("diff", help="对比基线与当前改稿，记录差异与候选")
    p1.add_argument("--profile", required=True)
    p1.add_argument("--note", required=True)
    p1.add_argument("--baseline-run", help="指定生成基线 run_id（默认用上次修订快照）")
    p1.add_argument("--json", action="store_true")

    p2 = sub.add_parser("confirm", help="确认候选为生效偏好")
    p2.add_argument("--profile", required=True)
    p2.add_argument("--candidate", required=True, help="候选编号（candidates 查询）")

    p3 = sub.add_parser("reject", help="拒绝候选")
    p3.add_argument("--profile", required=True)
    p3.add_argument("--candidate", required=True)
    p3.add_argument("--reason", help="拒绝原因（可选）")

    p4 = sub.add_parser("undo", help="撤销一次学习事件")
    p4.add_argument("--profile", required=True)
    p4.add_argument("--event", required=True, help="event_id")

    p5 = sub.add_parser("candidates", help="查看候选清单")
    p5.add_argument("--profile", required=True)
    p5.add_argument("--json", action="store_true")

    args = ap.parse_args()
    {"diff": cmd_diff, "confirm": cmd_confirm, "reject": cmd_reject,
     "undo": cmd_undo, "candidates": cmd_candidates}[args.cmd](args)


if __name__ == "__main__":
    main()
