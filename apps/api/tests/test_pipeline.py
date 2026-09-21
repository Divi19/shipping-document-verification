"""Pipeline tests, using document shapes taken from the supplied dataset."""

import json
from pathlib import Path

import pytest

from app.models.email.schemas import EmailAttachment, EmailCategory, ParsedEmail
from app.pipeline import (
    CaseOutcome,
    DocumentRole,
    FieldName,
    Pipeline,
    ReviewReason,
    build_submission,
)
from app.pipeline.compare import compare_documents
from app.pipeline.documents import detect_role, is_readable
from app.pipeline.fields import extract_fields, match_field
from app.pipeline.normalize import (
    is_missing,
    normalize_party,
    normalize_place,
    parse_container_count,
    parse_weight_kg,
    party_names_agree,
)
from app.pipeline.readers import PlainTextReader, ReaderError
from app.pipeline.status import asserts_documents_attached

SI_TEXT = """SHIPPING INSTRUCTION
========================================

Shipper: APRIL FAR EAST (M) SDN BHD
  TOWER 2, AVENUE 5, LEVEL 6; BANGSAR SOUTH CITY; 59200 KUALA LUMPUR, MALAYSIA
Consignee (Non-Negotiable): EAST BRIGHT FZ-LLC
  RAKEZ AMENITY CENTER; AL HAMRA INDUSTRIAL ZONE, RAK, UAE
Notify: EAST BRIGHT FZ-LLC
Port of Loading (POL): NANTONG, CHINA (CNNTG)
POD: KARACHI, PAKISTAN (PKKHI)
Total Containers: 6 x 40'HC
Gross Wt (kgs): 131,058 KG
Booking Ref: ONEYSINF32871
"""

BL_TEXT = """BILL OF LADING (DRAFT)
========================================

SHIPPER: APRIL FAR EAST (M) SDN BHD
  TOWER 2, AVENUE 5, LEVEL 6; BANGSAR SOUTH CITY; 59200 KUALA LUMPUR, MALAYSIA
To the Order of: UAB NOVAKOPA
  RAKEZ AMENITY CENTER; AL HAMRA INDUSTRIAL ZONE, RAK, UAE
Notify Party/Intermediate Consignee: UAB NOVAKOPA
Port of Loading (POL): NANTONG, CHINA
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 6 x 40'HC
Gross Weight (KG): 131,058 KG
Booking Ref: ONEYSINF32871
"""


class TestNormalisation:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("6 x 40'HC", 6), ("12 X 20'FCL", 12), ("15 x 20'GP", 15), ("6", 6), ("", None)],
    )
    def test_container_count(self, value: str, expected: int | None) -> None:
        assert parse_container_count(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("131,058 KG", 131058.0),
            ("243588", 243588.0),
            ("243,588", 243588.0),
            ("138 MT", 138000.0),  # unit matters: 138 MT is not 138 kg
        ],
    )
    def test_weight(self, value: str, expected: float) -> None:
        assert parse_weight_kg(value) == expected

    def test_locode_suffix_is_formatting_not_content(self) -> None:
        assert normalize_place("NANTONG, CHINA (CNNTG)") == normalize_place("NANTONG, CHINA")

    def test_company_suffix_spelling(self) -> None:
        assert normalize_party("KPP-ANTALIS (SINGAPORE) PTE. LTD.") == normalize_party(
            "KPP-ANTALIS PTE LTD"
        )

    def test_different_companies_stay_different(self) -> None:
        assert normalize_party("EAST BRIGHT FZ-LLC") != normalize_party("UAB NOVAKOPA")

    @pytest.mark.parametrize("value", ["N/A", "TBA", "???", "_______", "", "   ", "-"])
    def test_placeholders_are_missing(self, value: str) -> None:
        assert is_missing(value)

    def test_real_value_is_not_missing(self) -> None:
        assert not is_missing("131,058 KG")


