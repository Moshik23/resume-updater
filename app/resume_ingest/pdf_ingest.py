"""Extracts plain text lines from a .pdf resume.

No layout/style information survives this path -- pdf_ingest exists purely to
get resume content into the same flat {id, text} shape the Claude client
expects, regardless of input format. The apply side (docx_rebuild) never
tries to replicate the original PDF's visual layout.
"""

from pypdf import PdfReader

from app.models import ContentBlock


def extract(path: str) -> list[ContentBlock]:
    reader = PdfReader(path)
    blocks: list[ContentBlock] = []
    line_idx = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            blocks.append(ContentBlock(id=f"l{line_idx}", text=stripped, style_name=None))
            line_idx += 1
    return blocks
