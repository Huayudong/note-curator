#!/usr/bin/env python3
"""
run_eval.py — B10 冻结评测执行器。

纪律（方案 §9、B10-01/06/07/08/10）：
  - 冻结集物理隔离：任务定义在 evals/tasks/frozen-v1.json，来源在
    evals/sources/；首跑 --freeze 生成清单并记录来源 sha256，此后
    来源变更会被**拒绝**（冻结不可事后修改）。
  - 报告可复现：记录核心版本/语言包版本/提供者/上下文层/逐任务明细，
    写入 evals/reports/。
  - 消融：--layers 控制 public / +profile / +prefs 三档（与
    model_generate 的层机制一致），逐档出报告。
  - --sabotage <task_id>：故意删减来源前半，用于验证评测确实能抓到
    事实丢失（B10-08 缺陷→回归的管道演示）。

本脚本只做确定性打分（事实保留/尾部清单/篇幅）；「自然度/像本人」的
盲评见 blind_compare.py，由人工投票驱动。评测不改变任何默认策略；
新策略成为默认必须先有报告与硬约束通过（B10-10）。

用法：
    python run_eval.py --freeze                     # 首次冻结
    python run_eval.py --provider mock --layers public
    python run_eval.py --provider mock --sabotage zh-technical
退出码：0 全部通过；1 有任务未过；2 冻结校验失败/参数错误。
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

# 评测集在仓库根 evals/（与开发夹具物理隔离，B10-01）
EVALS_ROOT = Path(os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "evals")))
FROZEN = "frozen-v1.json"
TASKS = [
    {"id": "zh-technical", "source": "zh-technical.md", "lang": "zh",
     "register": "technical"},
    {"id": "zh-reading", "source": "zh-reading.md", "lang": "zh",
     "register": "reading"},
    {"id": "zh-experiment", "source": "zh-experiment.md", "lang": "zh",
     "register": "experiment"},
    {"id": "zh-retrospective", "source": "zh-retrospective.md", "lang": "zh",
     "register": "retrospective"},
    {"id": "en-technical", "source": "en-technical.md", "lang": "en",
     "register": "technical"},
    {"id": "en-reading", "source": "en-reading.md", "lang": "en",
     "register": "reading"},
    {"id": "en-experiment", "source": "en-experiment.md", "lang": "en",
     "register": "experiment"},
    {"id": "en-retrospective", "source": "en-retrospective.md", "lang": "en",
     "register": "retrospective"},
]


def sha256_file(path):
    """Hash normalized UTF-8 content (newline-insensitive, B10-01)."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    text = text.replace(chr(13) + chr(10), chr(10))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_frozen(evals_root):
    return json.loads((evals_root / "tasks" / FROZEN).read_text(encoding="utf-8"))


def freeze(evals_root):
    """生成/校验冻结清单。已存在且哈希一致 → 视为已冻结。"""
    tasks_dir = evals_root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    frozen_path = tasks_dir / FROZEN
    manifest = {
        "schema": 1,
        "frozen_at": nc_core.now_iso(),
        "tasks": TASKS,
        "sources": {},
    }
    for task in TASKS:
        p = evals_root / "sources" / task["source"]
        if not p.is_file():
            print("[ERROR] 来源缺失: %s" % p, file=sys.stderr)
            sys.exit(2)
        manifest["sources"][task["source"]] = sha256_file(p)
    if frozen_path.exists():
        current = json.loads(frozen_path.read_text(encoding="utf-8"))
        if current.get("sources") == manifest["sources"]:
            print("[OK] 冻结集校验通过（%d 个任务，来源未变）。" % len(TASKS))
            sys.exit(0)
        print("[STOP] 来源与冻结清单不一致：冻结集不可修改。", file=sys.stderr)
        sys.exit(2)
    frozen_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("[OK] 已冻结 %d 个任务 -> %s" % (len(TASKS), frozen_path))
    sys.exit(0)


def verify_frozen(evals_root):
    frozen = load_frozen(evals_root)
    for rel, digest in frozen.get("sources", {}).items():
        p = evals_root / "sources" / rel
        if not p.is_file() or sha256_file(p) != digest:
            print("[STOP] 来源与冻结清单不一致：%s（冻结集不可修改）" % rel,
                  file=sys.stderr)
            sys.exit(2)
    return frozen


