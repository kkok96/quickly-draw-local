---
name: quickly-draw
description: Use when a user provides a PNG, JPEG, or WebP and asks for a faithful redraw, trace, vectorization, or Illustrator recreation, especially when the source contains English text, numbers, labels, charts, or editable typography.
author: Kkeep
---

# quickly-draw

## Core rule: readable text is always live text

Every legible human-readable character in the reference is content, not artwork. English words, Latin/Greek symbols, panel letters, digits, decimals, units, axis ticks, legends, captions, chemical labels, superscripts, and abbreviations **must be native editable Illustrator text** (`TextFrame` / live text box).

Do not trace glyphs into paths. Do not rasterize text. Do not keep a raster-text fallback in the final artwork. A hidden source image or temporary outline layer may be used only for visual comparison and must not be the delivered representation. If a vectorizer creates glyph outlines, remove those glyphs from the final graphics layer before delivery; never place live text on top of duplicate traced lettering.

## Direct mode

When the image is readable and Illustrator already has a clear target document or artboard, start drawing immediately. Do not turn a simple redraw into a planning or approval workflow. Keep the whole reference as one composition.

## Required redraw pipeline

1. Make only two initial checks: Illustrator is open with an unambiguous target, and the reference image can be read. Preserve the original file.
2. Allocate the next unused `shibielujingN` basename. Never overwrite existing customer files or Illustrator artwork.
3. Inventory all readable text with OCR plus visual/manual correction. Preserve exact capitalization, punctuation, line breaks, symbols (`μ`, `×`, `⁸`), units, and numbers. Keep one manifest entry per independent text box with content, bounds, font family, size, weight, fill, alignment, and rotation.
4. Remove text from the graphics input before vectorization: mask the detected glyph polygons and inpaint the local background. Vectorize only non-text graphics (panels, particles, cells, arrows, chart lines, axes, frames, and fills).
5. Create one native Illustrator text object per manifest entry. Use area-text boxes for multi-line labels and point text for isolated labels or ticks. Use an editable substitute font if the original font is unavailable; never outline the substitute.
6. Merge the graphics and live-text layers without changing the reference composition. Keep the white scientific-figure background, proportions, colors, arrows, charts, frames, and detail. Do not add style or content.
7. Validate before claiming completion: the SVG has live `<text>` elements and no raster nodes; the imported Illustrator document has the expected nonzero `textFrames` count; representative strings are selectable and editable character-by-character; no required readable text exists only as a path or pixel; and the result is visually checked at 100% zoom.
8. Save AI and export SVG and PNG when useful or requested. If the PNG is only a preview, export it at the reference composition's actual aspect ratio and readable resolution.

## Text manifest contract

Use the existing `scripts/merge_live_text.py` runtime. Its input manifest must contain `text_elements`; each element must have stable `id`, exact `content`, absolute `x`/`y` or a documented bounding box, `font_size`, `font_family`, `font_weight`, `fill`, `text_anchor`, `alignment_baseline`, and `rotation`. The graphics SVG and manifest must use the same viewBox and coordinate system. Duplicate `(content, bounds)` entries are an error. Run `scripts/validate_live_text_manifest.py` for this manifest; `scripts/validate_manifest.py` is for the separate geometry manifest format.

If OCR confidence is low, inspect and transcribe from the source manually. If a character is genuinely unreadable, keep an editable text box marked `[VERIFY]` and report it; never silently replace it with traced or raster text.

## Runtime and file handling

Use the bundled Illustrator bridge/runtime and read `references/illustrator-runtime.md` when parameters or import behavior matter. Useful helpers include `scripts/build_live_text_redraw.py`, `scripts/merge_live_text.py`, `scripts/validate_live_text_manifest.py`, `scripts/validate_vector_svg.py`, `scripts/validate_manifest.py`, `scripts/run_vector_playback.ps1`, and `scripts/allocate_shibielujing_name.py`. Do not start, close, focus, move, or rearrange Illustrator.

Pause only when Illustrator is not open, the target document is unclear, the reference cannot be read, or the requested save would overwrite existing work. Do not pause merely because OCR needs manual correction or because validation takes time.

## Output contract

At start, say only: `正在绘制。`

At completion, say only: `完成。` followed by clickable AI, SVG, and PNG paths.

If blocked, state the missing condition in one sentence. Do not expose internal commands, logs, prompts, or batch details.

## Red flags — stop and correct

- A readable English word or number appears as a `path`, raster image, or embedded PNG in the final deliverable.
- The graphics trace still contains glyph outlines underneath live text.
- OCR output was accepted without visual correction for scientific notation, units, or digits.
- Illustrator `textFrames.length` is zero or materially below the manifest count.
- A missing font was “fixed” by outlining text.
- The package or output was zipped without checking every referenced file.

Any red flag means the result is not complete. Fix it before saving the final deliverable.
