#!/usr/bin/env python3
"""
style_metrics.py — note-curator 的中文文风统计与比较工具（共享实现）。

只做确定性的文本统计，不调用模型：
- 句长、段落长度分布
- 标点使用频率
- 人称、语气词、模糊限定词、强调词、连接词
- 句首习惯、高频字词片段
- 修辞标记（举例、类比、枚举、个人经验、转折）
- Markdown 排版特征

style_profile.py 用它建立画像，style_check.py 用它比较草稿和画像。
只依赖 Python 标准库。
"""

import datetime
import math
import re
import statistics
from collections import Counter

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
SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[。！？!?])\s*|(?<=……)\s*|(?<=[.!?])(?=\s)|\n+"
)

PRONOUN_PATTERNS = {
    "我": r"我(?!们)",
    "我们": r"我们",
    "你": r"你(?!们)",
    "你们": r"你们",
    "他": r"他(?!们)",
    "她": r"她(?!们)",
    "它": r"它(?!们)",
    "他们": r"他们",
    "她们": r"她们",
    "它们": r"它们",
    "大家": r"大家",
    "自己": r"自己",
}

PARTICLES = ["吧", "呢", "啊", "嘛", "呀", "哦", "嗯", "哈", "啦"]
HEDGES = ["可能", "也许", "大概", "或许", "似乎", "看起来", "应该", "差不多",
          "某种程度上", "不一定", "未必", "估计"]
BOOSTERS = ["一定", "肯定", "确实", "明显", "显然", "绝对", "非常", "特别",
             "尤其", "必须", "毫无疑问", "无疑"]
CONNECTORS = ["但是", "不过", "然而", "所以", "因此", "因为", "其实", "说白了",
              "换句话说", "也就是说", "另外", "此外", "总之", "反正", "于是", "然后"]

RHETORIC_PATTERNS = {
    "举例": r"比如|例如|举个例子|譬如|像是",
    "类比": r"就像|好比|相当于|类似于|如同|宛如",
    "枚举": r"首先|其次|最后|第一|第二|第三|一方面|另一方面",
    "个人经验": r"我以前|有一次|我自己|我遇到|我见过|在我看来|我的经验",
    "转折": r"但是|不过|然而|其实|话说回来",
}

PUNCTUATION_PATTERNS = {
    "逗号": r"[，,]",
    "句号": r"[。]",
    "问号": r"[？?]",
    "感叹号": r"[！!]",
    "冒号": r"[：:]",
    "分号": r"[；;]",
    "破折号": r"——|—|--",
    "省略号": r"……|\.\.\.",
    "括号": r"[（）()]",
    "引号": r"[“”\"「」『』]",
    "书名号": r"[《》]",
}

STOP_CHARS = set("的了是在和与也就都而及或着过吗呢吧啊呀哦嗯哈啦我你他她它这那有没不一个们")


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


def split_sentences(text):
    """按中英文句末标点和换行切句，过滤过短碎片。"""
    parts = SENTENCE_SPLIT_RE.split(text)
    out = []
    for part in parts:
        part = part.strip().strip("“”\"'「」『』（）()【】[]，,。！？!?：:；; ")
        if len(re.sub(r"\s+", "", part)) >= 2:
            out.append(part)
    return out


def char_len(text):
    return len(re.sub(r"\s+", "", text))


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


def per_1000(count, chars):
    return round(count / chars * 1000, 2) if chars else 0.0


def count_patterns(text, patterns, chars=None):
    chars = char_len(text) if chars is None else chars
    result = {}
    for name, pattern in patterns.items():
        count = len(re.findall(pattern, text))
        result[name] = {"count": count, "per_1000": per_1000(count, chars)}
    return result


def count_terms(text, terms, chars=None):
    chars = char_len(text) if chars is None else chars
    result = {}
    for term in terms:
        count = text.count(term)
        result[term] = {"count": count, "per_1000": per_1000(count, chars)}
    return result


def top_ngrams(text, n_min=2, n_max=4, top=20):
    """按字符 n-gram 统计高频片段；中文没有分词依赖时，这是可用的近似。"""
    runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text)
    counter = Counter()
    for run in runs:
        if not re.search(r"[\u4e00-\u9fff]", run):
            continue
        for n in range(n_min, n_max + 1):
            for i in range(len(run) - n + 1):
                gram = run[i:i + n]
                if all(ch in STOP_CHARS for ch in gram):
                    continue
                counter[gram] += 1
    items = [(gram, count) for gram, count in counter.most_common(top * 3) if count >= 2][:top]
    if not items:
        items = counter.most_common(top)
    return items


