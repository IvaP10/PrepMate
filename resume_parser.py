# ============================================================================
# MODULE: resume_parser.py
# PURPOSE: Extract text + links + light metadata from PDF/DOCX resumes
#          (PyMuPDF for selectable PDFs, PaddleOCR fallback for scans, python-docx
#          for Word documents).
# STRUCTURE:
#   - ResumeParseResult dataclass (lines 23-32)
#   - URL_PATTERN regex (line 35-38)
#   - _normalize_text helper + per-format parsers (later in file)
#   - parse_resume_structured(file_path) entry point
# ENDPOINTS: none
# DEPENDS ON: pymupdf, paddleocr, python-docx (lazy imports)
# CONSUMED BY: pre_interview.py
# DATA TABLES: none (returns a dict; pre_interview.py persists into UserInfo.resume_json)
# ============================================================================

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List

logger = logging.getLogger("resume_parser")


@dataclass
class ResumeParseResult:
    text: str
    parser: str 
    links: List[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/[A-Za-z0-9_.-]+|github\.com/[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(?:dev|io|me|com|net|org)(?:/[^\s),;]*)?)",
    re.I,
)


def _normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\b([A-Z])\s+(?=[A-Z]\b)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _extract_links(text: str) -> List[str]:
    links: List[str] = []
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0).strip().rstrip(".,;)")
        if not url:
            continue
        if "." in url and not url.startswith("http"):
            url = f"https://{url}"
        links.append(url)
    return list(dict.fromkeys(links))


def _page_text_pymupdf(page) -> str:
    blocks = page.get_text("blocks") or []
    lines: List[str] = []
    for block in blocks:
        if len(block) >= 5 and isinstance(block[4], str):
            line = block[4].strip()
            if line:
                lines.append(line)
    if lines:
        return "\n".join(lines)
    return page.get_text("text", sort=True) or ""


def _parse_pdf_with_pymupdf(file_path: str, *, allow_ocr: bool = True) -> ResumeParseResult:
    import fitz

    doc = fitz.open(file_path)
    text_pages = [_page_text_pymupdf(page) for page in doc]
    ocr_pages: List[str] = []
    normalized_preview = _normalize_text("\n".join(text_pages))
    low_text_pages = [
        index
        for index, text in enumerate(text_pages)
        if len((text or "").strip()) < 80
    ]
    if allow_ocr and (low_text_pages or len(normalized_preview) < 250):
        ocr_pages = _ocr_pdf_pages(doc, low_text_pages or list(range(len(doc))))
    pages = text_pages + ocr_pages
    page_count = len(doc)
    doc.close()
    text = _normalize_text("\n".join(pages))
    if not text:
        raise ValueError("PDF text/OCR extraction returned empty text")
    parser = "pymupdf+paddleocr" if ocr_pages else "pymupdf"
    return ResumeParseResult(
        text=text,
        parser=parser,
        links=_extract_links(text),
        metadata={
            "pages": page_count,
            "ocr_pages": len(ocr_pages),
            "format": ".pdf",
        },
    )


_paddle_ocr = None
_paddle_loaded = False


def _get_paddle_ocr():
    global _paddle_ocr, _paddle_loaded
    if _paddle_loaded:
        return _paddle_ocr
    _paddle_loaded = True
    try:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        try:
            _paddle_ocr = PaddleOCR(
                lang="en",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
        except TypeError:
            _paddle_ocr = PaddleOCR(lang="en", use_angle_cls=True)
        logger.info("PaddleOCR resume parser loaded")
    except Exception:
        logger.error("PaddleOCR unavailable")
        _paddle_ocr = None
    return _paddle_ocr


def _ocr_pdf_pages(doc, page_indexes: Iterable[int]) -> List[str]:
    ocr = _get_paddle_ocr()
    if not ocr:
        return []

    import fitz

    extracted: List[str] = []
    for page_index in page_indexes:
        tmp_path = ""
        try:
            page = doc[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            pix.save(tmp_path)
            result = _run_paddle_ocr(ocr, tmp_path)
            page_text = _normalize_text("\n".join(_flatten_ocr_result(result)))
            if page_text:
                extracted.append(page_text)
        except Exception:
            logger.debug("PaddleOCR page %s failed", page_index)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    return extracted


def _run_paddle_ocr(ocr, image_path: str):
    if hasattr(ocr, "predict"):
        return ocr.predict(input=image_path)
    return ocr.ocr(image_path, cls=True)


def _flatten_ocr_result(value: Any) -> List[str]:
    texts: List[str] = []

    def visit(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, str):
            if re.search(r"[A-Za-z]", obj) and len(obj.strip()) > 1:
                texts.append(obj.strip())
            return
        if isinstance(obj, dict):
            for key in ("rec_text", "text", "transcription"):
                if isinstance(obj.get(key), str):
                    visit(obj[key])
            for key in ("rec_texts", "texts", "data", "res", "result"):
                if key in obj:
                    visit(obj[key])
            return
        if isinstance(obj, (list, tuple)):
            if len(obj) >= 2 and isinstance(obj[1], (list, tuple)) and obj[1] and isinstance(obj[1][0], str):
                visit(obj[1][0])
                return
            for item in obj:
                visit(item)
            return
        for attr in ("rec_text", "rec_texts", "text", "json"):
            try:
                if hasattr(obj, attr):
                    visit(getattr(obj, attr))
            except Exception:
                pass

    visit(value)
    return list(dict.fromkeys(texts))


def _parse_docx_with_python_docx(file_path: str) -> ResumeParseResult:
    from docx import Document  # type: ignore[import-not-found]

    doc = Document(file_path)
    parts = [para.text for para in doc.paragraphs if para.text and para.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = _normalize_text("\n".join(parts))
    if not text:
        raise ValueError("DOCX extraction returned empty text")
    return ResumeParseResult(
        text=text,
        parser="python-docx",
        links=_extract_links(text),
        metadata={"format": ".docx"},
    )


def parse_resume_structured(file_path: str, *, fast: bool = False) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        raise FileNotFoundError("Resume file not found")

    ext = os.path.splitext(file_path)[1].lower()
    errors: List[str] = []

    try:
        if ext == ".pdf":
            result = _parse_pdf_with_pymupdf(file_path, allow_ocr=not fast)
        elif ext == ".docx":
            result = _parse_docx_with_python_docx(file_path)
        else:
            raise ValueError("No parser for this file type")
        parsed = result.to_dict()
        parsed["metadata"]["fast"] = fast
        parsed["metadata"]["errors"] = errors
        return parsed
    except Exception as exc:
        errors.append(f"parser: {type(exc).__name__}")
        logger.error("All resume parsers failed")
        raise RuntimeError(
            "Failed to read resume. Upload a valid PDF or DOCX, or convert legacy .doc files to DOCX."
        ) from exc


def parse_resume(file_path: str) -> str:
    return parse_resume_structured(file_path)["text"]