class TestLabels:
    @pytest.mark.parametrize(
        ("label", "field"),
        [
            ("Consignee (Non-Negotiable)", FieldName.CONSIGNEE),
            ("To the Order of", FieldName.CONSIGNEE),
            ("Load Port", FieldName.PORT_OF_LOADING),
            ("Port of Loading (POL)", FieldName.PORT_OF_LOADING),
            ("POD", FieldName.PORT_OF_DISCHARGE),
            ("Notify Party/Intermediate Consignee", FieldName.NOTIFY_PARTY),
            ("No. of Containers or Packages", FieldName.CONTAINER_COUNT),
            ("Gross Wt (kgs)", FieldName.GROSS_WEIGHT_KG),
            ("Shipper (Principal or Seller)", FieldName.SHIPPER),
        ],
    )
    def test_synonyms(self, label: str, field: FieldName) -> None:
        assert match_field(label) is field

    def test_bilingual_label(self) -> None:
        assert match_field("Gross Wt (kgs) (毛重 KGS)") is FieldName.GROSS_WEIGHT_KG

    def test_net_weight_is_not_gross_weight(self) -> None:
        assert match_field("NET WEIGHT") is None


class TestExtraction:
    def test_seven_fields_from_plain_text(self) -> None:
        fields = extract_fields(SI_TEXT, "email_004_SI.txt")
        assert fields[FieldName.CONSIGNEE].normalized == "EAST BRIGHT FZ LLC"
        assert fields[FieldName.CONTAINER_COUNT].normalized == "6"
        assert fields[FieldName.GROSS_WEIGHT_KG].normalized == "131058"
        assert all(value.is_present for value in fields.values())

    def test_every_value_carries_evidence(self) -> None:
        fields = extract_fields(SI_TEXT, "email_004_SI.txt")
        weight = fields[FieldName.GROSS_WEIGHT_KG]
        assert weight.evidence is not None
        assert weight.evidence.source == "email_004_SI.txt"
        assert "131,058" in weight.evidence.snippet
        assert weight.raw == "131,058 KG"

    def test_party_address_lines_do_not_join_the_value(self) -> None:
        """The party name identifies the party; its address block is context.

        Parentheticals are dropped on both sides, so "APRIL FAR EAST (M) SDN
        BHD" normalises without the "(M)" - consistent, and the raw value is
        kept for the report.
        """
        shipper = extract_fields(SI_TEXT, "si.txt")[FieldName.SHIPPER]
        assert shipper.normalized == "APRIL FAR EAST SDN BHD"
        assert shipper.raw == "APRIL FAR EAST (M) SDN BHD"
        assert "TOWER 2" not in (shipper.normalized or "")

    def test_total_wins_over_per_container_rows(self) -> None:
        """A container table lists a weight per container and then the total."""
        text = (
            "BILL OF LADING (DRAFT)\n"
            "| CONTAINER NO. | DESCRIPTION | GROSS WEIGHT (KG) |\n"
            "| PURJ4736471 | 40'HC PAPER | 21,887 |\n"
            "| WBFO6773592 | 40'HC PAPER | 21,887 |\n"
            "Container Count: 6 x 40'HC\n"
            "TOTAL Gross Weight (KG): 131,322 KG\n"
        )
        fields = extract_fields(text, "bl.pdf")
        assert fields[FieldName.GROSS_WEIGHT_KG].normalized == "131322"

    def test_spreadsheet_markdown_rows(self) -> None:
        text = (
            "| APRIL FINE PAPER TRADING |  |\n"
            "| BL INSTRUCTION | 3658202970 |\n"
            "| Load Port | SINGAPORE |\n"
            "| Container Count | 12 x 20'FCL |\n"
            "| GROSS WEIGHT | 243588 |\n"
        )
        fields = extract_fields(text, "si.xlsx")
        assert fields[FieldName.PORT_OF_LOADING].normalized == "SINGAPORE"
        assert fields[FieldName.CONTAINER_COUNT].normalized == "12"
        assert fields[FieldName.GROSS_WEIGHT_KG].normalized == "243588"

    def test_word_style_label_above_value(self) -> None:
        text = "BILL OF LADING (DRAFT)\nGross Wt (kgs) (毛重 KGS)\n243,588\n"
        fields = extract_fields(text, "bl.docx")
        assert fields[FieldName.GROSS_WEIGHT_KG].normalized == "243588"

    def test_blank_label_does_not_borrow_the_next_field(self) -> None:
        """email_519 leaves the count blank; the weight line must not fill it in."""
        text = (
            "SHIPPING INSTRUCTION\nNo. of Containers or Packages:\nGross Weight (KGS): 70,572 KG\n"
        )
        fields = extract_fields(text, "si.txt")
        count = fields[FieldName.CONTAINER_COUNT]
        assert not count.is_present
        assert fields[FieldName.GROSS_WEIGHT_KG].normalized == "70572"

    def test_placeholder_value_is_not_a_value(self) -> None:
        fields = extract_fields("SHIPPING INSTRUCTION\nGross Weight (KGS): N/A\n", "si.txt")
        assert not fields[FieldName.GROSS_WEIGHT_KG].is_present

    def test_contradictory_readings_are_refused(self) -> None:
        text = "SHIPPING INSTRUCTION\nLoad Port: SINGAPORE\nPort of Loading: BUATAN, INDONESIA\n"
        fields = extract_fields(text, "si.txt")
        loading = fields[FieldName.PORT_OF_LOADING]
        assert not loading.is_present
        assert loading.note is not None and "conflicting" in loading.note


