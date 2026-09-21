"""Contracts shared by document field extraction and evidence verification."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Strict base model for internal pipeline contracts."""

    model_config = ConfigDict(extra="forbid")


class ComparisonField(StrEnum):
    """The seven fields compared between an SI and draft BL."""

    SHIPPER = "shipper"
    CONSIGNEE = "consignee"
    NOTIFY_PARTY = "notify_party"
    PORT_OF_LOADING = "port_of_loading"
    PORT_OF_DISCHARGE = "port_of_discharge"
    CONTAINER_COUNT = "container_count"
    GROSS_WEIGHT_KG = "gross_weight_kg"


ALL_COMPARISON_FIELDS = frozenset(ComparisonField)


class DocumentRole(StrEnum):
    """Role assigned to a document in a comparison pair."""

    SHIPPING_INSTRUCTION = "shipping_instruction"
    BILL_OF_LADING = "bill_of_lading"


class ExtractionMethod(StrEnum):
    """Technique that produced a field candidate."""

    LABEL_MAP = "label_map"
    TABLE_MAP = "table_map"
    REGEX = "regex"
    SEMANTIC_MODEL = "semantic_model"
    OCR = "ocr"


class BoundingBox(ContractModel):
    """Rectangle in source-document coordinates."""

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(gt=0)
    y1: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        """Require a box with positive width and height."""
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("bounding box must have positive width and height")
        return self


class TextSpanLocator(ContractModel):
    """Half-open character span in extracted plain text."""

    kind: Literal["text_span"] = "text_span"
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require ordered character and optional line ranges."""
        if self.end <= self.start:
            raise ValueError("text span end must be greater than start")
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be provided together")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must not precede line_start")
        return self


class TableCellLocator(ContractModel):
    """Cell position in an extracted table."""

    kind: Literal["table_cell"] = "table_cell"
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    sheet_name: str | None = None
    page_number: int | None = Field(default=None, ge=1)


class PageRegionLocator(ContractModel):
    """Rectangular region on a rendered document page."""

    kind: Literal["page_region"] = "page_region"
    page_number: int = Field(ge=1)
    bounding_box: BoundingBox


EvidenceLocator = Annotated[
    TextSpanLocator | TableCellLocator | PageRegionLocator,
    Field(discriminator="kind"),
]


class EvidenceReference(ContractModel):
    """Auditable source evidence supporting an extracted candidate."""

    source_filename: str = Field(min_length=1)
    locator: EvidenceLocator
    source_text: str = Field(min_length=1)


class FieldCandidate(ContractModel):
    """One possible raw value for a required comparison field."""

    field: ComparisonField
    document_role: DocumentRole
    raw_label: str = Field(min_length=1)
    raw_value: str = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(min_length=1)
    extraction_method: ExtractionMethod
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def reject_blank_values(self) -> Self:
        """Reject whitespace-only labels, values, and evidence text."""
        if not self.raw_label.strip():
            raise ValueError("raw_label must contain non-whitespace text")
        if not self.raw_value.strip():
            raise ValueError("raw_value must contain non-whitespace text")
        if any(not item.source_text.strip() for item in self.evidence):
            raise ValueError("evidence source_text must contain non-whitespace text")
        return self


class DocumentFieldCandidates(ContractModel):
    """All field candidates extracted from one assigned document."""

    document_role: DocumentRole
    source_filename: str = Field(min_length=1)
    candidates: list[FieldCandidate] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidate_sources(self) -> Self:
        """Keep every candidate bound to this document and role."""
        for candidate in self.candidates:
            if candidate.document_role != self.document_role:
                raise ValueError("candidate document role does not match its document")
            if any(
                evidence.source_filename != self.source_filename for evidence in candidate.evidence
            ):
                raise ValueError("candidate evidence must reference its source document")
        return self

    def candidates_for(self, field: ComparisonField) -> list[FieldCandidate]:
        """Return all candidates for a field without choosing between them."""
        return [candidate for candidate in self.candidates if candidate.field == field]
