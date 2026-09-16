"""Create a text-free graphics raster and a native-text manifest from an image.

Usage:
    python build_live_text_redraw.py INPUT MASKED_OUTPUT MANIFEST_JSON

The masked image is for graphics-only vectorization. The manifest is consumed by
merge_live_text.py. OCR is only a candidate generator: inspect and correct the
manifest before importing it into Illustrator.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


def normalize_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    for old, new in {
        "DOx": "DOX",
        "Dox": "DOX",
        "dox": "DOX",
        "μug": "μg",
        "X×108": "×10⁸",
        "×108": "×10⁸",
    }.items():
        value = value.replace(old, new)
    return value


def is_usable_text(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
        "@()[]%+-–—./,:;*~<>≤≥≈μ⁸×'"
    )
    return all(char in allowed for char in value)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: build_live_text_redraw.py INPUT MASKED_OUTPUT MANIFEST_JSON"
        )

    source_path = Path(sys.argv[1]).resolve()
    masked_path = Path(sys.argv[2]).resolve()
    manifest_path = Path(sys.argv[3]).resolve()
    # cv2.imread is unreliable for non-ASCII Windows paths. Read bytes first
    # so a Chinese/Unicode source path works the same as an ASCII path.
    encoded_source = np.fromfile(str(source_path), dtype=np.uint8)
    image = cv2.imdecode(encoded_source, cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"cannot read image: {source_path}")

    result, _ = RapidOCR()(str(source_path))
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    elements: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()

    for item in result or []:
        points, raw_text, confidence = item
        text = normalize_text(str(raw_text))
        if float(confidence) < 0.72 or not is_usable_text(text):
            continue

        polygon = np.asarray(points, dtype=np.float32)
        x_min = max(0, int(np.floor(polygon[:, 0].min())))
        y_min = max(0, int(np.floor(polygon[:, 1].min())))
        x_max = min(image.shape[1] - 1, int(np.ceil(polygon[:, 0].max())))
        y_max = min(image.shape[0] - 1, int(np.ceil(polygon[:, 1].max())))
        if x_max <= x_min or y_max <= y_min:
            continue

        key = (text, round(x_min / 3), round(y_min / 3), round(x_max / 3), round(y_max / 3))
        if key in seen:
            continue
        seen.add(key)
        cv2.fillPoly(mask, [np.round(polygon).astype(np.int32)], 255)

        width = x_max - x_min
        height = y_max - y_min
        is_vertical = height > width * 1.55 and len(text) >= 4
        if text == "DAPI":
            fill = "#155dcc"
        elif text == "DOX":
            fill = "#ef233c"
        elif text == "Merge":
            fill = "#183b8c"
        else:
            fill = "#18202b"

        elements.append(
            {
                "id": f"live_text_{len(elements) + 1:04d}",
                "content": text,
                "x": (x_min + x_max) / 2.0,
                "y": (y_min + y_max) / 2.0,
                "coordinate_space": "absolute",
                "font_size": max(8.0, min(30.0, height * 0.92)),
                "font_family": "Arial",
                "font_weight": "bold" if height >= 18 else "normal",
                "text_anchor": "middle",
                "alignment_baseline": "middle",
                "fill": fill,
                "rotation": -90 if is_vertical else 0,
                "paint_order": 100000 + len(elements),
            }
        )

    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
    masked = cv2.inpaint(image, mask, 2, cv2.INPAINT_NS)
    encoded = cv2.imencode(".png", masked)[1]
    masked_path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(masked_path))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"schema_version": "1.0", "text_elements": elements}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"text_count": len(elements), "masked": str(masked_path), "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
