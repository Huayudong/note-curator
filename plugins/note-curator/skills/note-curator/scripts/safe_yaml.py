#!/usr/bin/env python3
"""
safe_yaml.py — note-curator 配置的受限 YAML 子集解析与 schema 校验（纯标准库）。

为什么不用正则、也不引第三方 YAML（B01-12 / G18）：
  - 旧实现用正则只取 vault_path 和 author 两个字段，其余配置各入口读法不一致。
  - 完整 YAML 需要第三方库；本 skill 对外保持零第三方依赖。
  因此这里实现明确声明的子集，遇到不支持的构造抛 ValueError 而不是静默猜错。

支持的子集：
  - # 注释（整行；行尾注释仅识别引号外的「 #」）
  - 顶层与嵌套映射（key: value），缩进只接受空格（tab 直接报错）
  - 块列表（- item / - key: value 起始的映射项）
  - 行内列表 [a, b, "c"]
  - 标量：带引号字符串、整数、浮点、true/false、null/~/空值
不支持的构造（抛错）：锚点/引用、多行标量 | 和 >、流映射 {a: b}、
文档分隔符 ---、标签。

validate_config 按 SCHEMA 校验：未知键进 warnings；类型不对进 errors。
"""

import re
from pathlib import Path

KEY_VALUE_RE = re.compile(r"^([^:\s][^:]*?):(?:\s+(.*))?$")


def _strip_comment(line):
    """去掉行尾注释（引号外的「 #」）。"""
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double \
                and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _parse_scalar(raw):
    text = raw.strip()
    if not text:
        return None
    if text[0] in "&*" or text.startswith("!!"):
        raise ValueError("不支持 YAML 锚点、引用或标签: %r" % raw)
    if text[0] in "\"'":
        if len(text) < 2 or text[-1] != text[0]:
            raise ValueError("引号字符串没有闭合: %r" % raw)
        return text[1:-1]
    if text.startswith("{"):
        raise ValueError("不支持流映射 {}，请改用缩进映射: %r" % raw)
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError("行内列表没有闭合: %r" % raw)
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline(inner)]
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_inline(text):
    """按逗号切行内列表项，忽略引号内的逗号。"""
    parts = []
    buf = []
    in_single = in_double = False
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == "," and not in_single and not in_double:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _indent_of(line):
    stripped_len = len(line) - len(line.lstrip(" "))
    if line[stripped_len:stripped_len + 1] == "\t":
        raise ValueError("YAML 缩进不接受 tab，请改用空格: %r" % line)
    return stripped_len


def _parse_block(lines, idx, warnings):
    """解析 lines[idx:] 处的一个块（缩进由首行决定）。返回 (值, 下一行号)。"""
    indent = _indent_of(lines[idx])
    if lines[idx].strip().startswith("-"):
        return _parse_list(lines, idx, indent, warnings)
    return _parse_map(lines, idx, indent, warnings)


def _parse_list(lines, idx, indent, warnings):
    items = []
    n = len(lines)
    while idx < n:
        raw = lines[idx]
        if not raw.strip():
            idx += 1
            continue
        cur = _indent_of(raw)
        if cur < indent:
            break
        stripped = _strip_comment(raw).strip()
        if not stripped:
            idx += 1
            continue
        if cur > indent or not stripped.startswith("- "):
            raise ValueError("列表项缩进或格式不对: %r" % raw)
        rest = stripped[2:].strip()
        if not rest:
            raise ValueError("暂不支持列表项下的空起始（- 后为空）: %r" % raw)
        m = KEY_VALUE_RE.match(rest)
        if m and not rest.startswith("["):
            # - key: value 起始的映射项：把它当成一行缩进映射的起点继续收集
            item_indent = indent + 2
            sub_lines = [" " * item_indent + rest]
            idx += 1
            while idx < n:
                nxt = lines[idx]
                if not nxt.strip():
                    sub_lines.append("")
                    idx += 1
                    continue
                cur2 = _indent_of(nxt)
                if cur2 < item_indent or (cur2 == item_indent
                                          and nxt.strip().startswith("- ")):
                    break
                sub_lines.append(nxt)
                idx += 1
            value, _ = _parse_map(sub_lines, 0, item_indent, warnings)
            items.append(value)
            continue
        items.append(_parse_scalar(rest))
        idx += 1
    return items, idx


def _parse_map(lines, idx, indent, warnings):
    result = {}
    n = len(lines)
    while idx < n:
        raw = lines[idx]
        if not raw.strip():
            idx += 1
            continue
        cur = _indent_of(raw)
        if cur < indent:
            break
        if cur > indent:
            raise ValueError("缩进比当前层级深，无法归属: %r" % raw)
        line = _strip_comment(raw)
        if not line.strip():
            idx += 1
            continue
        if line.strip().startswith("- "):
            raise ValueError("映射位置出现列表项: %r" % raw)
        m = KEY_VALUE_RE.match(line.strip())
        if not m:
            raise ValueError("无法解析的配置行（期望 key: value）: %r" % raw)
        key = m.group(1).strip().strip("\"'")
        value_raw = (m.group(2) or "").strip()
        idx += 1
        if value_raw:
            result[key] = _parse_scalar(value_raw)
        else:
            j = idx
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _indent_of(lines[j]) > cur:
                value, idx = _parse_block(lines, j, warnings)
            else:
                value = None
            result[key] = value
    return result, idx


