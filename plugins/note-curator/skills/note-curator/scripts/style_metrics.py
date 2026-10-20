#!/usr/bin/env python3
"""
style_metrics.py — note-curator 文风统计与比较的调度层。

职责：
- Markdown 清洗、段落切分、排版统计等语言无关逻辑
- 按语言选择语言包（style_lang_zh / style_lang_en）并调用其特征实现
- 语料画像（analyze_corpus）、人可读摘要（profile_to_markdown）
- 草稿与画像的比较（compare_profiles），只在同语言之间比较

语言包接口见 style_lang_zh.py / style_lang_en.py 顶部说明。
只依赖 Python 标准库。
"""

import datetime
import re

import style_lang_en
import style_lang_zh
from langdetect import (detect_language, detect_language_detail,  # noqa: F401
                        CJK_RE, LATIN_RE, MIN_CHARS, ZH_THRESHOLD)
from style_util import per_1000, percentile, stats  # noqa: F401  共享数学工具

PACKS = {"zh": style_lang_zh, "en": style_lang_en}

FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n.*?\n---\s*\n?", re.DOTALL)
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL_RE = re.compile(r"https?://\S+")
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
HTML_TAG_RE = re.compile(r"<[^>]+>")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*$", re.MULTILINE)
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?", re.MULTILINE)
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*\[[ xX]\]\s*", re.MULTILINE)

# 每种语言的展示文案：摘要标题、findings 分类、结论档位
LABELS = {
    "zh": {
        "report_title": "文风统计画像",
        "report_note": "这是确定性统计结果。语气、态度、用词偏好等定性部分，"
                       "请 Agent 阅读 samples 和原文后写入同目录的 `voice.md`。",
        "corpus": "语料", "files": "样本文件", "chars": "正文规模",
        "samples": "取样片段", "sentence": "句长与段落", "punct": "标点（每千字）",
        "voice": "人称与语气", "fragments": "高频片段", "starters": "句首习惯",
        "rhetoric": "修辞与结构", "formatting": "排版", "sample_section": "样本片段",
        "unit": "字", "none_usage": "样本中未出现明显用法",
        "insufficient": "样本不足",
        "cat": {"sentence": "句长", "paragraph": "段落", "punct": "标点",
                "pronoun": "人称", "particle": "语气词", "hedge": "模糊限定",
                "booster": "强调词", "connector": "连接词", "rhetoric": "修辞",
                "lexical": "用词", "formatting": "排版", "starter": "句首",
                "constructions": "句式", "colloquial": "口语词",
                "four_char": "四字格", "ai": "AI 腔", "latin": "中英混排"},
        "verdict": {"ok": "基本一致", "minor": "轻微偏差", "major": "明显偏差",
                    "mismatch": "语言不一致"},
    },
    "en": {
        "report_title": "Voice profile (statistics)",
        "report_note": "Deterministic statistics. Tone, attitude, and wording preferences "
                       "should be written by the agent into `voice.md` after reading samples.",
        "corpus": "Corpus", "files": "sample files", "chars": "body size",
        "samples": "sampled passages", "sentence": "Sentence and paragraph length",
        "punct": "Punctuation (per 1,000 units)", "voice": "Pronouns and tone",
        "fragments": "Frequent phrases", "starters": "Sentence openers",
        "rhetoric": "Rhetoric and structure", "formatting": "Formatting",
        "sample_section": "Sample passages",
        "unit": "words", "none_usage": "no notable usage in samples",
        "insufficient": "not enough samples",
        "cat": {"sentence": "sentence length", "paragraph": "paragraph",
                "punct": "punctuation", "pronoun": "pronouns",
                "particle": "tone particles", "hedge": "hedges",
                "booster": "boosters", "connector": "connectors",
                "rhetoric": "rhetoric", "lexical": "vocabulary",
                "formatting": "formatting", "starter": "opener",
                "constructions": "constructions", "colloquial": "colloquialisms",
                "four_char": "four-char phrases", "ai": "AI tells",
                "latin": "Latin mixing"},
        "verdict": {"ok": "consistent", "minor": "minor deviation",
                    "major": "major deviation", "mismatch": "language mismatch"},
    },
}


