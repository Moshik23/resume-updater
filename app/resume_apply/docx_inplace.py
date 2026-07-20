"""Applies accepted edits to an existing .docx in place, preserving formatting.

Rule: never delete/replace a Paragraph object. Only mutate `run.text` on
existing runs (fully lossless when the anchor sits inside one run), or clone
an existing paragraph's XML element for a new bullet (inherits exact list
numbering/indentation/fonts from the paragraph it's cloned from).
"""

import copy

from docx import Document
from docx.text.paragraph import Paragraph

from app.models import SuggestedEdit
from app.resume_ingest.docx_ingest import get_paragraph_registry


def _replace_in_runs(paragraph: Paragraph, anchor_text: str, new_text: str) -> bool:
    """Replace the first occurrence of anchor_text, preserving run formatting.

    Returns False (no-op) if the anchor isn't found in the paragraph's text.
    """
    full_text = paragraph.text
    idx = full_text.find(anchor_text)
    if idx == -1:
        return False
    end = idx + len(anchor_text)

    offsets = []
    pos = 0
    for run in paragraph.runs:
        offsets.append((pos, pos + len(run.text), run))
        pos += len(run.text)

    overlapping = [(start, stop, run) for start, stop, run in offsets if stop > idx and start < end]
    if not overlapping:
        return False

    if len(overlapping) == 1:
        start, _stop, run = overlapping[0]
        local_start = idx - start
        local_end = end - start
        run.text = run.text[:local_start] + new_text + run.text[local_end:]
        return True

    # Anchor spans a run boundary: new text goes in the first run, the
    # overlapping tail of later runs is cleared. Known fidelity limitation —
    # those later runs' distinct formatting (e.g. a bold sub-word) is lost
    # for the overlapping span. Rare in practice.
    first_start, _first_stop, first_run = overlapping[0]
    local_start = idx - first_start
    first_run.text = first_run.text[:local_start] + new_text
    for start, stop, run in overlapping[1:]:
        local_end = min(end, stop) - start
        run.text = run.text[max(0, local_end):]
    return True


def _clone_paragraph_after(paragraph: Paragraph, new_text: str) -> Paragraph:
    new_element = copy.deepcopy(paragraph._p)
    paragraph._p.addnext(new_element)
    new_paragraph = Paragraph(new_element, paragraph._parent)

    runs = new_paragraph.runs
    if runs:
        runs[0].text = new_text
        for extra in runs[1:]:
            extra.text = ""
    else:
        new_paragraph.add_run(new_text)
    return new_paragraph


def apply_edits(source_path: str, edits: list[SuggestedEdit], output_path: str) -> list[str]:
    """Apply edits to a copy of the source docx, save to output_path.

    Returns the edit_ids that could not be applied (anchor not found, unknown
    block_id) so the caller can surface a warning instead of silently
    dropping a change.
    """
    doc = Document(source_path)
    registry = get_paragraph_registry(doc)
    # Tracks, per block_id, the paragraph new bullets should be inserted
    # after — starts at the original anchor, advances with each clone so
    # multiple new bullets for the same block_id land in submitted order
    # instead of all landing immediately after the original paragraph.
    insertion_points: dict[str, Paragraph] = dict(registry)
    failed: list[str] = []

    for edit in edits:
        anchor_paragraph = registry.get(edit.block_id)
        if anchor_paragraph is None:
            failed.append(edit.edit_id)
            continue

        if edit.type in ("replace_phrase", "insert_keyword"):
            if not edit.anchor_text or not _replace_in_runs(anchor_paragraph, edit.anchor_text, edit.new_text):
                failed.append(edit.edit_id)
        elif edit.type in ("append_bullet", "new_bullet_after"):
            insert_after = insertion_points[edit.block_id]
            new_paragraph = _clone_paragraph_after(insert_after, edit.new_text)
            insertion_points[edit.block_id] = new_paragraph
        else:
            failed.append(edit.edit_id)

    doc.save(output_path)
    return failed
