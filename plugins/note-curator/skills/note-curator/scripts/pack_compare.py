#!/usr/bin/env python3
"""
pack_compare.py — B12-06 语言包本地对比：新旧两包在样例草稿上的效果差异。

方法：对 old/new 两个包根（各自含 zh-CN/ 或 en/ 完整包目录），分别以
python -c 运行 style_check——在子进程 import 之前设置 NOTE_CURATOR_PACK_ROOT，
保证加载的是目标包；对同一样例草稿 + 同一画像各跑一次，按类别汇总
findings 数量差异。只做本地对比，不改变默认包。

用法：
    python pack_compare.py --old old-root --new new-root \
        --profile profile.json --samples "samples/*.md" [--json]

退出码：0 有对比结果；2 参数错误。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

LANG_DIRS = {"zh-CN": "zh", "en": "en"}


def check_pack_at(root):
    """确认 root/<langDir>/pack.json 存在，返回目录名。"""
    for d in LANG_DIRS:
        if (Path(root) / d / "pack.json").is_file():
            return d
    return None


def findings_for(root, profile, draft):
    """在指定包根下运行 style_check，返回 findings 计数。"""
    style_check = str(Path(__file__).resolve().parent / "style_check.py")
    runner = (
        "import os, sys\n"
        "os.environ['NOTE_CURATOR_PACK_ROOT'] = " + repr(str(root)) + "\n"
        "sys.path.insert(0, " + repr(str(Path(__file__).resolve().parent)) + ")\n"
        "sys.argv = ['style_check.py', " + repr(str(draft)) + ", "
        "'--profile', " + repr(str(profile)) + ", '--json']\n"
        "code = " + repr(Path(style_check).read_text(encoding="utf-8")) + "\n"
        "exec(compile(code, 'style_check.py', 'exec'))\n"
    )
    r = subprocess.run([sys.executable, "-c", runner],
                       capture_output=True, encoding="utf-8", errors="replace")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {"error": (r.stderr or r.stdout)[-300:]}
    counts = {}
    for f in data.get("findings", []):
        key = f["category"] + "/" + f["severity"]
        counts[key] = counts.get(key, 0) + 1
    return {"verdict": data.get("verdict"), "counts": counts}


def main():
    ap = argparse.ArgumentParser(description="语言包新旧对比（B12-06）")
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--profile", required=True, help="profile.json")
    ap.add_argument("--samples", required=True, help="样例草稿 glob")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sample_path = Path(args.samples).absolute()
    samples = sorted(sample_path.parent.glob(sample_path.name))
    if not samples:
        print("[ERROR] 没有样例草稿：%s" % args.samples, file=sys.stderr)
        sys.exit(2)
    old_dir = check_pack_at(args.old)
    new_dir = check_pack_at(args.new)
    if not old_dir or not new_dir or old_dir != new_dir:
        print("[ERROR] 两个包根需包含同一语言的完整包目录（zh-CN/ 或 en/）",
              file=sys.stderr)
        sys.exit(2)

    results = []
    for sample in samples:
        old_res = findings_for(args.old, args.profile, sample)
        new_res = findings_for(args.new, args.profile, sample)
        keys = sorted(set(old_res.get("counts", {}))
                      | set(new_res.get("counts", {})))
        delta = {}
        for key in keys:
            a = old_res.get("counts", {}).get(key, 0)
            b = new_res.get("counts", {}).get(key, 0)
            if a != b:
                delta[key] = {"old": a, "new": b}
        results.append({
            "sample": sample.name,
            "old_verdict": old_res.get("verdict"),
            "new_verdict": new_res.get("verdict"),
            "findings_delta": delta,
            "error": old_res.get("error") or new_res.get("error"),
        })

    summary = {"samples": len(results),
               "changed": sum(1 for r in results if r["findings_delta"]),
               "results": results}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print("%s：old=%s new=%s" % (r["sample"], r["old_verdict"],
                                         r["new_verdict"]))
            for key, d in r["findings_delta"].items():
                print("   %s：%d -> %d" % (key, d["old"], d["new"]))
        print("[OK] %d 个样例中 %d 个有差异。" % (summary["samples"],
                                                 summary["changed"]))
    sys.exit(0)


if __name__ == "__main__":
    main()
