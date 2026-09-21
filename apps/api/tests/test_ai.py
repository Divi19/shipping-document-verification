"""AI layer: consulted narrowly, believed only on verified evidence.

Every test drives a fake client, so nothing here makes a network call.
"""

from pathlib import Path
from typing import Any

import pytest

from app.ai.client import build_client, parse_json_object
from app.ai.field_resolver import LlmFieldResolver
from app.ai.oracle import LlmCategoryOracle
from app.models.email.schemas import EmailAttachment, EmailCategory, ParsedEmail
from app.pipeline import CaseOutcome, FieldName, Pipeline, ReviewReason
from app.pipeline.readers import PlainTextReader
from tests.test_pipeline import BL_TEXT, SI_TEXT, make_email, write_case

SI_WITH_ODD_LABEL = """SHIPPING INSTRUCTION
========================================

Shipper: APRIL FAR EAST (M) SDN BHD
Consignee (Non-Negotiable): EAST BRIGHT FZ-LLC
Notify: EAST BRIGHT FZ-LLC
Port of Loading (POL): NANTONG, CHINA (CNNTG)
POD: KARACHI, PAKISTAN (PKKHI)
Total Containers: 6 x 40'HC
Weight of goods as shipped: 131,058 KG
"""


class FakeClient:
    """Returns scripted answers and records the prompts it was given."""

    name = "fake"

    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate_json(self, prompt: str) -> dict[str, Any] | None:
        self.prompts.append(prompt)
        return self.answer


def email(subject: str, body: str = "", email_id: str = "email_900") -> ParsedEmail:
    return ParsedEmail(
        email_id=email_id,
        from_address="someone@example.com",
        subject=subject,
        body=body,
        attachments=[],
    )


class TestResponseParsing:
    def test_reads_json_wrapped_in_prose_or_fences(self) -> None:
        assert parse_json_object('Sure!\n```json\n{"category": "SPAM"}\n```') == {
            "category": "SPAM"
        }

    @pytest.mark.parametrize("text", ["no json here", "", "[1, 2, 3]", "{broken"])
    def test_unparseable_answers_are_discarded(self, text: str) -> None:
        assert parse_json_object(text) is None

    def test_no_api_key_means_no_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert build_client() is None


class TestCategoryOracle:
    def test_returns_the_model_category(self) -> None:
        client = FakeClient({"category": "INVOICE_QUERY", "reason": "asks about a credit note"})
        verdict = LlmCategoryOracle(client).classify(email("Credit note query"))
        assert verdict is not None
        category, reason = verdict
        assert category is EmailCategory.INVOICE_QUERY
        assert "credit note" in reason

    @pytest.mark.parametrize(
        "answer",
        [None, {}, {"category": "URGENT"}, {"category": ""}, {"reason": "no category"}],
    )
    def test_an_answer_outside_the_five_categories_is_refused(
        self, answer: dict[str, Any] | None
    ) -> None:
        assert LlmCategoryOracle(FakeClient(answer)).classify(email("Anything")) is None

    def test_the_prompt_carries_the_email(self) -> None:
        client = FakeClient({"category": "GENERAL", "reason": "notice"})
        LlmCategoryOracle(client).classify(email("Berthing report", body="Vessel arrives Monday."))
        assert "Berthing report" in client.prompts[0]
        assert "Vessel arrives Monday." in client.prompts[0]