class TestDocumentIdentity:
    @pytest.mark.parametrize(
        ("header", "role"),
        [
            ("SHIPPING INSTRUCTION", DocumentRole.SHIPPING_INSTRUCTION),
            ("BL INSTRUCTION", DocumentRole.SHIPPING_INSTRUCTION),
            ("BILL OF LADING INSTRUCTION", DocumentRole.SHIPPING_INSTRUCTION),
            ("BILL OF LADING (DRAFT)", DocumentRole.BILL_OF_LADING),
            ("COMMERCIAL INVOICE", DocumentRole.OTHER),
            ("CERTIFICATE OF ORIGIN", DocumentRole.OTHER),
            ("PACKING LIST", DocumentRole.OTHER),
        ],
    )
    def test_role_detection(self, header: str, role: DocumentRole) -> None:
        assert detect_role(f"{header}\n====\nShipper: ACME\n") is role

    def test_bl_number_inside_an_si_does_not_make_it_a_bl(self) -> None:
        text = "SHIPPING INSTRUCTION\n====\nB/L No.: OOLU5146270482\nShipper: ACME\n"
        assert detect_role(text) is DocumentRole.SHIPPING_INSTRUCTION

    def test_empty_document_is_unreadable(self) -> None:
        assert not is_readable("")
        assert not is_readable("   \n\n")


class TestComparison:
    def test_real_defect_pair(self) -> None:
        """email_004: consignee and notify party changed, everything else agrees."""
        comparisons = compare_documents(
            extract_fields(SI_TEXT, "si.txt"), extract_fields(BL_TEXT, "bl.txt")
        )
        differing = {c.field for c in comparisons if c.is_defect}
        assert differing == {FieldName.CONSIGNEE, FieldName.NOTIFY_PARTY}

    def test_label_and_format_differences_are_not_defects(self) -> None:
        comparisons = compare_documents(
            extract_fields(SI_TEXT, "si.txt"), extract_fields(BL_TEXT, "bl.txt")
        )
        by_field = {c.field: c for c in comparisons}
        assert by_field[FieldName.PORT_OF_LOADING].matches is True
        assert by_field[FieldName.CONTAINER_COUNT].matches is True

    def test_missing_value_is_undecidable_not_a_mismatch(self) -> None:
        si = extract_fields(
            SI_TEXT.replace("Gross Wt (kgs): 131,058 KG", "Gross Wt (kgs): N/A"), "si"
        )
        comparisons = compare_documents(si, extract_fields(BL_TEXT, "bl"))
        weight = next(c for c in comparisons if c.field is FieldName.GROSS_WEIGHT_KG)
        assert weight.matches is None
        assert not weight.is_defect


class TestAttachmentClaims:
    @pytest.mark.parametrize(
        "body",
        [
            "Please compare the SI and draft BL for 070500263211 and confirm "
            "(attachments appear to have been dropped).",
            "Please compare the SI and draft BL for I756178688 and confirm "
            "(the draft BL is still missing).",
            "Attached are the SI and draft BL for OC 5ALT-01226.",
        ],
    )
    def test_sender_says_documents_are_attached(self, body: str) -> None:
        assert asserts_documents_attached(body)

    def test_request_to_send_documents_is_not_a_claim(self) -> None:
        assert not asserts_documents_attached(
            "Please assist to send the draft BL for 00159416 for checking asap."
        )

    def test_external_sender_banner_is_not_a_claim(self) -> None:
        body = (
            "WARNING: This email originated outside of our organisation. As a security "
            "measure, please exercise caution with E-Mail content and any links or "
            "attachments.\n\nPlease assist to send the draft BL for checking."
        )
        assert not asserts_documents_attached(body)