def sabotage_text(text):
    """B10-08 演示：删掉来源前半（模拟截断来源），评测应能抓到事实丢失。"""
    cut = max(len(text) // 2, 1)
    return text[cut:]


def run_task(task, evals_root, args, tmp_dir):
    from model_generate import (BUDGET, LAYERS)
    source_path = evals_root / "sources" / task["source"]
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    if args.sabotage == task["id"]:
        text = sabotage_text(text)
    draft_path = tmp_dir / (task["id"] + ".md")
    gen = nc_core and None
    gen_args = [str(Path(__file__).resolve().parent / "model_generate.py"),
                "--source-file", source_path if args.sabotage != task["id"]
                else str(_write_temp(tmp_dir, task["id"] + "-sab.py-source", text)),
                "--register", task["register"], "--lang", task["lang"],
                "--title", task["id"],
                "--layers", args.layers,
                "--out", str(draft_path),
                "--provider", args.provider, "--json"]
    if args.provider == "api":
        gen_args += ["--base-url", args.base_url, "--model", args.model]
    r = subprocess_run(gen_args)
    if r.returncode != 0:
        return {"id": task["id"], "pass": False,
                "error": "generate failed: " + r.stderr[-160:]}
    fact_args = [str(Path(__file__).resolve().parent / "fact_check.py"),
                 "--source", str(source_path), "--draft", str(draft_path),
                 "--lang", task["lang"], "--json"]
    f = subprocess_run(fact_args)
    fact = json.loads(f.stdout)
    missing = [m["text"] for m in fact["retention"]["missing"]]
    passed = (fact["retention"]["facts_missing"] == 0
              and fact["tail_violation"] is None
              and not fact["budget"]["needs_split_review"])
    return {
        "id": task["id"],
        "pass": passed,
        "facts_total": fact["retention"]["facts_total"],
        "missing_facts": missing,
        "retention_ratio": fact["retention"]["retention_ratio"],
        "tail_violation": bool(fact["tail_violation"]),
        "needs_split_review": fact["budget"]["needs_split_review"],
        "draft_chars": fact["budget"]["size"],
        "draft": str(draft_path),
    }


def _write_temp(tmp_dir, name, text):
    p = Path(tmp_dir) / (name + ".md")
    p.write_text(text, encoding="utf-8")
    return p


def subprocess_run(args):
    import subprocess
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    return subprocess.run([sys.executable] + args, capture_output=True,
                          encoding="utf-8", errors="replace", env=env)


def main():
    ap = argparse.ArgumentParser(description="冻结评测执行器（B10）")
    ap.add_argument("--provider", choices=["mock", "api"], default="mock")
    ap.add_argument("--layers", default="public,profile,prefs")
    ap.add_argument("--base-url", default=os.environ.get("NC_LLM_BASE_URL", ""))
    ap.add_argument("--model", default=os.environ.get("NC_LLM_MODEL", ""))
    ap.add_argument("--evals-root", help="评测根目录（默认仓库 evals/）")
    ap.add_argument("--freeze", action="store_true",
                    help="生成/校验冻结清单（不跑任务）")
    ap.add_argument("--sabotage", help="指定任务 id 演示缺陷捕获")
    ap.add_argument("--report", help="报告输出路径（默认 evals/reports/）")
    args = ap.parse_args()

    evals_root = Path(args.evals_root).resolve() if args.evals_root else EVALS_ROOT
    if not evals_root.is_dir():
        print("[ERROR] 评测根目录不存在: %s" % evals_root, file=sys.stderr)
        sys.exit(2)
    if args.freeze:
        freeze(evals_root)
        return

    frozen = verify_frozen(evals_root)
    import datetime
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_dir = evals_root / "reports" / ("tmp-" + run_id)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    from resource_pack import load_pack
    pack, _ = load_pack("zh")
    results = []
    for task in frozen["tasks"]:
        results.append(run_task(task, evals_root, args, tmp_dir))
        print("[TASK] %s -> %s" % (task["id"],
                                   "PASS" if results[-1]["pass"] else "FAIL"))
    passed = sum(1 for r in results if r["pass"])
    ratios = [r["retention_ratio"] for r in results
              if r.get("retention_ratio") is not None]
    report = {
        "schema": 1,
        "run_id": run_id,
        "provider": args.provider,
        "layers": [l for l in args.layers.split(",") if l in ("public", "profile", "prefs")],
        "pack_version": (pack or {}).get("pack_version"),
        "tasks_passed": passed,
        "tasks_total": len(results),
        "pass_rate": round(passed / len(results), 4) if results else None,
        "mean_retention": round(sum(ratios) / len(ratios), 4) if ratios else None,
        "frozen_manifest": str(evals_root / "tasks" / FROZEN),
        "results": results,
    }
    reports_dir = evals_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.report) if args.report else reports_dir / ("report-%s.json" % run_id)
    nc_core.atomic_write_text(out, json.dumps(report, ensure_ascii=False, indent=2))
    md_path = out.with_suffix(".md")
    lines = ["# 评测报告 %s" % run_id, "",
             "- provider: %s  layers: %s  pack: %s"
             % (args.provider, ",".join(report["layers"]),
                report["pack_version"]),
             "- 通过：%d/%d，平均事实保留率：%s" % (passed, len(results),
                                              report["mean_retention"]), ""]
    for r in results:
        lines.append("- %s %s（缺失事实：%s）"
                     % ("PASS" if r["pass"] else "FAIL", r["id"],
                        "、".join(r.get("missing_facts", [])) or "无"))
    nc_core.atomic_write_text(str(md_path), "\n".join(lines) + "\n")
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("[OK] 报告 -> %s（%d/%d 通过）" % (out, passed, len(results)))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
