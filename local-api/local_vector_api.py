from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

from PIL import Image
import vtracer


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class Job:
    image_id: str
    status: str
    input_path: str
    output_path: str
    original_filename: str
    created_at: float
    updated_at: float
    credits_left: None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "image_id": self.image_id,
            "status": self.status,
            "credits_left": self.credits_left,
        }
        if self.status == "completed":
            payload["file_url"] = f"/api/images/{self.image_id}/file"
            payload["result_url"] = f"/api/images/{self.image_id}/result"
        if self.error:
            payload["error"] = self.error
        return payload


class JobStore:
    def __init__(self, root: Path, workers: int) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.executor = ThreadPoolExecutor(max_workers=max(1, workers))
        self._load_existing_jobs()

    def _load_existing_jobs(self) -> None:
        for metadata_path in self.root.glob("*/job.json"):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                job = Job(**data)
                if job.status in {"queued", "processing"}:
                    job.status = "failed"
                    job.error = "服务重启时任务未完成。"
                    job.updated_at = time.time()
                    self._write(job)
                self.jobs[job.image_id] = job
            except Exception:
                continue

    def _write(self, job: Job) -> None:
        job_dir = Path(job.input_path).parent
        tmp_path = job_dir / "job.json.tmp"
        tmp_path.write_text(
            json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, job_dir / "job.json")

    def create(self, filename: str, payload: bytes) -> Job:
        image_id = uuid.uuid4().hex
        job_dir = self.root / image_id
        job_dir.mkdir(parents=True, exist_ok=False)
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            extension = ".bin"
        input_path = job_dir / f"input{extension}"
        output_path = job_dir / "result.svg"
        input_path.write_bytes(payload)
        now = time.time()
        job = Job(
            image_id=image_id,
            status="queued",
            input_path=str(input_path),
            output_path=str(output_path),
            original_filename=Path(filename).name or "image",
            created_at=now,
            updated_at=now,
        )
        with self.lock:
            self.jobs[image_id] = job
            self._write(job)
        self.executor.submit(self._process, image_id)
        return job

    def get(self, image_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(image_id)

    def _update(self, job: Job, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            self._write(job)

    def _process(self, image_id: str) -> None:
        job = self.get(image_id)
        if job is None:
            return
        self._update(job, status="processing", error=None)
        try:
            # Pillow verifies the input before it reaches the vectorizer and
            # gives clearer errors than a native backend would.
            with Image.open(job.input_path) as image:
                image.verify()

            vtracer.convert_image_to_svg_py(
                job.input_path,
                job.output_path,
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=8,
                color_precision=5,
                layer_difference=24,
                corner_threshold=60,
                length_threshold=6.0,
                max_iterations=10,
                splice_threshold=45,
                path_precision=6,
            )
            self._validate_svg(Path(job.output_path))
            self._update(job, status="completed")
        except Exception as exc:
            output_path = Path(job.output_path)
            if output_path.exists():
                output_path.unlink()
            message = str(exc).strip() or exc.__class__.__name__
            self._update(job, status="failed", error=message[:1000])

    @staticmethod
    def _validate_svg(path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("矢量化后端没有返回 SVG 文件。")
        JobStore._normalize_svg(path)
        content = path.read_text(encoding="utf-8", errors="strict")
        lowered = content.lower()
        if "<svg" not in lowered:
            raise RuntimeError("返回结果不是 SVG。")
        if "<image" in lowered or "data:image" in lowered or "base64," in lowered:
            raise RuntimeError("返回结果包含位图，不符合真实矢量输出要求。")
        if "<path" not in lowered and "<polygon" not in lowered:
            raise RuntimeError("SVG 中没有可绘制的矢量几何。")

    @staticmethod
    def _normalize_svg(path: Path) -> None:
        """Make VTracer's SVG acceptable to the Illustrator cache validator."""
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        tree = ET.parse(path)
        root = tree.getroot()

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def number(value: str | None) -> float | None:
            if not value:
                return None
            match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
            if not match:
                return None
            parsed = float(match.group(1))
            return parsed if parsed > 0 else None

        view_box = root.get("viewBox")
        view_box_ok = False
        if view_box:
            values = view_box.replace(",", " ").split()
            if len(values) == 4:
                try:
                    view_box_ok = float(values[2]) > 0 and float(values[3]) > 0
                except ValueError:
                    view_box_ok = False
        if not view_box_ok:
            width = number(root.get("width"))
            height = number(root.get("height"))
            if width is None or height is None:
                raise RuntimeError("SVG 缺少有效的画布尺寸。")
            root.set("viewBox", f"0 0 {width:g} {height:g}")

        geometry_tags = {
            "path", "polygon", "polyline", "rect", "circle", "ellipse", "line"
        }
        geometry_index = 0
        for element in root.iter():
            if local_name(element.tag) in geometry_tags:
                if not element.get("id"):
                    element.set("id", f"local-vector-{geometry_index:05d}")
                geometry_index += 1
        if geometry_index == 0:
            raise RuntimeError("SVG 中没有可绘制的矢量几何。")
        tree.write(path, encoding="utf-8", xml_declaration=True)


class LocalApiHandler(BaseHTTPRequestHandler):
    server_version = "LocalVectorService/1.0"

    @property
    def store(self) -> JobStore:
        return self.server.store  # type: ignore[attr-defined]

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def _send_svg(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _image_id_and_suffix(self) -> tuple[str | None, str | None]:
        parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
        if len(parts) < 3 or parts[0:2] != ["api", "images"]:
            return None, None
        image_id = parts[2]
        suffix = parts[3] if len(parts) >= 4 else None
        if not JOB_ID_RE.fullmatch(image_id):
            return None, None
        return image_id, suffix

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "local-vector-service",
                    "backend": "vtracer",
                    "authenticated": False,
                    "credits_left": None,
                },
            )
            return

        image_id, suffix = self._image_id_and_suffix()
        if image_id is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "未找到接口。")
            return
        job = self.store.get(image_id)
        if job is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "未找到图片任务。")
            return
        if suffix in {"file", "result"}:
            if job.status != "completed":
                status = HTTPStatus.CONFLICT if job.status in {"queued", "processing"} else HTTPStatus.INTERNAL_SERVER_ERROR
                self._send_json(status, job.public())
                return
            self._send_svg(Path(job.output_path))
            return
        if suffix is None:
            self._send_json(HTTPStatus.OK, job.public())
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "未找到接口。")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/images":
            self._send_error_json(HTTPStatus.NOT_FOUND, "未找到接口。")
            return
        content_length_header = self.headers.get("Content-Length")
        try:
            content_length = int(content_length_header or "-1")
        except ValueError:
            content_length = -1
        if content_length <= 0:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "缺少有效的请求体。")
            return
        if content_length > MAX_UPLOAD_BYTES + 1024 * 1024:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "图片超过 10 MB 限制。")
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "请使用 multipart/form-data 上传图片。")
            return
        body = self.rfile.read(content_length)
        if len(body) > MAX_UPLOAD_BYTES + 1024 * 1024:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "图片超过 10 MB 限制。")
            return
        try:
            filename, image_bytes = self._extract_image(content_type, body)
            if len(image_bytes) > MAX_UPLOAD_BYTES:
                raise ValueError("图片超过 10 MB 限制。")
            job = self.store.create(filename, image_bytes)
        except Exception as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc)[:1000])
            return
        self._send_json(HTTPStatus.ACCEPTED, job.public())

    @staticmethod
    def _extract_image(content_type: str, body: bytes) -> tuple[str, bytes]:
        envelope = (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n"
            "\r\n"
        ).encode("utf-8") + body
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        if not message.is_multipart():
            raise ValueError("无法解析 multipart 请求。")
        for part in message.iter_attachments():
            disposition_name = part.get_param("name", header="content-disposition")
            filename = part.get_filename() or "image"
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if disposition_name == "image" or Path(filename).suffix.lower() in ALLOWED_EXTENSIONS:
                return Path(filename).name, payload
        raise ValueError("请求中没有找到 image 文件字段。")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs useful without echoing request bodies or image data.
        print(f"[{self.log_date_time_string()}] {format % args}")


class LocalApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: JobStore) -> None:
        super().__init__(address, LocalApiHandler)
        self.store = store


def main() -> None:
    parser = argparse.ArgumentParser(description="Local drop-in API for vectorization")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "jobs",
    )
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    store = JobStore(args.data_dir.resolve(), args.workers)
    server = LocalApiServer((args.host, args.port), store)
    print(f"local vector API listening at http://{args.host}:{args.port}")
    print(f"job data directory: {args.data_dir.resolve()}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
