#!/usr/bin/env python3
"""style_util.py — 文风统计的共享数学工具（语言无关）。"""

import math
import statistics


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * p
    low = int(math.floor(k))
    high = int(math.ceil(k))
    if low == high:
        return float(sorted_values[int(k)])
    return float(sorted_values[low] * (high - k) + sorted_values[high] * (k - low))


def stats(values):
    """均值/中位数/四分位/标准差；空列表返回全 0。"""
    values = [float(v) for v in values if v is not None]
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p25": 0.0,
                "p75": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "p25": round(percentile(ordered, 0.25), 2),
        "p75": round(percentile(ordered, 0.75), 2),
        "std": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def per_1000(count, units):
    """每千单位的频率；units 为 0 时返回 0。"""
    return round(count / units * 1000, 2) if units else 0.0