def sentence_starters(sentences, top=12):
    counter = Counter()
    for sentence in sentences:
        sentence = sentence.strip("“”\"'「」『』（）()【】[]，,。！？!?：:；; ")
        if len(sentence) >= 2:
            counter[sentence[:4]] += 1
    return counter.most_common(top)


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
        "标题": sum(heading_levels.values()),
        "无序列表": len(re.findall(r"^\s*[-*+]\s+", text, re.MULTILINE)),
        "有序列表": len(re.findall(r"^\s*\d+\.\s+", text, re.MULTILINE)),
        "加粗": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "斜体": len(re.findall(r"(?<!\*)\*[^*]+\*(?!\*)", text)),
        "高亮": len(re.findall(r"==[^=]+==", text)),
        "引用块": len(re.findall(r"^\s*>\s?", text, re.MULTILINE)),
        "表格行": len(re.findall(r"^\s*\|.*\|\s*$", text, re.MULTILINE)),
        "代码块": len(re.findall(r"```", text)) // 2,
        "双链": len(re.findall(r"\[\[[^\]]+\]\]", text)),
        "行内代码": len(re.findall(r"`[^`\n]+`", text)),
    }
    main_heading = max(heading_levels, key=heading_levels.get) if heading_levels else "无"
    return {
        "heading_levels": heading_levels,
        "main_heading_level": main_heading,
        "counts": counts,
    }


def analyze_text(raw_text, formatting_text=None):
    text = clean_markdown(raw_text)
    sentences = split_sentences(text)
    paragraphs = split_paragraphs(text)
    chars = char_len(text)
    sentence_lengths = [char_len(s) for s in sentences]
    paragraph_lengths = [char_len(p) for p in paragraphs]

    punctuation = count_patterns(text, PUNCTUATION_PATTERNS, chars)
    pronouns = count_patterns(text, PRONOUN_PATTERNS, chars)
    particles = count_terms(text, PARTICLES, chars)
    hedges = count_terms(text, HEDGES, chars)
    boosters = count_terms(text, BOOSTERS, chars)
    connectors = count_terms(text, CONNECTORS, chars)
    rhetoric = count_patterns(text, RHETORIC_PATTERNS, chars)

    unique_chars = len(set(re.sub(r"\s+", "", text)))
    char_counts = Counter(re.sub(r"\s+", "", text))
    hapax = sum(1 for count in char_counts.values() if count == 1)
    lexical = {
        "chars": chars,
        "unique_chars": unique_chars,
        "type_token_ratio": round(unique_chars / chars, 4) if chars else 0.0,
        "hapax_ratio": round(hapax / unique_chars, 4) if unique_chars else 0.0,
    }

    return {
        "chars": chars,
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
        "question_count": punctuation["问号"]["count"],
        "exclamation_count": punctuation["感叹号"]["count"],
        "sentence_starters": sentence_starters(sentences),
        "ngrams": top_ngrams(text),
        "lexical": lexical,
        "formatting": formatting_features(formatting_text if formatting_text is not None else raw_text),
    }


