#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from html_assets import ALL_FIELDS


FIELD_SET_FULL = "full"
FIELD_SET_CORE = "core"
FIELD_SET_MINIMAL = "minimal"

FIELD_SET_CHOICES = (FIELD_SET_FULL, FIELD_SET_CORE, FIELD_SET_MINIMAL)

# NOTE: Keep defaults backward-compatible: empty visible_fields => show ALL_FIELDS.
FIELD_SET_TO_FIELDS: dict[str, Tuple[str, ...]] = {
    FIELD_SET_FULL: (),
    FIELD_SET_CORE: (
        "project_name",
        "amount",
        "procurer",
        "publish_date",
        "deadline",
        "winner",
        "source_url",
    ),
    FIELD_SET_MINIMAL: (
        "project_name",
        "amount",
        "publish_date",
        "deadline",
        "source_url",
    ),
}


@dataclass(frozen=True)
class VisibleFieldOptions:
    field_set: Optional[str] = None
    visible_fields_csv: Optional[str] = None


def resolve_visible_fields(options: VisibleFieldOptions) -> Tuple[str, ...]:
    """Resolve visible fields from CLI options.

    Priority:
    1) visible_fields_csv (explicit list) overrides everything
    2) field_set maps to a predefined subset
    3) default: () meaning ALL_FIELDS
    """
    explicit = _parse_csv(options.visible_fields_csv)
    if explicit:
        fields = tuple(item.lower() for item in explicit)
        _validate_visible_fields(fields)
        return fields

    if options.field_set:
        key = str(options.field_set).strip().lower()
        if key not in FIELD_SET_TO_FIELDS:
            raise ValueError(f"--field-set 仅支持: {', '.join(FIELD_SET_CHOICES)}")
        return FIELD_SET_TO_FIELDS[key]

    return ()


def _parse_csv(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return ()
    items = [item.strip() for item in str(value).split(",") if item.strip()]
    return tuple(items)


def _validate_visible_fields(fields: Sequence[str]) -> None:
    allowed = set(ALL_FIELDS)
    unknown = [item for item in fields if item not in allowed]
    if unknown:
        supported = ", ".join(ALL_FIELDS)
        raise ValueError(f"--visible-fields 含不支持字段: {', '.join(unknown)}。支持: {supported}")

