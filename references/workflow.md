# Direct drawing workflow

This is the operational reference for quickly-draw. The normal path is short, but editable text is mandatory whenever the source has readable text:

1. Confirm that Illustrator is already open and the reference image is readable.
2. Allocate the next `shibielujingN` name and preserve the source image.
3. Inventory readable English, numbers, symbols, labels, and captions as live-text manifest entries.
4. Mask text before vectorizing the non-text graphics, then merge native Illustrator text frames.
5. Draw the complete composition directly in the active Illustrator document.
6. Validate the SVG and live-text manifest, then save a new AI file and export SVG/PNG when useful.

Keep the whole reference together. Preserve its layout, text, arrows, charts, labels, colors, and scientific details. All readable text must be live text; traced glyph paths and raster text are not acceptable final representations.

Use the text manifest, text cleanup, and detailed validation as part of the normal path. Add geometry caching or staged playback when the artwork is large or Illustrator import is slow.

If the Illustrator target is missing or the next action would overwrite an existing file, pause and ask one concise question. Do not launch or close Illustrator on the user's behalf.