def get_pack(lang):
    pack = PACKS.get(lang)
    if pack is None:
        raise ValueError("unsupported language: %r (expected zh/en)" % lang)
    return pack


# ---------- 语言无关的 Markdown 清洗 ----------

def clean_markdown(text):
    """去掉 frontmatter、代码、链接和 Markdown 标记，只留适合统计的正文。"""
    text = HTML_COMMENT_RE.sub("", text)
    text = FRONTMATTER_RE.sub("", text)
    text = CODE_BLOCK_RE.sub("\n\n", text)
    text = INLINE_CODE_RE.sub("", text)
    text = IMAGE_RE.sub("", text)
    text = LINK_RE.sub(r"\1", text)
    text = URL_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    text = TABLE_SEP_RE.sub("", text)
    text = HEADING_RE.sub("", text)
    text = BLOCKQUOTE_RE.sub("", text)
    text = LIST_RE.sub("", text)
    text = CHECKBOX_RE.sub("", text)
    text = text.replace("|", " ")
    text = re.sub(r"[*_~=`]{1,3}", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---------- 通用统计工具（实现在 style_util.py） ----------

def _count_pattern(text, pattern, size, flags):
    count = len(re.findall(pattern, text, flags))
    return {"count": count, "per_1000": per_1000(count, size)}


def count_patterns(text, patterns, size, flags=0):
    return {name: _count_pattern(text, pattern, size, flags)
            for name, pattern in patterns.items()}


def count_terms(text, terms, size, pack=None):
    """词条统计：带 pack 时按其 REGEX_TERMS 决定词边界或字面，无 pack 按字面。"""
    regex = bool(pack is not None and getattr(pack, "REGEX_TERMS", False))
    flags = getattr(pack, "PATTERN_FLAGS", 0) if pack is not None else 0
    result = {}
    for term in terms:
        if regex:
            pattern = r"\b" + re.escape(term) + r"\b"
            item = _count_pattern(text, pattern, size, flags)
        else:
            count = text.count(term)
            item = {"count": count, "per_1000": per_1000(count, size)}
        result[term] = item
    return result


# ---------- 排版统计（语言无关，键为中性 id） ----------

def formatting_features(raw_text):
    text = HTML_COMMENT_RE.sub("", raw_text)
    text = FRONTMATTER_RE.sub("", text)
    heading_levels = {}
    for level in range(1, 7):
        marker = "#" * level
        count = len(re.findall(r"^%s\s+\S" % re.escape(marker), text, re.MULTILINE))
        if count:
            heading_levels["H%d" % level] = count
    counts = {
        "heading": sum(heading_levels.values()),
        "bullet_list": len(re.findall(r"^\s*[-*+]\s+", text, re.MULTILINE)),
        "ordered_list": len(re.findall(r"^\s*\d+\.\s+", text, re.MULTILINE)),
        "bold": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "italic": len(re.findall(r"(?<!\*)\*[^*]+\*(?!\*)", text)),
        "highlight": len(re.findall(r"==[^=]+==", text)),
        "quote": len(re.findall(r"^\s*>\s?", text, re.MULTILINE)),
        "table_row": len(re.findall(r"^\s*\|.*\|\s*$", text, re.MULTILINE)),
        "code_block": len(re.findall(r"```", text)) // 2,
        "wikilink": len(re.findall(r"\[\[[^\]]+\]\]", text)),
        "inline_code": len(re.findall(r"`[^`\n]+`", text)),
    }
    main_heading = max(heading_levels, key=heading_levels.get) if heading_levels else "none"
    return {"heading_levels": heading_levels, "main_heading_level": main_heading,
            "counts": counts}


# ---------- 单篇分析 ----------

def analyze_text(raw_text, lang=None, formatting_text=None):
    """统计一篇/一段合并文本。lang 为 None 时自动检测。"""
    text = clean_markdown(raw_text)
    if lang is None:
        lang = detect_language(text)
    pack = get_pack(lang)

    sentences = pack.split_sentences(text)
    paragraphs = split_paragraphs(text)
    size = pack.corpus_size(text)
    sentence_lengths = [pack.unit_len(s) for s in sentences]
    paragraph_lengths = [pack.unit_len(p) for p in paragraphs]

    punctuation = count_patterns(text, pack.PUNCTUATION_PATTERNS, size, pack.PATTERN_FLAGS)
    pronouns = count_patterns(text, pack.PRONOUN_PATTERNS, size, pack.PATTERN_FLAGS)
    particles = count_terms(text, pack.PARTICLES, size, pack)
    hedges = count_terms(text, pack.HEDGES, size, pack)
    boosters = count_terms(text, pack.BOOSTERS, size, pack)
    connectors = count_terms(text, pack.CONNECTORS, size, pack)
    rhetoric = count_patterns(text, pack.RHETORIC_PATTERNS, size, pack.PATTERN_FLAGS)

    return {
        "language": lang,
        "unit": pack.UNIT,
        "chars": size,  # 兼容字段：语言对应的计量规模（zh=字数，en=词数）
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "sentence_length": stats(sentence_lengths),
        "paragraph_length": stats(paragraph_lengths),
        "punctuation": punctuation,
        "pronouns": pronouns,
        "particles": particles,
        "hedges": hedges,
        "boosters": boosters,
        "connectors": connectors,
        "rhetoric": rhetoric,
        "question_count": punctuation.get(pack.QUESTION_KEY, {}).get("count", 0),
        "exclamation_count": punctuation.get(pack.EXCLAMATION_KEY, {}).get("count", 0),
        "sentence_starters": pack.starters(sentences),
        "ngrams": pack.top_fragments(text),
        "lexical": pack.lexical(text),
        "formatting": formatting_features(formatting_text if formatting_text is not None else raw_text),
        **pack.metrics_extras(text, size),
    }


# ---------- 语料画像 ----------

def _para_is_compatible(para, lang):
    """段级语言相容判定；过短段落（und）不剔除。"""
    cjk = len(CJK_RE.findall(para))
    latin = len(LATIN_RE.findall(para))
    total = cjk + latin
    if total < MIN_CHARS:
        return True
    detected = "zh" if cjk / total >= ZH_THRESHOLD else "en"
    return detected == lang


def analyze_corpus(files, max_samples=5, lang="auto"):
    """files: [Path]；lang: auto/zh/en。返回可序列化的画像字典。

    B02 语言口径（G02）：
    - 语言按文件判定（清洗后），auto 取有效文件多数；
    - 强制语言表示**筛选与验证**：不匹配的文件剔除并记录在
      language_scope.files_excluded，不再强行按该语言统计；
    - 命中文件里与画像语言不同的段落（如长英文引语段）剔除出正文统计；
      代码、行内代码、链接与 URL 在 clean_markdown 已剔除。
    """
    entries = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        detail = detect_language_detail(clean_markdown(raw))
        entries.append({"path": path, "raw": raw, "primary": detail["primary"]})

    forced = lang in ("zh", "en")
    if not forced:
        counted = [e for e in entries if e["primary"] in ("zh", "en")]
        if counted:
            zh_n = sum(1 for e in counted if e["primary"] == "zh")
            lang = "zh" if zh_n * 2 >= len(counted) else "en"
        else:
            lang = "zh"  # 全部 und：跟随默认，段级过滤不会误删
    excluded = []
    und_followed = 0
    used = []
    for e in entries:
        if e["primary"] == "und":
            used.append(e)
            und_followed += 1
        elif e["primary"] == lang:
            used.append(e)
        else:
            excluded.append({"path": str(e["path"]), "detected": e["primary"]})

    raw_texts = []
    samples = []
    dropped_segments = 0
    for e in used:
        clean = clean_markdown(e["raw"])
        paras = [p for p in split_paragraphs(clean) if p.strip()]
        kept = [p for p in paras if _para_is_compatible(p, lang)]
        dropped_segments += len(paras) - len(kept)
        raw_texts.append("\n\n".join(kept))
        if len(samples) < max_samples:
            for para in kept:
                if 80 <= len(para) <= 320:
                    samples.append({"source": str(e["path"]), "text": para})
                    break

    combined_raw = "\n\n".join(e["raw"] for e in used)
    combined_clean = "\n\n".join(raw_texts)
    metrics = analyze_text(combined_clean, lang=lang, formatting_text=combined_raw)
    return {
        "profile_version": 3,
        "language": lang,
        "unit": metrics["unit"],
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus": {
            "file_count": len(raw_texts),
            "total_chars": metrics["chars"],
        },
        "metrics": metrics,
        "samples": samples,
        "language_scope": {
            "forced": forced,
            "files_used": len(used),
            "files_excluded": excluded,
            "und_followed_profile": und_followed,
            "segments_dropped": dropped_segments,
        },
    }


