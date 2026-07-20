"""Builds a human-readable summary of what changed (and what didn't), so a
user who prefers to edit their resume by hand can apply the same changes
themselves instead of relying on the generated docx.
"""

from app.models import GapAnalysis, SuggestedEdit

_EDIT_TYPE_LABELS = {
    "replace_phrase": "Replaced text",
    "insert_keyword": "Inserted keyword",
    "append_bullet": "Added new bullet",
    "new_bullet_after": "Added new bullet",
}


def _addressed_gap_requirements(
    accepted_edits: list[SuggestedEdit], failed_edit_ids: list[str]
) -> set[str]:
    """Requirements actually addressed by a successfully-applied edit --
    excludes edits that failed to apply, since those never touched the
    resume."""
    failed = set(failed_edit_ids)
    return {
        edit.related_gap
        for edit in accepted_edits
        if edit.related_gap and edit.edit_id not in failed
    }


def build_summary_markdown(
    analysis: GapAnalysis,
    accepted_edits: list[SuggestedEdit],
    failed_edit_ids: list[str],
) -> str:
    lines = ["# Resume tailoring summary", ""]

    if accepted_edits:
        lines.append("## Changes applied")
        lines.append("")
        for edit in accepted_edits:
            label = _EDIT_TYPE_LABELS.get(edit.type, edit.type)
            if edit.edit_id in failed_edit_ids:
                label += " (could not be applied automatically — add this yourself)"
            lines.append(f"- **{label}**")
            if edit.anchor_text:
                lines.append(f'  - Changed: "{edit.anchor_text}" → "{edit.new_text}"')
            else:
                lines.append(f'  - Added: "{edit.new_text}"')
            lines.append(f"  - Why: {edit.rationale}")
        lines.append("")

    addressed_gaps = _addressed_gap_requirements(accepted_edits, failed_edit_ids)
    remaining_gaps = [gap for gap in analysis.gaps if gap.requirement not in addressed_gaps]
    if remaining_gaps:
        lines.append("## Still worth addressing")
        lines.append("")
        lines.append("These job requirements weren't covered by an applied edit — consider adding them yourself:")
        lines.append("")
        for gap in remaining_gaps:
            lines.append(f"- **{gap.requirement}** — {gap.question_to_user}")
        lines.append("")

    if analysis.matches:
        lines.append("## Requirements your resume already covers")
        lines.append("")
        for match in analysis.matches:
            lines.append(f"- **{match.requirement}** — {match.evidence}")
        lines.append("")

    return "\n".join(lines)


def compute_match_score(
    analysis: GapAnalysis,
    accepted_edits: list[SuggestedEdit] | None = None,
    failed_edit_ids: list[str] | None = None,
) -> float:
    """Percentage of extracted JD requirements the resume covers.

    Call with no accepted_edits for the "before" score (requirements
    already matched in the original resume). Pass the applied edits and
    their failures for the "after" score.
    """
    total = len(analysis.extracted_requirements)
    if total == 0:
        return 100.0

    covered = {match.requirement for match in analysis.matches}
    if accepted_edits:
        covered |= _addressed_gap_requirements(accepted_edits, failed_edit_ids or [])

    return round(len(covered) / total * 100, 1)
