#!/usr/bin/env python3
from __future__ import annotations

"""Minimal YAML subset parser used by job configs.

Supported:
- mappings (dict)
- scalars: string/number/bool/null
- scalar lists

Not supported:
- tabs
- comments
- anchors/aliases
- complex objects (list of mappings)
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


INDENT_SPACES = 2


@dataclass(frozen=True)
class ParsedLine:
    indent: int
    content: str


def parse_yaml_subset(text: str) -> dict:
    lines = _normalize_lines(text)
    document, next_index = _parse_block(lines, 0, 0)
    if next_index != len(lines):
        raise ValueError(f"Unexpected trailing content near line {next_index + 1}")
    if not isinstance(document, dict):
        raise ValueError("Top-level YAML must be a mapping")
    return document


def _normalize_lines(text: str) -> List[ParsedLine]:
    lines: List[ParsedLine] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if "\t" in raw:
            raise ValueError("Tabs are not supported in job YAML")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % INDENT_SPACES != 0:
            raise ValueError(f"Indentation must use multiples of {INDENT_SPACES} spaces")
        lines.append(ParsedLine(indent=indent, content=raw.strip()))
    return lines


def _parse_block(lines: List[ParsedLine], index: int, indent: int) -> Tuple[object, int]:
    if index >= len(lines):
        raise ValueError("Unexpected end of YAML input")
    line = lines[index]
    if line.indent != indent:
        raise ValueError(f"Unexpected indentation at line {index + 1}")
    if line.content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: List[ParsedLine], index: int, indent: int) -> Tuple[dict, int]:
    mapping: dict = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise ValueError(f"Unexpected indentation at line {index + 1}")
        if line.content.startswith("- "):
            break
        key, value = _split_key_value(line.content, index)
        if value is None:
            mapping[key], index = _parse_nested(lines, index + 1, indent)
            continue
        mapping[key] = _parse_scalar(value)
        index += 1
    return mapping, index


def _parse_list(lines: List[ParsedLine], index: int, indent: int) -> Tuple[list, int]:
    values: list = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent != indent:
            raise ValueError(f"Unexpected indentation at line {index + 1}")
        if not line.content.startswith("- "):
            break
        item = line.content[2:].strip()
        if not item:
            nested, index = _parse_nested(lines, index + 1, indent)
            values.append(nested)
            continue
        values.append(_parse_scalar(item))
        index += 1
    return values, index


def _parse_nested(lines: List[ParsedLine], index: int, parent_indent: int) -> Tuple[object, int]:
    if index >= len(lines):
        raise ValueError("Nested YAML block is missing")
    if lines[index].indent <= parent_indent:
        raise ValueError(f"Expected nested block at line {index + 1}")
    return _parse_block(lines, index, parent_indent + INDENT_SPACES)


def _split_key_value(content: str, index: int) -> Tuple[str, Optional[str]]:
    if ":" not in content:
        raise ValueError(f"Invalid mapping entry at line {index + 1}")
    key, raw_value = content.split(":", 1)
    name = key.strip()
    if not name:
        raise ValueError(f"Missing key at line {index + 1}")
    value = raw_value.strip()
    return name, value if value else None


def _parse_scalar(value: str) -> object:
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value == "[]":
        return []
    if lowered.isdigit():
        return int(lowered)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
