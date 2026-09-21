#!/usr/bin/env python3
"""Test classifier against SDOC data."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.email_classifier.classifier import EmailClassifier  # noqa: E402
from app.config import resolve_data_dir  # noqa: E402
from app.ingestion.parser import EmailParser  # noqa: E402
from app.models.email.schemas import EmailCategory  # noqa: E402


def main() -> None:
    inbox_path = resolve_data_dir(sys.argv[1] if len(sys.argv) > 1 else None)

    parser = EmailParser(str(inbox_path / "inbox"))
    emails = parser.parse_all()
    print(f"Parsed {len(emails)} emails from {inbox_path}/inbox")

    if not emails:
        print("ERROR: No emails found. Check the inbox path.")
        return

    classifier = EmailClassifier()
    results = classifier.classify_batch(emails)

    # Summary
    from collections import Counter

    counts = Counter(r.category.value for r in results)
    print("\n=== Classification Summary ===")
    for cat, count in counts.most_common():
        print(f"  {cat}: {count}")

    # Show samples per category
    print("\n=== Samples per Category ===")
    for cat in EmailCategory:
        cat_results = [r for r in results if r.category == cat]
        if cat_results:
            print(f"\n{cat.value} ({len(cat_results)}):")
            for r in cat_results[:3]:
                email = next(e for e in emails if e.email_id == r.email_id)
                print(f"  {r.email_id}: {email.subject[:80]}")
                print(f"    confidence={r.confidence:.2f} reason={r.reasoning}")

    # Export to JSON (submission format)
    submission: dict[str, dict[str, object]] = {}
    for r in results:
        submission[r.email_id] = {
            "category": r.category.value,
            "status": "OK",
            "review_reason": None,
            "defect_fields": [],
            "has_defect": False,
        }

    output_path = inbox_path / "classification_output.json"
    output_path.write_text(json.dumps(submission, indent=2))
    print(f"\n=== Output written to {output_path} ===")


if __name__ == "__main__":
    main()