def _flow_depth(text):
    """未闭合的 [ 深度（引号外）。"""
    depth = 0
    in_single = in_double = False
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
    return depth


def _join_flow_lines(lines):
    """把跨多行的行内列表 [ ... ] 拼回单行（真实配置里长关键词列表很常见）。"""
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = _strip_comment(lines[i])
        i += 1
        if not line.strip() or "[" not in line or _flow_depth(line) <= 0:
            out.append(line)
            continue
        joined = line
        while _flow_depth(joined) > 0 and i < n:
            nxt = _strip_comment(lines[i]).strip()
            i += 1
            if not nxt:
                continue
            joined += " " + nxt
        if _flow_depth(joined) > 0:
            raise ValueError("行内列表没有闭合: %r" % line.strip())
        out.append(joined)
    return out


def loads(text):
    """解析配置文本，返回 (data, warnings)。不支持的构造抛 ValueError。"""
    if text.lstrip().startswith("---"):
        raise ValueError("不支持 YAML 文档分隔符（---），请提供单一映射文档")
    lines = _join_flow_lines(text.splitlines())
    data = {}
    warnings = []
    idx = 0
    n = len(lines)
    while idx < n:
        if not lines[idx].strip():
            idx += 1
            continue
        block, idx = _parse_map(lines, idx, _indent_of(lines[idx]), warnings)
        data.update(block)
    return data, warnings


def load_file(path):
    return loads(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------- schema 校验 ----------

SCHEMA = {
    "vault_path": str,
    "adapter": str,
    "interface_language": str,
    "taxonomy": {"default_dir": str, "rules": list, "confirm_dir": bool},
    "frontmatter": {"author": str, "auto_tags": bool},
    "backlinks": {"mode": str, "min_confidence": float},
    "dedup": {"scope": str, "similarity_threshold": float,
              "merge_flow": str, "default_op": str, "conflict_handling": str},
    "style": {"geek_joke_probability": float, "allow_extension": bool,
              "learn_from_vault": bool, "profile_sample": int,
              "language": str, "profile_dir": str, "check_before_write": bool,
              "output_language": str,
              "allowed_phrases": list, "banned_phrases": list},
}

TYPE_NAMES = {str: "字符串", bool: "布尔值", list: "列表", int: "整数",
              float: "数字"}


def _check_type(value, expect):
    if expect is bool:
        return isinstance(value, bool)
    if expect is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expect is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expect)


def validate_config(data):
    """按 SCHEMA 校验。返回 (errors, warnings)。未知键只警告，不删除。"""
    errors = []
    warnings = []
    for key, expect in SCHEMA.items():
        if key not in data or data[key] is None:
            continue
        if isinstance(expect, dict):
            sub = data[key]
            if not isinstance(sub, dict):
                errors.append("%s 应为映射，实际是 %s" % (key, type(sub).__name__))
                continue
            for sub_key, sub_expect in expect.items():
                if sub_key in sub and sub[sub_key] is not None:
                    if not _check_type(sub[sub_key], sub_expect):
                        errors.append("%s.%s 应为 %s，实际是 %r"
                                      % (key, sub_key,
                                         TYPE_NAMES.get(sub_expect, sub_expect),
                                         sub[sub_key]))
            for extra in sub:
                if extra not in expect:
                    warnings.append("未知配置项 %s.%s（已忽略其影响）" % (key, extra))
        else:
            if not _check_type(data[key], expect):
                errors.append("%s 应为 %s，实际是 %r"
                              % (key, TYPE_NAMES.get(expect, expect), data[key]))
    for extra in data:
        if extra not in SCHEMA:
            warnings.append("未知配置项 %s（已忽略其影响）" % extra)
    author = (data.get("frontmatter") or {}).get("author")
    if author is not None and not isinstance(author, str):
        errors.append("frontmatter.author 应为字符串")
    return errors, warnings


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) != 2:
        print("用法：python safe_yaml.py <config.yaml>  # 输出解析与校验结果 JSON",
              file=sys.stderr)
        sys.exit(1)
    try:
        parsed, warns = load_file(sys.argv[1])
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    errs, warns2 = validate_config(parsed)
    print(json.dumps({"ok": not errs, "errors": errs,
                      "warnings": warns + warns2, "data": parsed},
                     ensure_ascii=False, indent=2))
    sys.exit(0 if not errs else 2)
