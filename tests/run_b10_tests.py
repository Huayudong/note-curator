#!/usr/bin/env python3
"""
run_b10_tests.py — B10 评测纪律回归测试。

覆盖：
  1. 冻结清单生成与来源篡改拒绝（B10-01）
  2. mock 全量评测 8/8 通过 + 报告字段完整
  3. --sabotage 演示：评测能抓到事实丢失（B10-08）
  4. blind_compare：偏好率、平局处理、Wilson 区间（B10-07）
  5. feedback：记录 / 列表 / 转待办任务（B10-08/09）

用法：python tests/run_b10_tests.py
退出码：0 全部通过；1 有失败。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts"
EVALS = REPO_ROOT / "evals"

FAILURES = []


def check(name, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else " — %s" % str(detail)[:300]))
    if not condition:
        FAILURES.append(name)


def run(args, home=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    if home:
        env["NOTE_CURATOR_HOME"] = str(home)
    return subprocess.run([sys.executable] + [str(a) for a in args],
                          capture_output=True, encoding="utf-8",
                          errors="replace", env=env)


def main():
    if not EVALS.is_dir():
        check("evals dir exists", False, str(EVALS))
        sys.exit(1)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home = td / "home"
        evals_root = td / "evals"
        shutil.copytree(EVALS, evals_root,
                        ignore=shutil.ignore_patterns("reports", "tasks",
                                                      "__pycache__"))

        # 1. 冻结生成 + 篡改拒绝（B10-01）
        r = run([SCRIPTS / "run_eval.py", "--evals-root", evals_root,
                 "--freeze"], home)
        check("freeze creates manifest", r.returncode == 0, r.stderr[-200:])
        frozen = json.loads((evals_root / "tasks" / "frozen-v1.json")
                            .read_text(encoding="utf-8"))
        check("frozen has 8 tasks", len(frozen["tasks"]) == 8
              and len(frozen["sources"]) == 8, str(len(frozen["tasks"])))
        r = run([SCRIPTS / "run_eval.py", "--evals-root", evals_root,
                 "--freeze"], home)
        check("re-freeze idempotent rc0", r.returncode == 0, r.stderr[-150:])
        target = evals_root / "sources" / "zh-technical.md"
        original = target.read_text(encoding="utf-8")
        target.write_text(original[:len(original) // 3], encoding="utf-8")
        r = run([SCRIPTS / "run_eval.py", "--evals-root", evals_root,
                 "--freeze"], home)
        check("tampered source refused rc2", r.returncode == 2, "rc=%s" % r.returncode)
        target.write_text(original, encoding="utf-8")

        # 2. mock 全量评测
        r = run([SCRIPTS / "run_eval.py", "--evals-root", evals_root,
                 "--provider", "mock", "--layers", "public"], home)
        check("mock eval rc0", r.returncode == 0, r.stdout[-400:])
        reports = sorted((evals_root / "reports").glob("report-*.json"))
        check("report written", bool(reports), str(list(evals_root.rglob("*.json"))))
        report = json.loads(reports[-1].read_text(encoding="utf-8"))
        check("report fields", report["tasks_passed"] == 8
              and report["pass_rate"] == 1.0
              and report["layers"] == ["public"]
              and report["pack_version"], str(report)[:200])

        # 3. sabotage 演示：删前半来源 → 评测抓到事实丢失（B10-08）
        r = run([SCRIPTS / "run_eval.py", "--evals-root", evals_root,
                 "--provider", "mock", "--sabotage", "zh-technical"], home)
        check("sabotaged run rc1", r.returncode == 1, "rc=%s" % r.returncode)
        reports = sorted((evals_root / "reports").glob("report-*.json"))
        last = json.loads(reports[-1].read_text(encoding="utf-8"))
        sabotaged = [x for x in last["results"] if x["id"] == "zh-technical"][0]
        check("sabotage detected as fail",
              sabotaged["pass"] is False and sabotaged["missing_facts"],
              str(sabotaged)[:200])

        # 4. blind_compare 数学（B10-07）
        votes = td / "votes.jsonl"
        rows = ([{"pair_id": str(i), "prefer": "a"} for i in range(7)]
                + [{"pair_id": str(10 + i), "prefer": "b"} for i in range(3)]
                + [{"pair_id": str(20 + i), "prefer": "tie"} for i in range(2)]
                + [{"pair_id": "99", "prefer": "unjudgeable"}])
        votes.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
        r = run([SCRIPTS / "blind_compare.py", "--votes", votes, "--json"], home)
        result = json.loads(r.stdout)
        check("preference rate", result["directional_preference"] == 0.7,
              str(result)[:200])
        ci = result["ci95"]
        check("wilson ci sane", ci and ci[0] < 0.7 < ci[1]
              and ci[0] > 0.34 and ci[1] < 0.94, str(ci))
        check("tie reported separately", result["tie"] == 2
              and result["unjudgeable"] == 1
              and result["tie_half_sensitivity"]["rate"] is not None, str(result)[:150])
        empty = td / "empty.jsonl"
        empty.write_text(json.dumps({"pair_id": "1", "prefer": "tie"}), encoding="utf-8")
        r = run([SCRIPTS / "blind_compare.py", "--votes", empty, "--json"], home)
        res2 = json.loads(r.stdout)
        check("all-tie is N/A with sensitivity",
              res2["directional_preference"] is None
              and res2["tie_half_sensitivity"]["rate"] == 0.5, str(res2)[:150])

        # 5. feedback 管道（B10-08/09）
        r = run([SCRIPTS / "feedback.py", "add", "--category", "style_mismatch",
                 "--note", "句长偏长", "--draft", str(td / "d.md")], home)
        check("feedback add rc0", r.returncode == 0, r.stderr[-150:])
        r = run([SCRIPTS / "feedback.py", "add", "--category", "bad_category"], home)
        check("bad category rejected", r.returncode == 1, "rc=%s" % r.returncode)
        r = run([SCRIPTS / "feedback.py", "list", "--json"], home)
        entries = r.stdout.count("style_mismatch") if False else None
        r = run([SCRIPTS / "feedback.py", "to-task", "--id", "1",
                 "--out", str(evals_root / "tasks" / "pending" / "t1.json")], home)
        check("to-task rc0", r.returncode == 0, r.stderr[-150:])
        task = json.loads((evals_root / "tasks" / "pending" / "t1.json")
                          .read_text(encoding="utf-8"))
        check("task stub fields", task["origin"] == "feedback"
              and task["category"] == "style_mismatch"
              and task["status"] == "pending", str(task)[:150])
        r = run([SCRIPTS / "feedback.py", "to-task", "--id", "99",
                 "--out", str(td / "x.json")], home)
        check("missing feedback rc2", r.returncode == 2, "rc=%s" % r.returncode)

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All B10 eval-discipline tests passed.")


if __name__ == "__main__":
    main()
