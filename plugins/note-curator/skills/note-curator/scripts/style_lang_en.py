#!/usr/bin/env python3
"""
style_lang_en.py — 英文语言包：style_metrics 的英文特征实现。

特征分类参考 write-like-me（lexical / syntactic / hedging & stance / structural），
针对英文笔记重写：句长按词数、词 n-gram、词边界匹配、英文标点与语气词表。
"""

import re
from collections import Counter

LANG = "en"
UNIT = "words"

PATTERN_FLAGS = re.IGNORECASE
# 英文短词（so / but / it）必须按词边界统计，text.count 会误伤别的单词
REGEX_TERMS = True

QUESTION_KEY = "question"
EXCLAMATION_KEY = "exclamation"

PUNCTUATION_PATTERNS = {
    "comma": r",",
    "period": r"\.",
    "question": r"\?",
    "exclamation": r"!",
    "colon": r":",
    "semicolon": r";",
    "dash": r"—|–|--",
    "ellipsis": r"\.\.\.|…",
    "parens": r"[()]",
    "quotes": r"\"|“|”",
}

PRONOUN_PATTERNS = {
    "I": r"\b[Ii]\b",
    "me": r"\bme\b",
    "my": r"\bmy\b",
    "we": r"\bwe\b",
    "us": r"\bus\b",
    "our": r"\bour\b",
    "you": r"\byou\b",
    "he": r"\bhe\b",
    "him": r"\bhim\b",
    "she": r"\bshe\b",
    "her": r"\bher\b",
    "it": r"\bit\b",
    "they": r"\bthey\b",
    "them": r"\bthem\b",
    "their": r"\btheir\b",
}

PARTICLES = []  # 英文没有中文式语气词，这一组在英文画像里恒为空

HEDGES = ["maybe", "perhaps", "possibly", "probably", "roughly", "apparently",
          "seems", "seem", "appears", "appear", "might", "somewhat", "fairly",
          "relatively", "arguably", "presumably", "tend to", "more or less"]

BOOSTERS = ["clearly", "certainly", "definitely", "obviously", "really",
            "very", "extremely", "absolutely", "undoubtedly", "truly",
            "always", "never", "remarkably", "hugely", "massively"]

CONNECTORS = ["however", "but", "therefore", "thus", "because", "although",
              "though", "yet", "actually", "moreover", "furthermore", "instead",
              "meanwhile", "still", "in other words", "that said",
              "for instance", "for example", "on the other hand"]

RHETORIC_PATTERNS = {
    "example": r"\bfor example\b|\bfor instance\b|\bsuch as\b|\be\.g\.|\blike\b",
    "analogy": r"\bimagine\b|\bthink of\b|\bis like\b|\bakin to\b|\bsimilar to\b|\bthink of it as\b",
    "enumeration": r"\bfirst\b|\bsecond\b|\bthird\b|\bfinally\b|\bnext\b|\bon one hand\b|\bon the other hand\b",
    "personal": r"\bin my experience\b|\bi once\b|\bi've\b|\bwhen i\b|\bmy own\b|\bi found\b",
    "transition": r"\bhowever\b|\bbut\b|\balthough\b|\bthough\b|\byet\b|\bactually\b",
}

STOPWORDS = set("""
the a an of to in on is are was were be been being for and with that this these those
it its as by at from or but not no nor so if then than there here what which who whom
you your we our us they them their he she his her me my i
do does did doing have has had having can could will would should may might must
about into over under again further once
very too also just only own same s t don now
""".split())

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")

_ABBR_DOT_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|Fig|No|approx|Inc|Ltd|Co|U\.S|U\.K)\.",
    re.IGNORECASE,
)
_DECIMAL_DOT_RE = re.compile(r"(\d)\.(\d)")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+|\n+")

FMT_LABELS = {
    "heading": "heading",
    "bullet_list": "bullet list",
    "ordered_list": "ordered list",
    "bold": "bold",
    "italic": "italic",
    "highlight": "highlight",
    "quote": "quote",
    "table_row": "table row",
    "code_block": "code block",
    "wikilink": "wikilink",
    "inline_code": "inline code",
}


def words(text):
    return WORD_RE.findall(text)


def split_sentences(text):
    """缩写/小数保护后按句末标点切句；返回原句文本。"""
    protected = _ABBR_DOT_RE.sub(lambda m: m.group(0)[:-1] + "\u2062", text)
    protected = _DECIMAL_DOT_RE.sub(lambda m: m.group(1) + "\u2062" + m.group(2), protected)
    parts = _SENT_SPLIT_RE.split(protected)
    out = []
    for part in parts:
        part = part.replace("\u2062", ".").strip().strip("\"'“”‘’()[] ")
        if len(words(part)) >= 2:
            out.append(part)
    return out


def unit_len(text):
    """句长/段长的计量单位：英文用词数。"""
    return len(words(text))


def corpus_size(text):
    """密度分母：英文按千词。"""
    return len(words(text))


def top_fragments(text, top=20):
    """词 n-gram（1–3）统计高频短语；至少出现 2 次。"""
    tokens = [w.lower() for w in words(text)]
    counter = Counter()
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i:i + n])
            if all(w in STOPWORDS for w in gram):
                continue
            counter[gram] += 1
    phrases = [(g, c) for g, c in counter.most_common(top * 2) if c >= 2][:top]
    if phrases:
        return [(" ".join(g), c) for g, c in phrases]
    # 短语不足时退回高频实词，仍有一定参考价值
    singles = Counter(w for w in tokens if w not in STOPWORDS)
    return singles.most_common(top)


def starters(sentences, top=12):
    """句首习惯：取句首前 3 个词（小写归一）。"""
    counter = Counter()
    for sentence in sentences:
        tokens = [w.lower() for w in words(sentence)[:3]]
        if tokens:
            counter[" ".join(tokens)] += 1
    return counter.most_common(top)


def lexical(text):
    """词汇丰富度：英文按词 TTR。"""
    tokens = [w.lower() for w in words(text)]
    total = len(tokens)
    unique = len(set(tokens))
    counter = Counter(tokens)
    hapax = sum(1 for count in counter.values() if count == 1)
    return {
        "size": total,
        "unique": unique,
        "type_token_ratio": round(unique / total, 4) if total else 0.0,
        "hapax_ratio": round(hapax / unique, 4) if unique else 0.0,
    }


def metrics_extras(text, size):
    """英文暂无深化特征；接口与中文包对齐，返回空。"""
    return {}
