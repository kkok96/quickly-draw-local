#!/usr/bin/env python3
"""Run the quickly-draw cached Illustrator playback through pywin32.

Illustrator 2024 exposes a usable COM server to pywin32, while the bundled
PowerShell COM bridge cannot load this installation's type library.  This
adapter keeps the same cached JSX runtime, batching, checkpoints, resume state,
and final QA contract as run_vector_playback.ps1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pythoncom
import pywintypes
import win32com.client


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def js_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def do_javascript(illustrator, script: str) -> str:
    # pywin32's dynamic wrapper misclassifies DoJavaScript for this typelib and
    # tries a property get with no argument. Invoke the dispatch method by ID.
    dispid = illustrator._oleobj_.GetIDsOfNames("DoJavaScript")
    result = illustrator._oleobj_.Invoke(
        dispid,
        0,
        pythoncom.DISPATCH_METHOD,
        True,
        script,
    )
    return "" if result is None else str(result)


def read_result_value(result: str, key: str) -> str | None:
    prefix = key + "="
    for part in result.split("|"):
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


def invoke_cached_runtime(illustrator, runtime_path: Path, configuration: dict) -> str:
    runtime_json = json.dumps(runtime_path.resolve().as_posix())
    bootstrap = (
        f"var VECTOR_PLAYBACK_CONFIG = {js_json(configuration)}; "
        f"$.evalFile(new File({runtime_json}));"
    )
    return do_javascript(illustrator, bootstrap)


def existing_batch_groups(illustrator, state: dict, document_name: str) -> list[str]:
    configuration = {
        "documentName": document_name,
        "rootGroupName": str(state["root_group_name"]),
        "groupNames": [str(batch["group_name"]) for batch in state["batches"]],
    }
    payload = js_json(configuration)
    script = f"""
(function(){{
  var c={payload};
  function namedGroup(container,name){{
    for(var i=0;i<container.groupItems.length;i+=1){{
      try{{var item=container.groupItems[i];if(item&&item.name===name){{return item;}}}}catch(ignore){{}}
    }}
    return null;
  }}
  var doc=null;
  for(var d=0;d<app.documents.length;d+=1){{if(app.documents[d].name===c.documentName){{doc=app.documents[d];break;}}}}
  if(doc===null){{return 'ERROR|TARGET_DOCUMENT_MISSING';}}
  var root=namedGroup(doc,c.rootGroupName);
  if(root===null){{return '';}}
  var found=[];
  for(var i=0;i<c.groupNames.length;i+=1){{
    if(namedGroup(root,c.groupNames[i])!==null){{found.push(c.groupNames[i]);}}
  }}
  return found.join('|LCTSEP|');
}}());
"""
    result = do_javascript(illustrator, script)
    if result.startswith("ERROR|"):
        raise RuntimeError(result)
    return [value for value in result.split("|LCTSEP|") if value]


def save_ai_checkpoint(illustrator, runtime_path: Path, output_ai: Path, document_name: str) -> str:
    configuration = {
        "operation": "save",
        "targetDocumentName": document_name,
        "outputAi": output_ai.resolve().as_posix(),
    }
    result = invoke_cached_runtime(illustrator, runtime_path, configuration)
    if not result.startswith("OK|"):
        raise RuntimeError(f"AI checkpoint failed: {result}")
    return read_result_value(result, "documentName") or document_name


def export_final_png(illustrator, runtime_path: Path, output_png: Path, document_name: str) -> None:
    configuration = {
        "operation": "export",
        "targetDocumentName": document_name,
        "outputPng": output_png.resolve().as_posix(),
    }
    result = invoke_cached_runtime(illustrator, runtime_path, configuration)
    if not result.startswith("OK|"):
        raise RuntimeError(f"Final PNG export failed: {result}")


def normalize_root_stack(illustrator, state: dict, document_name: str, target_layer_name: str) -> None:
    configuration = {
        "documentName": document_name,
        "rootGroupName": str(state["root_group_name"]),
        "targetLayerName": target_layer_name,
        "batchGroupNames": [str(batch["group_name"]) for batch in state["batches"]],
    }
    payload = js_json(configuration)
    script = f"""
