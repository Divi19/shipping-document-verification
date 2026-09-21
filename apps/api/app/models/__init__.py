"""Models package."""

from app.models.email.schemas import (
    ClassifiedEmail,
    EmailAttachment,
    EmailCategory,
    ParsedEmail,
)
from app.models.extraction import (
    ALL_COMPARISON_FIELDS,
    BoundingBox,
    ComparisonField,
    DocumentFieldCandidates,
    DocumentRole,
    EvidenceReference,
    ExtractionMethod,
    FieldCandidate,
    PageRegionLocator,
    TableCellLocator,
    TextSpanLocator,
)
from app.models.health import HealthResponse

__all__ = [
    "ALL_COMPARISON_FIELDS",
    "BoundingBox",
    "ClassifiedEmail",
    "ComparisonField",
    "DocumentFieldCandidates",
    "DocumentRole",
    "EmailAttachment",
    "EmailCategory",
    "EvidenceReference",
    "ExtractionMethod",
    "FieldCandidate",
    "HealthResponse",
    "PageRegionLocator",
    "ParsedEmail",
    "TableCellLocator",
    "TextSpanLocator",
]
