"""Compare the draft BL against the Shipping Instruction.

The SI is the reference. Comparison is deterministic: by the time values reach
this module they have already been normalised and carry their evidence, so the
only judgement left is equal / not equal / not decidable.

A field is *not decidable* when either side is missing, blank, a placeholder or
contradictory. That is uncertainty, not a discrepancy, and it must never be
reported as a mismatch.
"""

from .models import COMPARED_FIELDS, FieldComparison, FieldName, FieldValue


def compare_field(si: FieldValue, bl: FieldValue) -> FieldComparison:
    """Compare one field, leaving ``matches`` unset when it cannot be decided."""
    if not si.is_present or not bl.is_present:
        missing = "SI" if not si.is_present else "BL"
        note = si.note if not si.is_present else bl.note
        return FieldComparison(
            field=si.field,
            si=si,
            bl=bl,
            matches=None,
            note=f"not decidable: {missing} value unavailable ({note or 'not found'})",
        )

    matches = si.normalized == bl.normalized
    return FieldComparison(field=si.field, si=si, bl=bl, matches=matches)


def compare_documents(
    si_fields: dict[FieldName, FieldValue],
    bl_fields: dict[FieldName, FieldValue],
) -> list[FieldComparison]:
    """Compare all seven fields, in a fixed order."""
    return [
        compare_field(
            si_fields.get(field, FieldValue(field=field, note="not extracted")),
            bl_fields.get(field, FieldValue(field=field, note="not extracted")),
        )
        for field in COMPARED_FIELDS
    ]


def undecided_fields(comparisons: list[FieldComparison]) -> list[FieldName]:
    """Fields the system could not decide."""
    return [c.field for c in comparisons if c.matches is None]


def differing_fields(comparisons: list[FieldComparison]) -> list[FieldName]:
    """Fields where the BL contradicts the SI."""
    return [c.field for c in comparisons if c.matches is False]