# ---------- 人可读摘要 ----------

def _fmt(value):
    if isinstance(value, float):
        return ("%.2f" % value).rstrip("0").rstrip(".")
    return str(value)


def _top_terms(term_dict, limit=8):
    items = [(name, data["count"], data["per_1000"])
             for name, data in term_dict.items() if data["count"] > 0]
    items.sort(key=lambda item: item[1], reverse=True)
    return items[:limit]


def profile_to_markdown(profile):
    lang = profile.get("language", "zh")
    labels = LABELS[lang]
    cat = labels["cat"]
    pack = get_pack(lang)
    metrics = profile["metrics"]
    sl = metrics["sentence_length"]
    pl = metrics["paragraph_length"]
    unit = labels["unit"]
    lines = []
    lines.append("# %s" % labels["report_title"])
    lines.append("")
    lines.append("> %s" % labels["report_note"])
    lines.append("")
    lines.append("## %s" % labels["corpus"])
    lines.append("- %s: %d" % (labels["files"], profile["corpus"]["file_count"]))
    lines.append("- %s: %d %s" % (labels["chars"], profile["corpus"]["total_chars"], unit))
    if profile.get("samples"):
        lines.append("- %s: %d" % (labels["samples"], len(profile["samples"])))
    lines.append("")
    lines.append("## %s" % labels["sentence"])
    lines.append("- %s: %s / %s / %s / %s / %s" % (
        labels["cat"]["sentence"], _fmt(sl["mean"]), _fmt(sl["median"]),
        _fmt(sl["p25"]), _fmt(sl["p75"]), _fmt(sl["std"])))
    lines.append("- range: %s-%s %s, n=%d" % (_fmt(sl["min"]), _fmt(sl["max"]), unit, sl["count"]))
    lines.append("- %s: %s / %s / %s, n=%d" % (
        labels["cat"]["paragraph"], _fmt(pl["mean"]), _fmt(pl["median"]),
        _fmt(pl["p75"]), pl["count"]))
    lines.append("")
    lines.append("## %s" % labels["punct"])
    for name, data in metrics["punctuation"].items():
        lines.append("- %s: %d (%s)" % (name, data["count"], _fmt(data["per_1000"])))
    lines.append("")
    lines.append("## %s" % labels["voice"])
    groups = [(labels["cat"]["pronoun"], metrics["pronouns"]),
              (labels["cat"]["particle"], metrics["particles"]),
              (labels["cat"]["hedge"], metrics["hedges"]),
              (labels["cat"]["booster"], metrics["boosters"]),
              (labels["cat"]["connector"], metrics["connectors"])]
    for label, data in groups:
        items = _top_terms(data)
        if items:
            lines.append("- %s: %s" % (label, "、".join(
                "%s(%d)" % (name, count) for name, count, _ in items)))
        else:
            lines.append("- %s: %s" % (label, labels["none_usage"]))
    lines.append("")
    lines.append("## %s" % labels["fragments"])
    if metrics["ngrams"]:
        lines.append("- " + "、".join("%s(%d)" % (gram, count)
                                     for gram, count in metrics["ngrams"][:15]))
    else:
        lines.append("- %s" % labels["insufficient"])
    lines.append("")
    lines.append("## %s" % labels["starters"])
    if metrics["sentence_starters"]:
        lines.append("- " + "、".join("%s(%d)" % (starter, count)
                                     for starter, count in metrics["sentence_starters"][:12]))
    else:
        lines.append("- %s" % labels["insufficient"])
    lines.append("")
    lines.append("## %s" % labels["rhetoric"])
    for name, data in metrics["rhetoric"].items():
        lines.append("- %s: %d" % (name, data["count"]))
    lines.append("- Q: %d / !: %d" % (metrics["question_count"], metrics["exclamation_count"]))
    lines.append("")

    # ---- 中文深化特征（仅 zh 画像有）----
    if "zh_constructions" in metrics:
        lines.append("## %s" % cat.get("constructions", "句式"))
        for name, data in metrics["zh_constructions"].items():
            lines.append("- %s: %d (%s)" % (name, data["count"], _fmt(data["per_1000"])))
        four = metrics.get("zh_four_char", {})
        lines.append("- %s: %d (%s)" % (cat.get("four_char", "四字格"),
                                        four.get("count", 0), _fmt(four.get("per_1000", 0))))
        lines.append("")
        lines.append("## %s" % cat.get("colloquial", "口语词"))
        items = _top_terms(metrics["zh_colloquial"])
        if items:
            lines.append("- " + "、".join("%s(%d)" % (name, count) for name, count, _ in items))
        else:
            lines.append("- %s" % labels["none_usage"])
        lines.append("")
        ai_items = _top_terms(metrics["ai_tells"])
        lines.append("## %s" % cat.get("ai", "AI 腔"))
        if ai_items:
            lines.append("- " + "、".join("%s(%d)" % (name, count) for name, count, _ in ai_items)
                         + ("（画像语料本身含有这些句式，写作时应避免再新增）"))
        else:
            lines.append("- 语料中未出现 AI 腔黑名单句式" if lang == "zh"
                         else "no AI tells in samples")
        lines.append("")
        lines.append("## %s" % cat.get("latin", "中英混排"))
        lines.append("- 英文词密度: %s / 千字" % _fmt(metrics.get("latin_per_1000", 0)))
        lines.append("")
    lines.append("## %s" % labels["formatting"])
    formatting = metrics["formatting"]
    lines.append("- main heading: %s" % formatting["main_heading_level"])
    fmt_labels = pack.FMT_LABELS
    for name, count in formatting["counts"].items():
        if count:
            lines.append("- %s: %d" % (fmt_labels.get(name, name), count))
    lines.append("")
    if profile.get("samples"):
        lines.append("## %s" % labels["sample_section"])
        for sample in profile["samples"]:
            lines.append("")
            lines.append("source: `%s`" % sample["source"])
            lines.append("")
            lines.append("> " + sample["text"].replace("\n", " "))
    lines.append("")
    return "\n".join(lines)


