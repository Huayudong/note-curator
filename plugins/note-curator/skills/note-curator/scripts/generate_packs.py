#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_packs.py — 从 style_lang_zh/en 抽取词表，生成 language-packs 首版资源。

只在开发时运行：保证 pack.json 与代码内置词表逐值一致（单一事实源）。
运行：python scripts/generate_packs.py
"""

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import style_lang_en
import style_lang_zh

PACK_ROOT = SCRIPTS.parent / "language-packs"


def zh_rules():
    return [
        {"id": "zh.ai-tell.canned-transitions", "category": "ai_tell",
         "severity": "major", "kind": "deterministic",
         "guidance": "不要用「值得注意的是/综上所述/接下来我们」这类宣布结构的套话；"
                     "过渡句要承接上一句的具体内容。",
         "pattern": style_lang_zh.AI_TELL_PATTERNS["套话提示语"],
         "bad_example": "接下来我们来看看缓存失效的问题。",
         "better_example": "缓存能减少查询，但数据更新后，旧值还可能被继续读取。",
         "exceptions": ["引语", "用户明确保留的讲课口吻"]},
        {"id": "zh.ai-tell.reversal-frame", "category": "ai_tell",
         "severity": "major", "kind": "contextual",
         "guidance": "「不是A而是B」只在澄清真实概念差异时使用；澄清要有具体内容，"
                     "不能只做修辞翻转。",
         "pattern": style_lang_zh.AI_TELL_PATTERNS["翻案腔"],
         "bad_example": "这不是一个技术问题，而是一个认知问题。",
         "better_example": "难点不在工具，而在于团队对数据口径没有达成一致。",
         "exceptions": ["真实概念对比"]},
        {"id": "zh.ai-tell.hollow-booster", "category": "ai_tell",
         "severity": "major", "kind": "deterministic",
         "guidance": "「赋能/抓手/底层逻辑」等空洞强调词不带来信息；判断标准是"
                     "删掉后句子是否丢意思。",
         "pattern": style_lang_zh.AI_TELL_PATTERNS["空洞强调"],
         "bad_example": "该方案极大地赋能了业务底层逻辑。",
         "better_example": "该方案把对账时间从两小时缩短到十分钟。",
         "exceptions": []},
        {"id": "zh.transition.empty-announcement", "category": "transition",
         "severity": "suggestion", "kind": "contextual",
         "guidance": "过渡句应承接具体内容；只宣布下一节的句子可删减。",
         "bad_example": "首先，我们把数据放进缓存。其次，我们设置过期时间。",
         "better_example": "缓存命中后仍需处理过期：设 TTL，并在重建时加锁。",
         "exceptions": ["步骤说明确需序数"]},
        {"id": "zh.modifier.overlong-attributive", "category": "modifier",
         "severity": "suggestion", "kind": "guidance",
         "guidance": "长定语拆成短句：中文倾向「先说主语和动作，再补条件」，"
                     "而不是把大量修饰成分堆在名词前。",
         "bad_example": "这是一个用于解决高并发场景下库存超卖问题的基于 Redis 的分布式锁方案。",
         "better_example": "高并发下库存可能超卖。我们用 Redis 实现分布式锁来解决。",
         "exceptions": ["术语本身较长"]},
        {"id": "zh.subject.clarity", "category": "subject",
         "severity": "suggestion", "kind": "guidance",
         "guidance": "主语省略是中文常态，但连续省略会让指代悬空；换段或换对象时"
                     "把主语补回来。",
         "bad_example": "先配置超时，然后重试三次，还不行就降级，最后报警。",
         "better_example": "客户端先配置超时，失败后重试三次；仍失败则由网关降级并报警。",
         "exceptions": ["步骤清单"]},
        {"id": "zh.term.first-mention", "category": "terminology",
         "severity": "suggestion", "kind": "guidance",
         "guidance": "术语首现用「中文名（英文缩写）」格式，如「检索增强生成（RAG）」；"
                     "之后可只用缩写。用户词表优先于默认写法。",
         "bad_example": "RAG 是一种检索增强生成技术（RAG）。",
         "better_example": "检索增强生成（RAG）先检索再生成；后文简称 RAG。",
         "exceptions": ["通篇只有缩写更自然的场景"]},
        {"id": "zh.register.colloquial-balance", "category": "register",
         "severity": "info", "kind": "guidance",
         "guidance": "口语词（搞定、折腾、靠谱）带人味，但技术解释里密度过高会显得"
                     "轻浮；实验记录与复盘可以更松，知识笔记更收敛。",
         "bad_example": "这个 bug 太折腾了，搞了半天终于搞定了，真的很离谱。",
         "better_example": "这个 bug 折腾了半天：根因是时区，修复只改了一行。",
         "exceptions": ["复盘、随笔等个人文体"]},
    ]


def en_rules():
    return [
        {"id": "en.ai-tell.summary-prelude", "category": "ai_tell",
         "severity": "major", "kind": "deterministic",
         "guidance": "Skip the throat-clearing prelude; lead with the point.",
         "pattern": r"in conclusion|in summary|it is worth noting that|"
                    "it should be noted that|let's dive in|let's take a look",
         "bad_example": "In conclusion, let's take a look at caching.",
         "better_example": "Caching helps until the data changes; then staleness bites.",
         "exceptions": ["formal reports that require a summary section"]},
        {"id": "en.ai-tell.reveal-dash", "category": "ai_tell",
         "severity": "minor", "kind": "contextual",
         "guidance": "The dramatic reveal dash ('X—here's the thing—Y') reads as "
                     "performance; use a colon or a plain sentence.",
         "pattern": r"\w+—but here's the thing—|\bhere's the (?:thing|kicker)\b",
         "bad_example": "The fix was simple—here's the thing—we already had it.",
         "better_example": "The fix was simple: we already had it.",
         "exceptions": ["deliberate voice in personal notes"]},
        {"id": "en.ai-tell.hollow-booster", "category": "ai_tell",
         "severity": "major", "kind": "deterministic",
         "guidance": "Hollow boosters ('hugely', 'massively', 'game-changer') need "
                     "numbers or sources behind them; otherwise delete.",
         "pattern": r"\bhugely\b|\bmassively\b|\bgame-changer\b|\bbest-in-class\b",
         "bad_example": "This massively improves performance.",
         "better_example": "This cuts p99 latency from 800 ms to 300 ms.",
         "exceptions": []},
        {"id": "en.transition.stiff-connectors", "category": "transition",
         "severity": "minor", "kind": "contextual",
         "guidance": "Vary transitions; starting consecutive sentences with "
                     "However/Moreover/Furthermore reads as machine-templated.",
         "bad_example": "However, caches fail. Moreover, locks are slow. "
                        "Furthermore, retries amplify load.",
         "better_example": "Caches fail under writes, and locks make it worse: "
                           "every retry hits the database again.",
         "exceptions": []},
        {"id": "en.noun.nominal-deadweight", "category": "noun",
         "severity": "suggestion", "kind": "guidance",
         "guidance": "Prefer verbs over stacked nominalizations "
                     "('perform the migration of' → 'migrate').",
         "bad_example": "We performed the initialization of the configuration of the cluster.",
         "better_example": "We initialized the cluster configuration.",
         "exceptions": ["established noun forms in API names"]},
        {"id": "en.register.contraction-balance", "category": "register",
         "severity": "info", "kind": "guidance",
         "guidance": "Contractions ('doesn't', 'it's') read human in notes and docs; "
                     "avoid stacking them in formal references.",
         "bad_example": "Do not utilize the utilizer in order to achieve utilization.",
         "better_example": "Don't use it — it doesn't do anything.",
         "exceptions": ["style guides that ban contractions"]},
    ]


ZH_TERMS = {
    "particles": style_lang_zh.PARTICLES,
    "hedges": style_lang_zh.HEDGES,
    "boosters": style_lang_zh.BOOSTERS,
    "connectors": style_lang_zh.CONNECTORS,
    "colloquial": style_lang_zh.COLLOQUIAL_TERMS,
    "ai_tell_patterns": style_lang_zh.AI_TELL_PATTERNS,
    "construction_patterns": style_lang_zh.CONSTRUCTION_PATTERNS,
}

EN_TERMS = {
    "particles": style_lang_en.PARTICLES,
    "hedges": style_lang_en.HEDGES,
    "boosters": style_lang_en.BOOSTERS,
    "connectors": style_lang_en.CONNECTORS,
    "colloquial": [],
    "ai_tell_patterns": {
        "summary prelude": r"in conclusion|in summary|it is worth noting",
        "reveal dash": r"here's the (?:thing|kicker)",
        "hollow booster": r"\bhugely\b|\bmassively\b",
    },
    "construction_patterns": {},
}

ZH_TERMINOLOGY = [
    {"term": "检索增强生成", "abbr": "RAG", "first_mention": "检索增强生成（RAG）"},
    {"term": "存活时间", "abbr": "TTL", "first_mention": "存活时间（TTL）"},
    {"term": "预写日志", "abbr": "WAL", "first_mention": "预写日志（WAL）"},
]

EN_TERMINOLOGY = [
    {"term": "retrieval-augmented generation", "abbr": "RAG",
     "first_mention": "retrieval-augmented generation (RAG)"},
    {"term": "time to live", "abbr": "TTL", "first_mention": "time to live (TTL)"},
]

ZH_EXAMPLES = [
    {"id": "zh-tech-001", "register": "technical", "synthetic": True,
     "author": "note-curator", "source": "built-in", "license": "CC0",
     "reviewed": True,
     "text": "缓存能减少查询，但数据更新后，旧值还可能被继续读取，所以过期策略要和一致性要求一起定。"},
    {"id": "zh-retro-001", "register": "retrospective", "synthetic": True,
     "author": "note-curator", "source": "built-in", "license": "CC0",
     "reviewed": True,
     "text": "这次发布翻车在我的预估上：迁移脚本没考虑旧数据为空的分支，回滚花了四十分钟。"},
    {"id": "zh-exp-001", "register": "experiment", "synthetic": True,
     "author": "note-curator", "source": "built-in", "license": "CC0",
     "reviewed": True,
     "text": "把批量从 64 调到 128 后吞吐没涨，显存先满了；收益上限在批量 96 附近。"},
]

EN_EXAMPLES = [
    {"id": "en-tech-001", "register": "technical", "synthetic": True,
     "author": "note-curator", "source": "built-in", "license": "CC0",
     "reviewed": True,
     "text": "The cache hides latency until the data changes; then every reader sees stale rows."},
    {"id": "en-retro-001", "register": "retrospective", "synthetic": True,
     "author": "note-curator", "source": "built-in", "license": "CC0",
     "reviewed": True,
     "text": "The outage was on me: the migration script missed the empty-table branch, and rollback took forty minutes."},
]


def dump(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print("WROTE", path.relative_to(PACK_ROOT.parent))


def dump_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("WROTE", path.relative_to(PACK_ROOT.parent))


def main():
    zh_pack = {
        "schema_version": 1,
        "pack_version": "1.0.0",
        "language": "zh-CN",
        "name": "中文表达规则包（首版）",
        "compat": {"min_core": "1.7.0"},
        "weak_metrics": ["zh_constructions", "zh_four_char"],
        "terms": ZH_TERMS,
        "rules": zh_rules(),
    }
    en_pack = {
        "schema_version": 1,
        "pack_version": "1.0.0",
        "language": "en",
        "name": "English expression rules (first release)",
        "compat": {"min_core": "1.7.0"},
        "weak_metrics": [],
        "terms": EN_TERMS,
        "rules": en_rules(),
    }
    dump(PACK_ROOT / "zh-CN" / "pack.json", zh_pack)
    dump(PACK_ROOT / "en" / "pack.json", en_pack)
    dump(PACK_ROOT / "zh-CN" / "terminology.json", ZH_TERMINOLOGY)
    dump(PACK_ROOT / "en" / "terminology.json", EN_TERMINOLOGY)
    dump_jsonl(PACK_ROOT / "zh-CN" / "examples.jsonl", ZH_EXAMPLES)
    dump_jsonl(PACK_ROOT / "en" / "examples.jsonl", EN_EXAMPLES)


if __name__ == "__main__":
    main()