class TestReaders:
    def test_binary_file_with_text_extension_fails_cleanly(self, tmp_path: Path) -> None:
        path = tmp_path / "email_999_BL.txt"
        path.write_bytes(b"%PDF-1.5\n\x00\x9d\x8f binary")
        with pytest.raises(ReaderError):
            PlainTextReader().read(path)

    def test_empty_file_fails_cleanly(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.txt"
        path.write_text("")
        with pytest.raises(ReaderError):
            PlainTextReader().read(path)


def write_case(root: Path, email_id: str, si: str | None, bl: str | None) -> list[str]:
    (root / "attachments").mkdir(parents=True, exist_ok=True)
    paths = []
    for role, text in (("SI", si), ("BL", bl)):
        if text is None:
            continue
        name = f"attachments/{email_id}_{role}.txt"
        (root / name).write_text(text, encoding="utf-8")
        paths.append(name)
    return paths


def make_email(email_id: str, body: str, attachments: list[str]) -> ParsedEmail:
    return ParsedEmail(
        email_id=email_id,
        from_address="docs@vitalsolutions.sg",
        subject="TO CONFIRM DOCS _ 5RVN-23924 _ HOCHIMINH CITY_VIETNAM",
        body=body,
        attachments=[
            EmailAttachment(path=path, filename=path.rsplit("/", 1)[-1]) for path in attachments
        ],
    )


class TestOrchestrator:
    def pipeline(self, root: Path) -> Pipeline:
        return Pipeline(dataset_root=root, readers=(PlainTextReader(),))

    def test_mismatch_case_reports_only_the_differing_fields(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_004", SI_TEXT, BL_TEXT)
        case = self.pipeline(tmp_path).run(
            make_email("email_004", "Attached are the SI and BL.", paths)
        )
        assert case.outcome is CaseOutcome.MISMATCH
        assert set(case.defect_fields) == {FieldName.CONSIGNEE, FieldName.NOTIFY_PARTY}

    def test_clean_case_is_verified(self, tmp_path: Path) -> None:
        paths = write_case(
            tmp_path,
            "email_005",
            SI_TEXT,
            SI_TEXT.replace("SHIPPING INSTRUCTION", "BILL OF LADING (DRAFT)"),
        )
        case = self.pipeline(tmp_path).run(
            make_email("email_005", "Attached are the SI and BL.", paths)
        )
        assert case.outcome is CaseOutcome.VERIFIED
        assert case.defect_fields == []

    def test_request_to_send_documents_is_not_an_escalation(self, tmp_path: Path) -> None:
        email = make_email("email_061", "Please assist to send the draft BL for checking asap.", [])
        case = self.pipeline(tmp_path).run(email)
        assert case.outcome is CaseOutcome.AWAITING_DOCUMENTS
        assert case.review_reason is None

    def test_dropped_attachments_escalate(self, tmp_path: Path) -> None:
        email = make_email(
            "email_506",
            "Please compare the SI and draft BL for 070500263211 and confirm "
            "(attachments appear to have been dropped).",
            [],
        )
        case = self.pipeline(tmp_path).run(email)
        assert case.outcome is CaseOutcome.NEEDS_REVIEW
        assert case.review_reason is ReviewReason.MISSING_ATTACHMENT

    def test_invoice_in_place_of_the_bl_escalates(self, tmp_path: Path) -> None:
        invoice = "COMMERCIAL INVOICE\n====\nInvoice No.: 5250078266\nSeller: APRIL\n"
        paths = write_case(tmp_path, "email_501", SI_TEXT, invoice)
        case = self.pipeline(tmp_path).run(
            make_email("email_501", "Attached are the SI and BL.", paths)
        )
        assert case.outcome is CaseOutcome.NEEDS_REVIEW
        assert case.review_reason is ReviewReason.WRONG_DOC_TYPE

    def test_unreadable_document_escalates_and_is_never_compared(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_511", SI_TEXT, "   ")
        case = self.pipeline(tmp_path).run(
            make_email("email_511", "Attached SI and draft BL.", paths)
        )
        assert case.outcome is CaseOutcome.NEEDS_REVIEW
        assert case.review_reason is ReviewReason.UNREADABLE
        assert case.comparisons == []

    def test_blank_required_value_escalates_rather_than_mismatching(self, tmp_path: Path) -> None:
        si = SI_TEXT.replace("Gross Wt (kgs): 131,058 KG", "Gross Wt (kgs): N/A")
        paths = write_case(tmp_path, "email_516", si, BL_TEXT)
        case = self.pipeline(tmp_path).run(
            make_email("email_516", "Attached are the SI and BL.", paths)
        )
        assert case.outcome is CaseOutcome.NEEDS_REVIEW
        assert case.review_reason is ReviewReason.MISSING_VALUE

    def test_non_comparison_email_is_not_applicable(self, tmp_path: Path) -> None:
        email = ParsedEmail(
            email_id="email_072",
            from_address="support@webmail-verify.co",
            subject="Increase your shipping revenue with this ONE weird trick",
            body="",
            attachments=[],
        )
        case = self.pipeline(tmp_path).run(email)
        assert case.category is EmailCategory.SPAM
        assert case.outcome is CaseOutcome.NOT_APPLICABLE

    def test_every_stage_is_recorded(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_004", SI_TEXT, BL_TEXT)
        case = self.pipeline(tmp_path).run(
            make_email("email_004", "Attached are the SI and BL.", paths)
        )
        stages = [attempt.stage for attempt in case.attempts]
        assert stages[0] == "classify"
        assert stages[-1] == "decide"
        assert "read_document" in stages and "compare" in stages

    def test_failed_reads_stay_in_the_history(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_511", SI_TEXT, "")
        (tmp_path / paths[1]).write_bytes(b"%PDF-1.5 broken")
        case = self.pipeline(tmp_path).run(
            make_email("email_511", "Attached SI and draft BL.", paths)
        )
        failures = [a for a in case.attempts if a.stage == "read_document" and not a.ok]
        assert failures, "a failed read must be recorded, not silently dropped"

    def test_retries_are_bounded(self, tmp_path: Path) -> None:
        calls: list[str] = []

        class AlwaysFails:
            name = "always-fails"

            def can_read(self, path: Path) -> bool:
                return True

            def read(self, path: Path) -> str:
                calls.append(path.name)
                raise ReaderError("nope")

        paths = write_case(tmp_path, "email_511", SI_TEXT, BL_TEXT)
        pipeline = Pipeline(
            dataset_root=tmp_path,
            readers=(AlwaysFails(), AlwaysFails(), AlwaysFails()),
            max_attempts_per_document=2,
        )
        case = pipeline.run(make_email("email_511", "Attached SI and draft BL.", paths))
        assert len(calls) == 4  # two documents, at most two attempts each
        assert case.outcome is CaseOutcome.NEEDS_REVIEW


class TestSubmission:
    def test_awaiting_documents_is_submitted_as_ok_but_kept_distinct(self, tmp_path: Path) -> None:
        pipeline = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),))
        case = pipeline.run(
            make_email("email_061", "Please assist to send the draft BL for checking.", [])
        )
        entry = build_submission([case])["email_061"]
        assert case.outcome is CaseOutcome.AWAITING_DOCUMENTS  # what the reviewer sees
        assert entry["status"] == "OK"  # what the scoreboard expects
        assert entry["has_defect"] is False

    def test_mismatch_entry_lists_the_fields(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_004", SI_TEXT, BL_TEXT)
        pipeline = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),))
        case = pipeline.run(make_email("email_004", "Attached are the SI and BL.", paths))
        entry = build_submission([case])["email_004"]
        assert entry["status"] == "MISMATCH"
        assert entry["has_defect"] is True
        assert sorted(entry["defect_fields"]) == ["consignee", "notify_party"]
        assert entry["review_reason"] is None

    def test_entries_are_json_serialisable(self, tmp_path: Path) -> None:
        pipeline = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),))
        case = pipeline.run(make_email("email_061", "Please send the draft BL.", []))
        assert json.loads(json.dumps(build_submission([case])))


