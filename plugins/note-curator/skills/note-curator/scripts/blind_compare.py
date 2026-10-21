#!/usr/bin/env python3
"""
blind_compare.py — B10-07 盲评计票：方向偏好率 + Wilson 95% 置信区间。

输入 votes.jsonl（每行一项任务投票，标签已匿名）：
    {"pair_id": "t1", "prefer": "a|b|tie|unjudgeable"}

口径（方案 §9.4）：
  - 有效方向偏好率 = A 胜出数 / (A 胜出数 + B 胜出数)；平局不计入分母，
    但必须另报 tie 数与 unjudgeable 数，不得静默删除。
  - 全为平局时偏好率为 N/A，同时报告「平局各计半票」的敏感性结果。
  - 95% CI 用 Wilson 区间（按独立题近似；同一用户/来源多题需另行聚类，
    本工具在报告里明确提示该限制）。
  - >60% 仅作为进入扩大试用的探索门槛，不构成对外宣称改善的证据。

用法：python blind_compare.py --votes votes.jsonl [--json]
退出码：0 有效结果；2 无有效投票。
"""

import argparse
import json
import math
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

Z95 = 1.959963984540054


def wilson(successes, n, z=Z95):
    """Wilson 单比例 95% 区间；n=0 返回 None。"""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"rate": round(p, 4),
            "ci95": [round(max(center - half, 0.0), 4),
                     round(min(center + half, 1.0), 4)]}


def count_votes(votes_path):
    counts = {"a": 0, "b": 0, "tie": 0, "unjudgeable": 0}
    invalid = 0
    with open(votes_path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                vote = json.loads(line)
            except ValueError:
                invalid += 1
                continue
            prefer = str(vote.get("prefer", "")).lower()
            if prefer in counts:
                counts[prefer] += 1
            else:
                invalid += 1
    return counts, invalid


def analyze(counts):
    a, b = counts["a"], counts["b"]
    valid = a + b
    result = {
        "a_wins": a, "b_wins": b, "tie": counts["tie"],
        "unjudgeable": counts["unjudgeable"],
        "valid_directional": valid,
        "note": ">60% 仅为探索门槛；CI 覆盖 50% 或样本不足时不能宣称改善；"
                "同一用户/来源多题需聚类自助法，本区间按独立题近似。",
    }
    if valid == 0:
        result["directional_preference"] = None
        result["ci95"] = None
        total = counts["tie"] * 0.5 + a
        result["tie_half_sensitivity"] = {
            "rate": round(total / (valid + counts["tie"]), 4)
            if (valid + counts["tie"]) else None,
        }
    else:
        ci = wilson(a, valid)
        result["directional_preference"] = ci["rate"]
        result["ci95"] = ci["ci95"]
        half_total = a + counts["tie"] * 0.5
        result["tie_half_sensitivity"] = {
            "rate": round(half_total / (valid + counts["tie"]), 4),
        }
    return result


def main():
    ap = argparse.ArgumentParser(description="盲评计票")
    ap.add_argument("--votes", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not Path(args.votes).is_file():
        print("[ERROR] 投票文件不存在: %s" % args.votes, file=sys.stderr)
        sys.exit(1)
    counts, invalid = count_votes(args.votes)
    result = analyze(counts)
    result["invalid_lines"] = invalid
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("A 胜 %d / B 胜 %d / 平局 %d / 无法判断 %d（无效行 %d）"
              % (counts["a"], counts["b"], counts["tie"],
                 counts["unjudgeable"], invalid))
        if result["directional_preference"] is None:
            print("有效方向偏好率：N/A（无有效方向投票）")
        else:
            print("有效方向偏好率：%.1f%%（Wilson 95%% CI %s）"
                  % (result["directional_preference"] * 100,
                     result["ci95"]))
        print("敏感性（平局各计半票）：", result["tie_half_sensitivity"]["rate"])
    sys.exit(0 if (counts["a"] + counts["b"]) > 0 else 2)


if __name__ == "__main__":
    main()