# ---------- 草稿与画像比较 ----------

def _add(findings, category, severity, message, expected, actual):
    findings.append({
        "category": category,
        "severity": severity,
        "message": message,
        "expected": expected,
        "actual": actual,
    })


def _ratio_severity(expected, actual):
    if expected > 0:
        ratio = actual / expected
        if 0.75 <= ratio <= 1.33:
            return None
    # 低频特征缺失不一定是文风问题；只在草稿明显多用了它时提示。
    if expected < 2.0:
        if actual >= 5:
            return "major"
        if actual >= 2:
            return "minor"
        return None
    ratio = actual / expected
    if ratio >= 3 or ratio <= 0.33:
        return "major"
    if ratio >= 2 or ratio <= 0.5:
        return "minor"
    return None


def compare_profiles(profile, draft):
    """把草稿统计与画像比较。语言不一致时直接给出 mismatch 结论。"""
    profile_lang = profile.get("language", "zh")
    draft_lang = draft.get("language", "zh")
    labels = LABELS[profile_lang]
    cat = labels["cat"]

    if profile_lang != draft_lang:
        findings = [{
            "category": cat["lexical"],
            "severity": "major",
            "message": "profile is %s but draft is %s; rebuild the profile for this language"
                       % (profile_lang, draft_lang)
                       if profile_lang == "en" else
                       "画像是 %s，草稿是 %s；请为该语言单独建立画像" % (profile_lang, draft_lang),
            "expected": profile_lang,
            "actual": draft_lang,
        }]
        return {"verdict": labels["verdict"]["mismatch"],
                "counts": {"major": 1, "minor": 0, "info": 0},
                "findings": findings}

    expected = profile["metrics"]
    findings = []
    is_en = profile_lang == "en"

    def unit_of(value):
        return "%s %s" % (_fmt(value), labels["unit"])

    for key in ("mean", "median", "p75"):
        label = cat["sentence"] + " " + key
        exp = expected["sentence_length"][key]
        act = draft["sentence_length"][key]
        if key == "mean" and expected["sentence_length"]["std"] > 0:
            z = abs(act - exp) / expected["sentence_length"]["std"]
            if z >= 2.5:
                _add(findings, cat["sentence"], "major",
                     "%s: %s, profile %s±%s" % (label, unit_of(act), unit_of(exp),
                                                _fmt(expected["sentence_length"]["std"])),
                     exp, act)
            elif z >= 1.5:
                _add(findings, cat["sentence"], "minor",
                     "%s: %s, profile %s±%s" % (label, unit_of(act), unit_of(exp),
                                                _fmt(expected["sentence_length"]["std"])),
                     exp, act)
        elif exp > 0:
            severity = _ratio_severity(exp, act)
            if severity:
                _add(findings, cat["sentence"], severity,
                     "%s: %s, profile %s" % (label, unit_of(act), unit_of(exp)),
                     exp, act)

    exp_pl = expected["paragraph_length"]["mean"]
    act_pl = draft["paragraph_length"]["mean"]
    if exp_pl > 0:
        severity = _ratio_severity(exp_pl, act_pl)
        if severity:
            _add(findings, cat["paragraph"], severity,
                 "%s mean: %s, profile %s" % (cat["paragraph"], unit_of(act_pl), unit_of(exp_pl)),
                 exp_pl, act_pl)

    for name, data in expected["punctuation"].items():
        exp = data.get("per_1000", 0)
        act = draft["punctuation"].get(name, {}).get("per_1000", 0)
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, cat["punct"], severity,
                 "%s: %s, profile %s" % (name, _fmt(act), _fmt(exp)),
                 exp, act)

    for label, key in [(cat["pronoun"], "pronouns"), (cat["particle"], "particles"),
                       (cat["hedge"], "hedges"), (cat["booster"], "boosters"),
                       (cat["connector"], "connectors")]:
        exp = sum(item["per_1000"] for item in expected[key].values())
        act = sum(item["per_1000"] for item in draft[key].values())
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, label, severity,
                 "%s: %s, profile %s" % (label, _fmt(act), _fmt(exp)),
                 round(exp, 2), round(act, 2))

    for name, data in expected["rhetoric"].items():
        exp = data.get("per_1000", 0)
        act = draft["rhetoric"].get(name, {}).get("per_1000", 0)
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, cat["rhetoric"], severity,
                 "%s: %s, profile %s" % (name, _fmt(act), _fmt(exp)),
                 exp, act)

    # ---- 中文深化特征（仅当画像与草稿都带这些字段时比较）----
    for group_key, label_key in (("zh_constructions", "constructions"),
                                 ("zh_colloquial", "colloquial")):
        if group_key not in expected or group_key not in draft:
            continue
        exp = sum(item["per_1000"] for item in expected[group_key].values())
        act = sum(item["per_1000"] for item in draft[group_key].values())
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, cat[label_key], severity,
                 "%s: %s, profile %s" % (cat[label_key], _fmt(act), _fmt(exp)),
                 round(exp, 2), round(act, 2))

    if "zh_four_char" in expected and "zh_four_char" in draft:
        exp = expected["zh_four_char"]["per_1000"]
        act = draft["zh_four_char"]["per_1000"]
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, cat["four_char"], severity,
                 "%s: %s, profile %s" % (cat["four_char"], _fmt(act), _fmt(exp)),
                 exp, act)

    if "ai_tells" in expected and "ai_tells" in draft:
        for name, data in expected["ai_tells"].items():
            exp_count = data.get("count", 0)
            act_data = draft["ai_tells"].get(name, {})
            act_count = act_data.get("count", 0)
            if act_count == 0:
                continue
            if exp_count == 0:
                # 画像里从不出现的 AI 腔，草稿里出现即偏差；多次出现按 major
                severity = "major" if act_count >= 2 else "minor"
            else:
                severity = _ratio_severity(data.get("per_1000", 0),
                                           act_data.get("per_1000", 0))
                if severity is None and act_count > exp_count:
                    severity = "minor"
            if severity:
                _add(findings, cat["ai"], severity,
                     "%s: draft %d, profile %d" % (name, act_count, exp_count),
                     exp_count, act_count)

    if "latin_per_1000" in expected and "latin_per_1000" in draft:
        exp = expected["latin_per_1000"]
        act = draft["latin_per_1000"]
        # 画像本身几乎不用英文术语时不比（中文全文名词写法同样成立）
        if exp >= 5:
            severity = _ratio_severity(exp, act)
            if severity:
                _add(findings, cat["latin"], severity,
                     "%s: %s, profile %s" % (cat["latin"], _fmt(act), _fmt(exp)),
                     exp, act)

    exp_ttr = expected["lexical"]["type_token_ratio"]
    act_ttr = draft["lexical"]["type_token_ratio"]
    if exp_ttr > 0 and abs(act_ttr - exp_ttr) >= 0.12:
        _add(findings, cat["lexical"], "minor",
             "%s TTR: %s, profile %s" % (cat["lexical"], _fmt(act_ttr), _fmt(exp_ttr)),
             exp_ttr, act_ttr)

    fmt_labels = get_pack(profile_lang).FMT_LABELS
    for name in expected["formatting"]["counts"]:
        exp = expected["formatting"]["counts"].get(name, 0) / max(expected["chars"], 1) * 1000
        act = draft["formatting"]["counts"].get(name, 0) / max(draft["chars"], 1) * 1000
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, cat["formatting"], severity,
                 "%s: %s, profile %s" % (fmt_labels.get(name, name), _fmt(act), _fmt(exp)),
                 round(exp, 2), round(act, 2))

    expected_starters = {item[0] for item in expected["sentence_starters"][:6]}
    actual_starters = {item[0] for item in draft["sentence_starters"][:6]}
    if expected_starters and actual_starters and not (expected_starters & actual_starters):
        _add(findings, cat["starter"], "info",
             "openers share nothing with the profile; fine when topics differ" if is_en
             else "句首习惯与画像没有重合；如果内容主题差异较大，可以忽略",
             0, 0)

    major = sum(1 for item in findings if item["severity"] == "major")
    minor = sum(1 for item in findings if item["severity"] == "minor")
    if major >= 3:
        verdict = labels["verdict"]["major"]
    elif major >= 1 or minor >= 3:
        verdict = labels["verdict"]["minor"]
    else:
        verdict = labels["verdict"]["ok"]
    severity_order = {"major": 0, "minor": 1, "info": 2}
    findings.sort(key=lambda item: severity_order.get(item["severity"], 3))
    return {
        "verdict": verdict,
        "counts": {"major": major, "minor": minor, "info": len(findings) - major - minor},
        "findings": findings,
    }
