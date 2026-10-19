#!/usr/bin/env python3
"""
style_lang_zh.py — 中文语言包：style_metrics 的中文特征实现。

只包含中文专属的数据与统计逻辑；语言无关的调度在 style_metrics.py。
被借鉴的英文方法论（write-like-me）见 references/style-profiling.md。
"""

import re
from collections import Counter

LANG = "zh"
UNIT = "字"

# 正则类统计是否忽略大小写（中文不需要）
PATTERN_FLAGS = 0
# 词条统计是否走正则词边界（中文按字面 count 即可）
REGEX_TERMS = False

QUESTION_KEY = "问号"
EXCLAMATION_KEY = "感叹号"

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|(?<=……)\s*|(?<=[.!?])(?=\s)|\n+")

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

STOP_CHARS = set("的了是在和与也就都而及或着过吗呢吧啊呀哦嗯哈啦我你他她它这那有没不一个们")

# 展示用的排版标签（键为内部中性 id，见 style_metrics.formatting_features）
FMT_LABELS = {
    "heading": "标题",
    "bullet_list": "无序列表",
    "ordered_list": "有序列表",
    "bold": "加粗",
    "italic": "斜体",
    "highlight": "高亮",
    "quote": "引用块",
    "table_row": "表格行",
    "code_block": "代码块",
    "wikilink": "双链",
    "inline_code": "行内代码",
}


def char_len(text):
    return len(re.sub(r"\s+", "", text))


def split_sentences(text):
    """按中英文句末标点和换行切句，过滤过短碎片。"""
    parts = SENTENCE_SPLIT_RE.split(text)
    out = []
    for part in parts:
        part = part.strip().strip("“”\"'「」『』（）()【】[]，,。！？!?：:；; ")
        if len(re.sub(r"\s+", "", part)) >= 2:
            out.append(part)
    return out


def unit_len(text):
    """句长/段长的计量单位：中文用非空白字符数。"""
    return char_len(text)


def corpus_size(text):
    """密度分母：中文按千字。"""
    return char_len(text)


def top_fragments(text, top=20):
    """字符 n-gram（2–4）统计高频片段；无分词依赖时的近似。"""
    runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text)
    counter = Counter()
    for run in runs:
        if not re.search(r"[\u4e00-\u9fff]", run):
            continue
        for n in range(2, 5):
            for i in range(len(run) - n + 1):
                gram = run[i:i + n]
                if all(ch in STOP_CHARS for ch in gram):
                    continue
                counter[gram] += 1
    items = [(gram, count) for gram, count in counter.most_common(top * 3) if count >= 2][:top]
    if not items:
        items = counter.most_common(top)
    return items


def starters(sentences, top=12):
    """句首习惯：取前 4 个字符。"""
    counter = Counter()
    for sentence in sentences:
        sentence = sentence.strip("“”\"'「」『』（）()【】[]，,。！？!?：:；; ")
        if len(sentence) >= 2:
            counter[sentence[:4]] += 1
    return counter.most_common(top)


def lexical(text):
    """词汇丰富度：中文按字符 TTR。"""
    compact = re.sub(r"\s+", "", text)
    chars = len(compact)
    unique = len(set(compact))
    counter = Counter(compact)
    hapax = sum(1 for count in counter.values() if count == 1)
    return {
        "size": chars,
        "unique": unique,
        "type_token_ratio": round(unique / chars, 4) if chars else 0.0,
        "hapax_ratio": round(hapax / unique, 4) if unique else 0.0,
    }
