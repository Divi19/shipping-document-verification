"""Run the verification pipeline over the inbox and write a submission.

    uv --directory apps/api run python scripts/run_pipeline.py
    uv --directory apps/api run python scripts/run_pipeline.py --text-only --score

``--text-only`` restricts reading to plain text, which is the quickest way to
see the effect of a change without the extraction extras installed.
"""

import argparse
import collections
import sys
from pathlib import Path

# Allow both "python -m scripts.run_pipeline" and "python scripts/run_pipeline.py".
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import LOCAL_DATA, data_dir  # noqa: E402
from app.pipeline import CaseRecord, Pipeline, write_submission  # noqa: E402
from app.pipeline.inbox import load_emails  # noqa: E402
from app.pipeline.readers import PlainTextReader, default_readers  # noqa: E402

DEFAULT_OUTPUT = LOCAL_DATA / "submission.json"


def summarise(cases: list[CaseRecord]) -> str:
    """A one-glance view of what the run decided."""
    outcomes = collections.Counter(case.outcome.value for case in cases)
    reasons = collections.Counter(
        case.review_reason.value for case in cases if case.review_reason is not None
    )
    lines = [f"{len(cases)} emails processed", "", "outcomes:"]
    lines += [f"  {name:<20} {count}" for name, count in sorted(outcomes.items())]
    if reasons:
        lines += ["", "escalation reasons:"]
        lines += [f"  {name:<20} {count}" for name, count in sorted(reasons.items())]
    defects = [case for case in cases if case.defect_fields]
    lines += ["", f"cases with a discrepancy: {len(defects)}"]
    if defects:
        fields = collections.Counter(
            field.value for case in defects for field in case.defect_fields
        )
        lines += [f"  {name:<20} {count}" for name, count in fields.most_common()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="dataset root holding inbox/ and attachments/ (default: $SDOC_DATA_DIR)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="submission path")
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="read only .txt attachments; PDF/Word/Excel become NEEDS_REVIEW",
    )
    parser.add_argument("--limit", type=int, default=None, help="process the first N emails only")
    parser.add_argument(
        "--score",
        action="store_true",
        help="score the result afterwards (needs the organisers' ground truth)",
    )
    args = parser.parse_args(argv)

    dataset_root = args.data or data_dir()
    emails = load_emails(dataset_root)
    if args.limit is not None:
        emails = emails[: args.limit]

    readers = (PlainTextReader(),) if args.text_only else default_readers()
    cases = Pipeline(dataset_root=dataset_root, readers=readers).run_all(emails)

    destination = write_submission(cases, args.out)
    print(summarise(cases))
    print(f"\nsubmission written to {destination}")

    if args.score:
        from scripts.score_submission import score_file

        print()
        print(score_file(destination))
    return 0


if __name__ == "__main__":
    sys.exit(main())