class TestLayoutDifferencesAreNotDefects:
    """Regressions from running the real Excel/Word pairs.

    Each of these produced a false discrepancy, which is exactly the failure
    the accuracy target is about: the documents agreed, the layout did not.
    """

    def test_escaped_pipe_does_not_truncate_a_cell(self) -> None:
        """Markdown escapes a literal pipe; splitting on it cut values in half."""
        text = "BL INSTRUCTION\n| Consignee | AL GURG STATIONERY LLC \| P.O. BOX 5069 |\n"
        consignee = extract_fields(text, "si.xlsx")[FieldName.CONSIGNEE]
        assert consignee.normalized == "AL GURG STATIONERY LLC P O BOX 5069"

    def test_address_on_one_side_only_is_not_a_discrepancy(self) -> None:
        """The Word BL keeps name and address in one cell; the Excel SI does not."""
        si = extract_fields("BL INSTRUCTION\n| Consignee | AL GURG STATIONERY LLC |\n", "si.xlsx")
        bl = extract_fields(
            "BILL OF LADING (DRAFT)\n"
            "| Consignee | AL GURG STATIONERY LLC P.O. BOX 5069 DUBAI, UAE |\n",
            "bl.docx",
        )
        consignee = next(c for c in compare_documents(si, bl) if c.field is FieldName.CONSIGNEE)
        assert consignee.matches is True
        assert consignee.note == "same party, address included on one side"

    def test_a_different_party_is_still_a_discrepancy(self) -> None:
        si = extract_fields("BL INSTRUCTION\n| Consignee | EAST BRIGHT FZ-LLC |\n", "si.xlsx")
        bl = extract_fields(
            "BILL OF LADING (DRAFT)\n| Consignee | UAB NOVAKOPA P.O. BOX 5069 |\n", "bl.docx"
        )
        consignee = next(c for c in compare_documents(si, bl) if c.field is FieldName.CONSIGNEE)
        assert consignee.matches is False

    def test_a_metadata_header_is_not_document_content(self) -> None:
        """A failed PDF extraction returns only its metadata block.

        Counting that as text made an unreadable scan look like a readable
        document with no fields, which escalated for the wrong reason.
        """
        metadata_only = (
            "---\n"
            "source_file: email_313_SI.pdf\n"
            "content_type: application/pdf\n"
            "extractor: PDFExtractor\n"
            "error: All extraction methods failed\n"
            "---"
        )
        assert not is_readable(metadata_only)


