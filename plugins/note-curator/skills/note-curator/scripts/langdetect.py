#!/usr/bin/env python3
"""
langdetect.py — note-curator 的轻量语言检测（B02 升级）。

只区分中文（zh）、英文（en）与 undetermined（und）：
  - detect_language(text)：整篇多数判定（兼容旧调用；空文本默认 zh）。
  - detect_language_detail(text)：清洗后按段识别，返回主语言与分段结果。
    代码块、行内代码、图片、链接 URL 与 Markdown 标记先剔除，不参与判定；
    有效字母类字符不足 MIN_CHARS 的文本/段落返回 und，不强行判断。
零依赖、确定性、可复现。
"""

import re

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

# CJK 占字母类字符的比例达到该值即判定为中文。
# 中文技术笔记常夹带英文术语（10%–40% 拉丁字母），阈值取 0.2 足够宽容。
ZH_THRESHOLD = 0.2

# 有效字符低于该值时不判定（B02-03）：短标题、一句话草稿允许 undetermined。
MIN_CHARS = 20

CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|!\[\[[^\]]*\]\]")
LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")
URL_RE = re.compile(r"https?://\S+")
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
WIKILINK_RE = re.compile(r"\[\[[^\]]*\]\]")


def strip_non_style(text):
    """去掉不适合做语言/风格样本的内容：代码、图片、链接、URL、HTML 注释。"""
    text = HTML_COMMENT_RE.sub("", text)
    text = CODE_BLOCK_RE.sub("\n\n", text)
    text = INLINE_CODE_RE.sub("", text)
    text = IMAGE_RE.sub("", text)
    text = LINK_RE.sub(" ", text)
    text = WIKILINK_RE.sub(" ", text)
    text = URL_RE.sub("", text)
    return text


def cjk_ratio(text):
    """CJK 字符占（CJK + 拉丁字母）的比例；无字母类字符时返回 0。"""
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    total = cjk + latin
    return cjk / total if total else 0.0


def _ratio_to_lang(cjk, latin):
    total = cjk + latin
    if total < MIN_CHARS:
        return "und"
    return "zh" if cjk / total >= ZH_THRESHOLD else "en"


def detect_language(text):
    """返回 "zh" / "en"。兼容入口：沿用历史语义，不做最短长度判定
    （undetermined 只出现在 detect_language_detail；空文本默认 zh）。"""
    if not text or not text.strip():
        return "zh"
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    total = cjk + latin
    if total == 0:
        return "zh"
    return "zh" if cjk / total >= ZH_THRESHOLD else "en"


def detect_language_detail(text):
    """按段识别。返回 {"primary", "segments", "zh_chars", "latin_chars"}。

    段落为剔除代码/引用后的非空段落；每段独立判定，短段落记 und。
    主语言按全部有效字符的比例判定，不足 MIN_CHARS 记 und。
    """
    cleaned = strip_non_style(text)
    segments = []
    zh = latin = 0
    for para in re.split(r"\n\s*\n", cleaned):
        para = para.strip()
        if not para:
            continue
        c = len(CJK_RE.findall(para))
        l = len(LATIN_RE.findall(para))
        segments.append({"lang": _ratio_to_lang(c, l), "zh_chars": c,
                         "latin_chars": l})
        zh += c
        latin += l
    total = zh + latin
    if total == 0:
        primary = "zh" if not text.strip() else "und"
    else:
        primary = _ratio_to_lang(zh, latin)
    return {"primary": primary, "segments": segments,
            "zh_chars": zh, "latin_chars": latin}
