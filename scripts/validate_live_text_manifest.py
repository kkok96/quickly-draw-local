"""Validate the live-text manifest consumed by merge_live_text.py."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


REQUIRED = {
    "id",
    "content",
    "font_size",
    "font_family",
    "font_weight",
    "fill",
    "text_anchor",
    "alignment_baseline",
    "rotation",
}


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    try:
        document = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # pragma: no cover - command-line diagnostic
        print(json.dumps({"status": "FAIL", "errors": [f"Cannot parse JSON: {exc}"]}, ensure_ascii=False))
        return 1

    if document.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'.")
    elements = document.get("text_elements")
    if not isinstance(elements, list):
        errors.append("text_elements must be a list.")
        elements = []
    if not elements and not args.allow_empty:
        errors.append("text_elements must not be empty for an image containing readable text.")

    ids: set[str] = set()
    positions: set[tuple[object, ...]] = set()
    for index, element in enumerate(elements):
        prefix = f"text_elements[{index}]"
        if not isinstance(element, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        missing = sorted(REQUIRED - element.keys())
        if missing:
            errors.append(f"{prefix} missing: {', '.join(missing)}.")
        item_id = element.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string.")
        elif item_id in ids:
            errors.append(f"Duplicate text id: {item_id}.")
        else:
            ids.add(item_id)

        content = element.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{prefix}.content must be a non-empty string.")
        if not finite_number(element.get("font_size")) or float(element.get("font_size", 0)) <= 0:
            errors.append(f"{prefix}.font_size must be a positive finite number.")
        for coordinate in ("x", "y"):
            if not finite_number(element.get(coordinate)):
                errors.append(f"{prefix}.{coordinate} must be a finite number.")
        if not finite_number(element.get("rotation")):
            errors.append(f"{prefix}.rotation must be a finite number.")

        key = (
            content,
            round(float(element.get("x", 0)), 3) if finite_number(element.get("x")) else None,
            round(float(element.get("y", 0)), 3) if finite_number(element.get("y")) else None,
        )
        if key in positions:
            errors.append(f"Duplicate text content and position: {content!r}.")
        positions.add(key)

    report = {
        "schema_version": document.get("schema_version"),
        "status": "PASS" if not errors else "FAIL",
        "file": str(args.manifest.resolve()),
        "text_count": len(elements),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