(function(){{
  var c={payload};
  function namedGroup(container,name){{
    for(var i=0;i<container.groupItems.length;i+=1){{
      try{{var item=container.groupItems[i];if(item&&item.name===name){{return item;}}}}catch(ignore){{}}
    }}
    return null;
  }}
  var doc=null;
  for(var d=0;d<app.documents.length;d+=1){{if(app.documents[d].name===c.documentName){{doc=app.documents[d];break;}}}}
  if(doc===null){{return 'ERROR|TARGET_DOCUMENT_MISSING';}}
  var root=namedGroup(doc,c.rootGroupName);
  if(root===null){{return 'ERROR|ROOT_GROUP_MISSING';}}
  var layer=null;
  if(c.targetLayerName){{try{{layer=doc.layers.getByName(c.targetLayerName);}}catch(ignoreLayer){{}}}}
  if(layer===null&&root.parent&&root.parent.typename==='Layer'){{layer=root.parent;}}
  if(layer===null){{return 'ERROR|TARGET_LAYER_MISSING';}}
  for(var b=0;b<c.batchGroupNames.length;b+=1){{
    var batch=namedGroup(root,c.batchGroupNames[b]);
    if(batch!==null&&batch.parent===root){{batch.zOrder(ZOrderMethod.BRINGTOFRONT);}}
  }}
  app.redraw();
  return 'OK|removed=0|existing_artwork_preserved=true';
}}());
"""
    result = do_javascript(illustrator, script)
    if not result.startswith("OK|"):
        raise RuntimeError(f"Final stack normalization failed: {result}")


def assert_complete_artwork(illustrator, cache: dict, state: dict, document_name: str) -> None:
    batch_expectations = []
    for batch in state["batches"]:
        paint_names = []
        for atom_index in batch["atom_indices"]:
            atom = cache["atoms"][int(atom_index)]
            paint_parts = atom.get("paintParts") or []
            if len(paint_parts) <= 1:
                paint_names.append(str(atom["objectName"]))
            else:
                paint_names.extend(
                    f"{atom['objectName']}_P{paint_index}"
                    for paint_index in range(len(paint_parts))
                )
        batch_expectations.append({"groupName": str(batch["group_name"]), "paintNames": paint_names})

    configuration = {
        "documentName": document_name,
        "rootGroupName": str(state["root_group_name"]),
        "batches": batch_expectations,
    }
    payload = js_json(configuration)
    script = f"""