class TestFieldResolver:
    def resolver(self, answer: dict[str, Any] | None) -> tuple[LlmFieldResolver, FakeClient]:
        client = FakeClient(answer)
        return LlmFieldResolver(client), client

    def test_recovers_a_field_whose_label_is_unknown(self) -> None:
        """ "Weight of goods as shipped" is in no synonym list, but it is there."""
        resolver, _ = self.resolver(
            {
                "gross_weight_kg": {
                    "value": "131,058 KG",
                    "evidence": "Weight of goods as shipped: 131,058 KG",
                }
            }
        )
        recovered = resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG])
        weight = recovered[FieldName.GROSS_WEIGHT_KG]
        assert weight.normalized == "131058"
        assert weight.evidence is not None
        assert weight.evidence.locator == "line 10"
        assert weight.note is not None and "evidence verified" in weight.note

    def test_a_value_whose_evidence_is_not_in_the_document_is_refused(self) -> None:
        """The model cannot invent a line and have it believed."""
        resolver, _ = self.resolver(
            {
                "gross_weight_kg": {
                    "value": "999,999 KG",
                    "evidence": "Gross Weight: 999,999 KG",
                }
            }
        )
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG]) == {}

    def test_a_value_missing_from_its_own_evidence_is_refused(self) -> None:
        """Real line, but the value does not appear in it."""
        resolver, _ = self.resolver(
            {
                "gross_weight_kg": {
                    "value": "99,999 KG",
                    "evidence": "Weight of goods as shipped: 131,058 KG",
                }
            }
        )
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG]) == {}

    @pytest.mark.parametrize("value", ["N/A", "TBA", "???", "", "   "])
    def test_placeholders_are_not_recoveries(self, value: str) -> None:
        resolver, _ = self.resolver(
            {"gross_weight_kg": {"value": value, "evidence": "Weight of goods as shipped: N/A"}}
        )
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG]) == {}

    def test_a_value_that_will_not_normalise_is_refused(self) -> None:
        resolver, _ = self.resolver(
            {
                "container_count": {
                    "value": "several",
                    "evidence": "Total Containers: 6 x 40'HC",
                }
            }
        )
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.CONTAINER_COUNT]) == {}

    def test_only_the_missing_fields_are_asked_for(self) -> None:
        resolver, client = self.resolver({})
        resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG])
        prompt = client.prompts[0]
        assert "gross_weight_kg" in prompt
        assert "consignee" not in prompt

    def test_nothing_is_asked_when_nothing_is_missing(self) -> None:
        resolver, client = self.resolver({})
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", []) == {}
        assert client.prompts == []

    def test_a_model_failure_is_survivable(self) -> None:
        resolver, _ = self.resolver(None)
        assert resolver.resolve(SI_WITH_ODD_LABEL, "si.txt", [FieldName.GROSS_WEIGHT_KG]) == {}


class TestOrchestratorWithAi:
    def test_a_recovered_field_completes_the_comparison(self, tmp_path: Path) -> None:
        """Without the model this pair escalates; with verified evidence it compares."""
        paths = write_case(tmp_path, "email_004", SI_WITH_ODD_LABEL, BL_TEXT)
        parsed = make_email("email_004", "Attached are the SI and draft BL.", paths)

        without_ai = Pipeline(dataset_root=tmp_path, readers=(PlainTextReader(),)).run(parsed)
        assert without_ai.outcome is CaseOutcome.NEEDS_REVIEW
        assert without_ai.review_reason is ReviewReason.MISSING_VALUE

        resolver = LlmFieldResolver(
            FakeClient(
                {
                    "gross_weight_kg": {
                        "value": "131,058 KG",
                        "evidence": "Weight of goods as shipped: 131,058 KG",
                    }
                }
            )
        )
        with_ai = Pipeline(
            dataset_root=tmp_path,
            readers=(PlainTextReader(),),
            field_resolver=resolver,
        ).run(parsed)
        assert with_ai.outcome is CaseOutcome.MISMATCH
        assert set(with_ai.defect_fields) == {FieldName.CONSIGNEE, FieldName.NOTIFY_PARTY}
        assert any(a.stage == "resolve_missing_fields" and a.ok for a in with_ai.attempts)

    def test_an_unverifiable_recovery_still_escalates(self, tmp_path: Path) -> None:
        paths = write_case(tmp_path, "email_004", SI_WITH_ODD_LABEL, BL_TEXT)
        resolver = LlmFieldResolver(
            FakeClient(
                {"gross_weight_kg": {"value": "131,058 KG", "evidence": "Gross Weight: invented"}}
            )
        )
        case = Pipeline(
            dataset_root=tmp_path,
            readers=(PlainTextReader(),),
            field_resolver=resolver,
        ).run(make_email("email_004", "Attached are the SI and draft BL.", paths))
        assert case.outcome is CaseOutcome.NEEDS_REVIEW
        assert case.review_reason is ReviewReason.MISSING_VALUE

    def test_the_deterministic_path_never_calls_the_model(self, tmp_path: Path) -> None:
        """Rules settle the known shapes; the model is for what they cannot."""
        client = FakeClient({"gross_weight_kg": {"value": "1", "evidence": "x"}})
        paths = write_case(tmp_path, "email_004", SI_TEXT, BL_TEXT)
        case = Pipeline(
            dataset_root=tmp_path,
            readers=(PlainTextReader(),),
            field_resolver=LlmFieldResolver(client),
        ).run(make_email("email_004", "Attached are the SI and draft BL.", paths))
        assert case.outcome is CaseOutcome.MISMATCH
        assert client.prompts == []


def test_attachment_shapes_stay_available() -> None:
    """Guard the helper import used above."""
    assert EmailAttachment(path="attachments/x.txt", filename="x.txt").filename == "x.txt"
