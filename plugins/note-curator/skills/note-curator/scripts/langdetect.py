#!/usr/bin/env python3
"""
langdetect.py — note-curator 的轻量语言检测。

只区分中文（zh）与英文（en），基于 CJK 字符与拉丁字母的数量比例：
零依赖、确定性、可复现。混合文本按多数判定，调用方可以显式覆盖。
"""

import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

# CJK 占字母类字符的比例达到该值即判定为中文。
# 中文技术笔记常夹带英文术语（10%–40% 拉丁字母），阈值取 0.2 足够宽容。
ZH_THRESHOLD = 0.2


def cjk_ratio(text: str) -> float:
    """CJK 字符占（CJK + 拉丁字母）的比例；无字母类字符时返回 0。"""
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    total = cjk + latin
    return cjk / total if total else 0.0


def detect_language(text: str) -> str:
    """返回 "zh" 或 "en"。空文本默认 zh（本 skill 的原生语言）。"""
    if not text or not text.strip():
        return "zh"
    return "zh" if cjk_ratio(text) >= ZH_THRESHOLD else "en"
