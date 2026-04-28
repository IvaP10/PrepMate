from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

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


def _parse_with_docling(file_path: str) -> ResumeParseResult:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(file_path)
    document = result.document

    if hasattr(document, "export_to_markdown"):
        text = document.export_to_markdown()
    elif hasattr(document, "export_to_text"):
        text = document.export_to_text()
    else:
        text = str(document)

    text = _normalize_text(text)
    if not text:
        raise ValueError("Docling returned empty text")

    return ResumeParseResult(
        text=text,
        parser="docling",
        links=_extract_links(text),
        metadata={"format": os.path.splitext(file_path)[1].lower()},
    )


def _parse_pdf_with_pymupdf(file_path: str) -> ResumeParseResult:
    import fitz

    doc = fitz.open(file_path)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    text = _normalize_text("\n".join(pages))
    if not text:
        raise ValueError("PDF text extraction returned empty text")
    return ResumeParseResult(
        text=text,
        parser="pymupdf",
        links=_extract_links(text),
        metadata={"pages": len(pages), "format": ".pdf"},
    )


def _parse_docx_with_python_docx(file_path: str) -> ResumeParseResult:
    from docx import Document

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


def parse_resume_structured(file_path: str) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        raise FileNotFoundError("Resume file not found")

    ext = os.path.splitext(file_path)[1].lower()
    errors: List[str] = []

    try:
        return _parse_with_docling(file_path).to_dict()
    except Exception as exc:
        logger.warning("Docling resume parsing failed, falling back: %s", exc)
        errors.append(f"docling: {type(exc).__name__}")

    try:
        if ext == ".pdf":
            result = _parse_pdf_with_pymupdf(file_path)
        elif ext == ".docx":
            result = _parse_docx_with_python_docx(file_path)
        else:
            raise ValueError("No fallback parser for this file type")
        parsed = result.to_dict()
        parsed["metadata"]["fallback_errors"] = errors
        return parsed
    except Exception as exc:
        errors.append(f"fallback: {type(exc).__name__}")
        logger.exception("All resume parsers failed")
        raise RuntimeError(
            "Failed to read resume. Upload a valid PDF or DOCX, or convert legacy .doc files to DOCX."
        ) from exc


def parse_resume(file_path: str) -> str:
    return parse_resume_structured(file_path)["text"]

