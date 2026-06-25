from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import gc
import traceback
from typing import Any, Callable

import fitz  # PyMuPDF

from .config import RuleConfig
from .pdf_rules import estimate_parts, initial_pages_per_part
from .utils import ensure_dir, file_size, mb, sanitize_filename_part, unique_path

ProgressFn = Callable[[str], None]


def scan_pdf(path: str | Path, rule: RuleConfig) -> dict[str, Any]:
    path = Path(path)
    info: dict[str, Any] = {
        "file_name": path.name,
        "original_path": str(path),
        "page_count": None,
        "size_bytes": None,
        "size_mb": None,
        "over_pages": None,
        "over_size": None,
        "estimated_parts": None,
        "encrypted": None,
        "error": "",
    }
    try:
        size = file_size(path)
        with fitz.open(path) as doc:
            info["encrypted"] = bool(doc.needs_pass)
            if doc.needs_pass:
                raise RuntimeError("PDF is encrypted and requires a password")
            pages = doc.page_count
        info.update({
            "page_count": pages,
            "size_bytes": size,
            "size_mb": mb(size),
            "over_pages": pages > rule.max_pages,
            "over_size": size > rule.max_size_bytes,
            "estimated_parts": estimate_parts(pages, size, rule),
        })
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _save_options(level: str) -> dict[str, Any]:
    # PyMuPDF save options. Image DPI downsampling is intentionally not implemented here:
    # PyMuPDF's safe built-in save options preserve OCR text layer and reduce redundant streams.
    if level == "none":
        return {"garbage": 0, "deflate": False, "clean": False}
    if level == "light":
        return {"garbage": 1, "deflate": True, "clean": False}
    if level == "medium":
        return {"garbage": 3, "deflate": True, "clean": True}
    return {"garbage": 4, "deflate": True, "clean": True}


def _copy_toc_for_range(src: fitz.Document, dst: fitz.Document, start_1: int, end_1: int) -> None:
    toc = src.get_toc(simple=False)
    if not toc:
        return
    new_toc = []
    for item in toc:
        level, title, page = item[0], item[1], item[2]
        rest = item[3] if len(item) > 3 else None
        if start_1 <= page <= end_1:
            new_item = [level, title, page - start_1 + 1]
            if rest is not None:
                new_item.append(rest)
            new_toc.append(new_item)
    if new_toc:
        try:
            dst.set_toc(new_toc)
        except Exception:
            # Bookmark preservation is best effort.
            pass


def _render_filename(template: str, source: Path, part_no: int, start: int, end: int) -> str:
    stem = sanitize_filename_part(source.stem)
    try:
        name = template.format(name=stem, part=part_no, start=start, end=end)
    except Exception:
        name = f"{stem}__part{part_no:03d}_p{start:03d}-{end:03d}.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return sanitize_filename_part(name[:-4]) + ".pdf"


def _split_once(src_path: Path, out_dir: Path, rule: RuleConfig, start_1: int, end_1: int, part_no: int) -> Path:
    out_name = _render_filename(rule.filename_template, src_path, part_no, start_1, end_1)
    out_path = unique_path(out_dir / out_name)
    src_doc = fitz.open(src_path)
    dst_doc = fitz.open()
    try:
        dst_doc.insert_pdf(src_doc, from_page=start_1 - 1, to_page=end_1 - 1, links=True, annots=True, show_progress=0)
        if rule.keep_bookmarks:
            _copy_toc_for_range(src_doc, dst_doc, start_1, end_1)
        dst_doc.save(out_path, **_save_options(rule.compression_level))
    finally:
        dst_doc.close()
        src_doc.close()
        gc.collect()
    return out_path


