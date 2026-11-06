from __future__ import annotations

from pathlib import Path


def read_resume(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    else:
        text = p.read_text()
    text = text.strip()
    if not text:
        raise ValueError(f"No text could be extracted from {p}")
    return text