class TestPartyNameAgreement:
    """Same party with its address on one side only, versus a different party
    that happens to share a name prefix."""

    @pytest.mark.parametrize(
        ("si", "bl"),
        [
            ("AL GURG STATIONERY LLC", "AL GURG STATIONERY LLC P O BOX 5069 DUBAI"),
            ("ROXCEL TRADING GMBH", "ROXCEL TRADING GMBH OPERNRING 3 5 1010 VIENNA AUSTRIA"),
            ("NAGAPPA EXPORTS", "NAGAPPA EXPORTS NEW NO 23 L BLOCK 17TH STREET"),
            (
                "APRIL FINE PAPER TRADING",
                "APRIL FINE PAPER TRADING ON BEHALF OF VITAL SOLUTIONS PTE LTD",
            ),
        ],
    )
    def test_address_on_one_side_is_the_same_party(self, si: str, bl: str) -> None:
        assert party_names_agree(si, bl)

    @pytest.mark.parametrize(
        ("si", "bl"),
        [
            # email_145: the Singapore and Middle East arms are different companies.
            ("APRIL FINE PAPER TRADING", "APRIL FINE PAPER TRADING FZE"),
            ("APRIL FINE PAPER TRADING", "APRIL FINE PAPER TRADING FZE 813 4 EA DUBAI"),
            ("VITAL SOLUTIONS", "VITAL SOLUTIONS PTE LTD"),
            # Extra words with no number and no address opener are not an address.
            ("EAST BRIGHT", "EAST BRIGHT PAPER MILLS"),
            ("EAST BRIGHT FZ LLC", "UAB NOVAKOPA"),
        ],
    )
    def test_a_different_entity_sharing_a_prefix_is_a_different_party(
        self, si: str, bl: str
    ) -> None:
        assert not party_names_agree(si, bl)