def _output_record(src_path: Path, out_path: Path, start: int, end: int, rule: RuleConfig, error: str = "") -> dict[str, Any]:
    pages = 0
    size = 0
    compliant = False
    reason = ""
    try:
        size = file_size(out_path)
        with fitz.open(out_path) as doc:
            pages = doc.page_count
        reasons = []
        if pages > rule.max_pages:
            reasons.append(f"pages {pages} > limit {rule.max_pages}")
        if size > rule.max_size_bytes:
            reasons.append(f"size {mb(size)} MB > limit {rule.max_size_mb} MB")
        if error:
            reasons.append(error)
        compliant = not reasons
        reason = "; ".join(reasons)
    except Exception as exc:
        reason = f"failed to inspect final output: {exc}"
        error = error or str(exc)
    return {
        "original_path": str(src_path),
        "output_path": str(out_path),
        "page_range": [start, end],
        "output_pages": pages,
        "output_size_bytes": size,
        "output_size_mb": mb(size),
        "is_mineru_compliant": compliant,
        "error": error,
        "rule": {
            "max_pages": rule.max_pages,
            "max_size_mb": rule.max_size_mb,
            "strategy": rule.strategy,
            "compression_level": rule.compression_level,
            "min_dpi": rule.min_dpi,
            "keep_bookmarks": rule.keep_bookmarks,
            "keep_ocr_text": rule.keep_ocr_text,
        },
        "output": {
            "compliant": compliant,
            "reason_if_not_compliant": reason,
        },
    }


def _recursive_process_range(src_path: Path, out_dir: Path, rule: RuleConfig, start: int, end: int, part_counter: list[int], progress: ProgressFn | None, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 20:
        # Safety guard: one-page files that remain too large cannot be solved safely without lossy raster compression.
        dummy = out_dir / _render_filename(rule.filename_template, src_path, part_counter[0], start, end)
        return [_output_record(src_path, dummy, start, end, rule, "maximum recursive split depth reached")]

    part_no = part_counter[0]
    part_counter[0] += 1
    if progress:
        progress(f"正在输出 {src_path.name} 第 {part_no} 卷：p{start}-{end}")
    out_path = _split_once(src_path, out_dir, rule, start, end, part_no)
    record = _output_record(src_path, out_path, start, end, rule)
    if record["output"]["compliant"]:
        return [record]

    pages = record["output_pages"] or (end - start + 1)
    too_many_pages = pages > rule.max_pages
    too_big = record["output_size_bytes"] > rule.max_size_bytes if record["output_size_bytes"] else False

    # If the output is too large and contains more than one page, split the source range into smaller chunks.
    if (too_many_pages or too_big) and start < end:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        range_pages = end - start + 1
        if too_big:
            # Halve range size to converge based on final measured output size, not estimate.
            next_chunk_size = max(1, range_pages // 2)
        else:
            next_chunk_size = max(1, rule.max_pages)
        records: list[dict[str, Any]] = []
        cur = start
        while cur <= end:
            nxt = min(end, cur + next_chunk_size - 1)
            records.extend(_recursive_process_range(src_path, out_dir, rule, cur, nxt, part_counter, progress, depth + 1))
            cur = nxt + 1
        return records

    # One page is still too large. Mark not compliant; lossy downsampling is deliberately not forced by default.
    return [record]


def process_pdf(src_path: str | Path, output_root: str | Path, rule: RuleConfig, progress: ProgressFn | None = None) -> dict[str, Any]:
    src_path = Path(src_path)
    output_root = Path(output_root)
    processed_dir = ensure_dir(output_root / "processed_pdfs")
    rule = rule.normalized()
    result: dict[str, Any] = {
        "original_path": str(src_path),
        "processing_mode": "subprocess_per_pdf_memory_safe",
        "outputs": [],
        "error": "",
    }
    try:
        size = file_size(src_path)
        with fitz.open(src_path) as doc:
            if doc.needs_pass:
                raise RuntimeError("PDF is encrypted and requires a password")
            page_count = doc.page_count

        chunk = initial_pages_per_part(page_count, size, rule)
        part_counter = [1]
        cur = 1
        while cur <= page_count:
            end = min(page_count, cur + chunk - 1)
            result["outputs"].extend(_recursive_process_range(src_path, processed_dir, rule, cur, end, part_counter, progress))
            cur = end + 1
    except Exception as exc:
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        gc.collect()
    return result