def analyze_corpus(files, max_samples=5):
    """files: [Path]；返回可序列化的画像字典。"""
    raw_texts = []
    samples = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        raw_texts.append(raw)
        clean = clean_markdown(raw)
        if len(samples) < max_samples:
            for para in split_paragraphs(clean):
                if 80 <= len(para) <= 320:
                    samples.append({"source": str(path), "text": para})
                    break

    combined_raw = "\n\n".join(raw_texts)
    combined_clean = "\n\n".join(clean_markdown(raw) for raw in raw_texts)
    metrics = analyze_text(combined_clean, formatting_text=combined_raw)
    return {
        "profile_version": 1,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus": {
            "file_count": len(raw_texts),
            "total_chars": metrics["chars"],
        },
        "metrics": metrics,
        "samples": samples,
    }


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
    metrics = profile["metrics"]
    sl = metrics["sentence_length"]
    pl = metrics["paragraph_length"]
    lines = []
    lines.append("# 文风统计画像")
    lines.append("")
    lines.append("> 这是确定性统计结果。语气、态度、用词偏好等定性部分，"
                 "请 Agent 阅读 samples 和原文后写入同目录的 `voice.md`。")
    lines.append("")
    lines.append("## 语料")
    lines.append("- 样本文件：%d 篇" % profile["corpus"]["file_count"])
    lines.append("- 正文规模：%d 字" % profile["corpus"]["total_chars"])
    if profile.get("samples"):
        lines.append("- 取样片段：%d 段" % len(profile["samples"]))
    lines.append("")
    lines.append("## 句长与段落")
    lines.append("- 句长：平均 %s 字，中位数 %s，P25 %s，P75 %s，标准差 %s"
                 % (_fmt(sl["mean"]), _fmt(sl["median"]), _fmt(sl["p25"]),
                    _fmt(sl["p75"]), _fmt(sl["std"])))
    lines.append("- 句长范围：%s–%s 字，共 %d 句"
                 % (_fmt(sl["min"]), _fmt(sl["max"]), sl["count"]))
    lines.append("- 段落：平均 %s 字，中位数 %s，P75 %s，共 %d 段"
                 % (_fmt(pl["mean"]), _fmt(pl["median"]), _fmt(pl["p75"]),
                    pl["count"]))
    lines.append("")
    lines.append("## 标点（每千字）")
    for name, data in metrics["punctuation"].items():
        lines.append("- %s：%d 次（%s‰）" % (name, data["count"], _fmt(data["per_1000"])))
    lines.append("")
    lines.append("## 人称与语气")
    for label, data in [("人称", metrics["pronouns"]),
                        ("语气词", metrics["particles"]),
                        ("模糊限定", metrics["hedges"]),
                        ("强调词", metrics["boosters"]),
                        ("连接词", metrics["connectors"])]:
        items = _top_terms(data)
        if items:
            text = "、".join("%s(%d)" % (name, count) for name, count, _ in items)
            lines.append("- %s：%s" % (label, text))
        else:
            lines.append("- %s：样本中未出现明显用法" % label)
    lines.append("")
    lines.append("## 高频片段（字符 n-gram）")
    if metrics["ngrams"]:
        lines.append("- " + "、".join("%s(%d)" % (gram, count)
                                     for gram, count in metrics["ngrams"][:15]))
    else:
        lines.append("- 样本不足，未提取到重复片段")
    lines.append("")
    lines.append("## 句首习惯")
    if metrics["sentence_starters"]:
        lines.append("- " + "、".join("%s(%d)" % (starter, count)
                                     for starter, count in metrics["sentence_starters"][:12]))
    else:
        lines.append("- 样本不足")
    lines.append("")
    lines.append("## 修辞与结构")
    for name, data in metrics["rhetoric"].items():
        lines.append("- %s：%d 次" % (name, data["count"]))
    lines.append("- 问句：%d 次；感叹句：%d 次"
                 % (metrics["question_count"], metrics["exclamation_count"]))
    lines.append("")
    lines.append("## 排版")
    formatting = metrics["formatting"]
    lines.append("- 主标题层级：%s" % formatting["main_heading_level"])
    for name, count in formatting["counts"].items():
        if count:
            lines.append("- %s：%d" % (name, count))
    lines.append("")
    if profile.get("samples"):
        lines.append("## 样本片段")
        for sample in profile["samples"]:
            lines.append("")
            lines.append("来源：`%s`" % sample["source"])
            lines.append("")
            lines.append("> " + sample["text"].replace("\n", " "))
    lines.append("")
    return "\n".join(lines)


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
        # 小样本下 1 次和 2 次的差异不值得报警；先排除接近值。
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
    """把草稿统计与画像比较，返回 findings 和 verdict。"""
    expected = profile["metrics"]
    findings = []

    for key, label in [("mean", "平均句长"), ("median", "句长中位数"), ("p75", "句长 P75")]:
        exp = expected["sentence_length"][key]
        act = draft["sentence_length"][key]
        if key == "mean" and expected["sentence_length"]["std"] > 0:
            z = abs(act - exp) / expected["sentence_length"]["std"]
            if z >= 2.5:
                _add(findings, "句长", "major",
                     "%s：%s 字，画像为 %s±%s 字（偏差较大）"
                     % (label, _fmt(act), _fmt(exp), _fmt(expected["sentence_length"]["std"])),
                     exp, act)
            elif z >= 1.5:
                _add(findings, "句长", "minor",
                     "%s：%s 字，画像为 %s±%s 字"
                     % (label, _fmt(act), _fmt(exp), _fmt(expected["sentence_length"]["std"])),
                     exp, act)
        elif exp > 0:
            severity = _ratio_severity(exp, act)
            if severity:
                _add(findings, "句长", severity,
                     "%s：%s 字，画像为 %s 字" % (label, _fmt(act), _fmt(exp)),
                     exp, act)

    exp_pl = expected["paragraph_length"]["mean"]
    act_pl = draft["paragraph_length"]["mean"]
    if exp_pl > 0:
        severity = _ratio_severity(exp_pl, act_pl)
        if severity:
            _add(findings, "段落", severity,
                 "平均段落长度为 %s 字，画像为 %s 字" % (_fmt(act_pl), _fmt(exp_pl)),
                 exp_pl, act_pl)

    for name in ["逗号", "句号", "问号", "感叹号", "冒号", "分号", "破折号",
                 "省略号", "括号", "引号"]:
        exp = expected["punctuation"].get(name, {}).get("per_1000", 0)
        act = draft["punctuation"].get(name, {}).get("per_1000", 0)
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, "标点", severity,
                 "%s使用为 %s‰，画像为 %s‰" % (name, _fmt(act), _fmt(exp)),
                 exp, act)

    for label, key in [("人称", "pronouns"), ("语气词", "particles"),
                       ("模糊限定", "hedges"), ("强调词", "boosters"),
                       ("连接词", "connectors")]:
        exp = sum(item["per_1000"] for item in expected[key].values())
        act = sum(item["per_1000"] for item in draft[key].values())
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, label, severity,
                 "%s密度为 %s‰，画像为 %s‰" % (label, _fmt(act), _fmt(exp)),
                 round(exp, 2), round(act, 2))

    for name in ["举例", "类比", "枚举", "个人经验", "转折"]:
        exp = expected["rhetoric"].get(name, {}).get("per_1000", 0)
        act = draft["rhetoric"].get(name, {}).get("per_1000", 0)
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, "修辞", severity,
                 "「%s」密度为 %s‰，画像为 %s‰" % (name, _fmt(act), _fmt(exp)),
                 exp, act)

    exp_ttr = expected["lexical"]["type_token_ratio"]
    act_ttr = draft["lexical"]["type_token_ratio"]
    if exp_ttr > 0 and abs(act_ttr - exp_ttr) >= 0.12:
        _add(findings, "用词", "minor",
             "字符丰富度为 %s，画像为 %s" % (_fmt(act_ttr), _fmt(exp_ttr)),
             exp_ttr, act_ttr)

    for name in ["标题", "无序列表", "有序列表", "加粗", "引用块", "表格行", "双链"]:
        exp = expected["formatting"]["counts"].get(name, 0) / max(expected["chars"], 1) * 1000
        act = draft["formatting"]["counts"].get(name, 0) / max(draft["chars"], 1) * 1000
        severity = _ratio_severity(exp, act)
        if severity:
            _add(findings, "排版", severity,
                 "%s密度为 %s‰，画像为 %s‰" % (name, _fmt(act), _fmt(exp)),
                 round(exp, 2), round(act, 2))

    expected_starters = {item[0] for item in expected["sentence_starters"][:6]}
    actual_starters = {item[0] for item in draft["sentence_starters"][:6]}
    if expected_starters and actual_starters and not (expected_starters & actual_starters):
        _add(findings, "句首", "info",
             "句首习惯与画像没有重合；如果内容主题差异较大，可以忽略", 0, 0)

    major = sum(1 for item in findings if item["severity"] == "major")
    minor = sum(1 for item in findings if item["severity"] == "minor")
    if major >= 3:
        verdict = "明显偏差"
    elif major >= 1 or minor >= 3:
        verdict = "轻微偏差"
    else:
        verdict = "基本一致"
    severity_order = {"major": 0, "minor": 1, "info": 2}
    findings.sort(key=lambda item: severity_order.get(item["severity"], 3))
    return {
        "verdict": verdict,
        "counts": {"major": major, "minor": minor, "info": len(findings) - major - minor},
        "findings": findings,
    }
