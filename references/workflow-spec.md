# Lightweight quickly-draw specification

## Goal

Turn a customer-supplied image into an Illustrator drawing with the closest practical visual match.

## Default contract

- Start drawing as soon as the image and Illustrator target are available.
- Keep the reference as one complete composition; do not split it into subject-by-subject jobs.
- Preserve composition, proportions, colors, typography, arrows, charts, frames, labels, and recognizable scientific details.
- Every legible English word, number, symbol, unit, axis label, legend, caption, and panel letter must be a native editable Illustrator text object. Use paths only for non-text graphics.
- Mask text before graphics vectorization. If a raster trace already contains glyph outlines, remove those glyphs from the final graphics layer; never add a second live-text copy over them.
- Use clean flat 2D scientific styling unless the reference clearly calls for another style.

## File handling

- Preserve the original image.
- Use the next available `shibielujingN` basename.
- Never overwrite a customer file or delete existing Illustrator artwork.
- Save AI at the end and export SVG/PNG when requested or useful.

## Editable-text mode

Use the text manifest, text cleanup, vector QA, one-time geometry caching, and resumable playback whenever the source contains readable text. `scripts/merge_live_text.py` and `scripts/validate_manifest.py` are part of the normal workflow, not optional polish.

## Blocking conditions

Pause only when Illustrator is not open, the target document is unclear, the image cannot be read, or the requested save would overwrite existing work. Do not start, close, focus, or rearrange Illustrator.