(function(){{
  var c={payload};
  function namedGroup(container,name){{
    for(var i=0;i<container.groupItems.length;i+=1){{
      try{{var item=container.groupItems[i];if(item&&item.name===name){{return item;}}}}catch(ignore){{}}
    }}
    return null;
  }}
  function namedArtwork(container,name){{
    var group=namedGroup(container,name);if(group!==null){{return group;}}
    var collections=[container.pathItems,container.compoundPathItems,container.textFrames];
    for(var q=0;q<collections.length;q+=1){{
      for(var i=0;i<collections[q].length;i+=1){{
        try{{var item=collections[q][i];if(item&&item.name===name){{return item;}}}}catch(ignore){{}}
      }}
    }}
    return null;
  }}
  var doc=null;
  for(var d=0;d<app.documents.length;d+=1){{if(app.documents[d].name===c.documentName){{doc=app.documents[d];break;}}}}
  if(doc===null){{return 'ERROR|TARGET_DOCUMENT_MISSING';}}
  var root=namedGroup(doc,c.rootGroupName);
  if(root===null){{return 'ERROR|ROOT_GROUP_MISSING';}}
  var missing=0;
  for(var b=0;b<c.batches.length;b+=1){{
    var batch=namedGroup(root,c.batches[b].groupName);
    if(batch===null){{missing+=c.batches[b].paintNames.length;continue;}}
    for(var a=0;a<c.batches[b].paintNames.length;a+=1){{
      if(namedArtwork(batch,c.batches[b].paintNames[a])===null){{missing+=1;}}
    }}
  }}
  return 'OK|missing='+missing+'|placed='+root.placedItems.length+'|raster='+root.rasterItems.length;
}}());
"""
    result = do_javascript(illustrator, script)
    if not result.startswith("OK|missing=0|placed=0|raster=0"):
        raise RuntimeError(f"QA_FAILED|{result}")


def connect_illustrator():
    last_error = None
    for prog_id in ("Illustrator.Application.30", "Illustrator.Application.29", "Illustrator.Application.28", "Illustrator.Application"):
        try:
            illustrator = win32com.client.Dispatch(prog_id)
            version = str(illustrator.Version)
            if illustrator.Documents.Count >= 1:
                return illustrator, version, prog_id
        except Exception as exc:  # pragma: no cover - depends on installed COM registrations
            last_error = exc
    raise RuntimeError(f"AI_COM_UNAVAILABLE|Could not connect to Illustrator 2024+ via pywin32: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-svg", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output-ai", required=True, type=Path)
    parser.add_argument("--output-png", required=True, type=Path)
    parser.add_argument("--runtime-path", required=True, type=Path)
    parser.add_argument("--placement", default="center")
    parser.add_argument("--max-width-fraction", type=float, default=0.72)
    parser.add_argument("--max-height-fraction", type=float, default=0.78)
    parser.add_argument("--checkpoint-seconds", type=int, default=30)
    parser.add_argument("--retry-limit", type=int, default=12)
    parser.add_argument("--target-layer-name", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_svg = args.input_svg.resolve()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_ai = args.output_ai.resolve()
    output_png = args.output_png.resolve()
    runtime_path = args.runtime_path.resolve()
    cache_path = work_dir / "geometry-cache.json"
    state_path = work_dir / "playback.json"
    batch_payload_path = work_dir / "current-batch.json"

    if not cache_path.is_file() or not state_path.is_file():
        raise RuntimeError("Missing geometry-cache.json or playback.json; run prepare_geometry_cache.py first.")
    if not runtime_path.is_file():
        raise RuntimeError(f"Missing Illustrator runtime: {runtime_path}")

    cache = read_json(cache_path)
    state = read_json(state_path)
    pythoncom.CoInitialize()
    illustrator = None
    try:
        illustrator, version, prog_id = connect_illustrator()
        if illustrator.Documents.Count < 1:
            raise RuntimeError("AI_DOCUMENT_REQUIRED|Open the target Illustrator document yourself before drawing.")
        target_document_name = str(illustrator.ActiveDocument.Name)
        groups = existing_batch_groups(illustrator, state, target_document_name)
        last_checkpoint = time.monotonic()
        has_checkpoint = output_ai.is_file()
        continued = False

        for batch in state["batches"]:
            group_name = str(batch["group_name"])
            group_exists = group_name in groups
            if bool(batch.get("completed")) and group_exists:
                continued = True
                continue
            if bool(batch.get("completed")) and not group_exists:
                batch["completed"] = False
                batch["completed_at"] = None
                batch["last_error"] = "Recorded complete but the immutable batch group is missing."
                state["updated_at"] = utc_now()
                write_json_atomic(state_path, state)

            atoms = [cache["atoms"][int(index)] for index in batch["atom_indices"]]
            batch_payload_path.write_text(
                json.dumps({"viewBox": cache["view_box"], "atoms": atoms}, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            configuration = {
                "operation": "draw",
                "batchJsonPath": batch_payload_path.as_posix(),
                "targetDocumentName": target_document_name,
                "rootGroupName": str(state["root_group_name"]),
                "batchGroupName": group_name,
                "placement": args.placement,
                "maxWidthFraction": args.max_width_fraction,
                "maxHeightFraction": args.max_height_fraction,
                "delayMs": 0,
                "targetLayerName": args.target_layer_name,
            }
            result = ""
            for _ in range(args.retry_limit):
                batch["attempts"] = int(batch.get("attempts", 0)) + 1
                batch["last_error"] = None
                state["updated_at"] = utc_now()
                write_json_atomic(state_path, state)
                try:
                    result = invoke_cached_runtime(illustrator, runtime_path, configuration)
                except pywintypes.com_error as exc:
                    result = f"ERROR|COM|{exc}"
                if result.startswith("OK|"):
                    break
                batch["last_error"] = result
                state["updated_at"] = utc_now()
                write_json_atomic(state_path, state)
                if any(token in result for token in ("TARGET_DOCUMENT_MISSING", "AI_DOCUMENT_REQUIRED", "Unsupported operation")):
                    break
                time.sleep(0.08)
            if not result.startswith("OK|"):
                completed = sum(1 for item in state["batches"] if item.get("completed"))
                raise RuntimeError(
                    f"RESUME_REQUIRED|failed_batch={batch['index']}|completed={completed}/{len(state['batches'])}|state={state_path}|existing_artwork_preserved=true"
                )

            batch["completed"] = True
            batch["completed_at"] = utc_now()
            batch["last_error"] = None
            state["updated_at"] = utc_now()
            write_json_atomic(state_path, state)
            groups.append(group_name)
            print(f"DONE|batch={batch['index']}|group={group_name}|{result}", flush=True)

            if (not has_checkpoint) or time.monotonic() - last_checkpoint >= args.checkpoint_seconds:
                target_document_name = save_ai_checkpoint(illustrator, runtime_path, output_ai, target_document_name)
                last_checkpoint = time.monotonic()
                has_checkpoint = True

        completed_count = sum(1 for batch in state["batches"] if batch.get("completed"))
        if completed_count != len(state["batches"]):
            raise RuntimeError(f"QA_FAILED|completed={completed_count}/{len(state['batches'])}")
        normalize_root_stack(illustrator, state, target_document_name, args.target_layer_name)
        assert_complete_artwork(illustrator, cache, state, target_document_name)
        target_document_name = save_ai_checkpoint(illustrator, runtime_path, output_ai, target_document_name)
        export_final_png(illustrator, runtime_path, output_png, target_document_name)
        if not output_ai.is_file() or not output_png.is_file():
            raise RuntimeError("QA_FAILED|The expected AI or final PNG file is missing.")
        mode = "continued" if continued else "fresh"
        print(
            f"VECTOR_PLAYBACK_COMPLETE|cache={cache_path}|ai={output_ai}|png={output_png}|batches={completed_count}/{len(state['batches'])}|mode={mode}|illustrator_window_untouched=true",
            flush=True,
        )
        return 0
    finally:
        if batch_payload_path.exists():
            batch_payload_path.unlink(missing_ok=True)
        if illustrator is not None:
            try:
                illustrator = None
            finally:
                pythoncom.CoUninitialize()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
