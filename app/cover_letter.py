"""Renders generated cover letter text into a plain, professional .docx."""

from docx import Document


def render_docx(cover_letter_text: str, output) -> None:
    doc = Document()
    for paragraph in cover_letter_text.split("\n\n"):
        stripped = paragraph.strip()
        if stripped:
            doc.add_paragraph(stripped)
    doc.save(output)
