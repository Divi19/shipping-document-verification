"""Score a submission against the organisers' ground truth.

The organisers confirmed (announcement, 19 September 2026) that the Docker
archive's ``ground_truth.json`` is for teams to evaluate their own work; the
"do not distribute" line in its README is stale. This script therefore reads
both the ground truth *and* the organisers' own ``scoring.py`` from the
gitignored ``local-data/`` directory, so the numbers we quote are produced by
their scorer rather than by a re-implementation of it.

Nothing here is imported by the application: scoring is a development tool and
the answer key must never influence runtime behaviour.

    uv --directory apps/api run python scripts/score_submission.py local-data/submission.json
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

# Allow both "python -m scripts.score_submission" and running the file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import LOCAL_DATA  # noqa: E402

DOCKER_BUNDLE = LOCAL_DATA / "sdoc-hackathon-docker"
GROUND_TRUTH = DOCKER_BUNDLE / "data_v2" / "ground_truth.json"
SCORING_MODULE = DOCKER_BUNDLE / "server" / "scoring.py"


def _load_scoring(path: Path) -> ModuleType:
    """Import the organisers' scoring module from local-data/."""
    if not path.is_file():
        raise SystemExit(
            f"Organiser scoring module not found at {path}.\n"
            "Extract sdoc-hackathon-docker.zip into local-data/ first."
        )
    spec = importlib.util.spec_from_file_location("organiser_scoring", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SystemExit(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(result: dict[str, Any]) -> str:
    stage1 = result["stage1"]
    stage3 = result["stage3"]
    reliability = result["reliability"]
    end_to_end = result["end_to_end"]

    lines = [
        f"final score            {result['final_score']:.3f}",
        "",
        f"  classification       macro-F1 {stage1['macro_f1']:.3f} "
        f"(accuracy {stage1['accuracy']:.3f})",
        f"  defect detection     F1 {stage3['defect_f1']:.3f} "
        f"(precision {stage3['defect_precision']:.2f}, recall {stage3['defect_recall']:.2f})",
        f"  field-level          F1 {stage3['field_f1']:.3f} "
        f"(exact set {stage3['exact_match_rate']:.2f})",
        f"  end-to-end           {end_to_end['success']}/{end_to_end['total']} "
        f"({end_to_end['rate']:.3f})",
        "",
        f"  escalation           precision {reliability['escalation_precision']:.2f}, "
        f"recall {reliability['escalation_recall']:.2f}",
    ]
    for reason, counts in sorted(reliability["per_reason"].items()):
        lines.append(f"    {reason:<20} {counts['caught']}/{counts['total']}")

    misrouted = {
        actual: {pred: n for pred, n in predictions.items() if pred != actual}
        for actual, predictions in stage1["confusion"].items()
    }
    misrouted = {actual: wrong for actual, wrong in misrouted.items() if wrong}
    if misrouted:
        lines += ["", "  misclassified:"]
        lines += [f"    {actual} -> {wrong}" for actual, wrong in sorted(misrouted.items())]
    return "\n".join(lines)


def score_file(
    submission_path: Path,
    ground_truth_path: Path = GROUND_TRUTH,
    scoring_path: Path = SCORING_MODULE,
) -> str:
    """Score a submission file and return a printable report."""
    if not ground_truth_path.is_file():
        raise SystemExit(
            f"Ground truth not found at {ground_truth_path}.\n"
            "Extract sdoc-hackathon-docker.zip into local-data/ first."
        )
    scoring = _load_scoring(scoring_path)
    truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    submission = json.loads(submission_path.read_text(encoding="utf-8"))

    missing = set(truth) - set(submission)
    if missing:
        print(
            f"warning: {len(missing)} email ids are absent and will score as GENERAL/OK",
            file=sys.stderr,
        )

    return _report(scoring.score_all(truth, submission))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path, help="submission JSON to score")
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH)
    parser.add_argument("--scoring", type=Path, default=SCORING_MODULE)
    args = parser.parse_args(argv)

    print(score_file(args.submission, args.ground_truth, args.scoring))
    return 0


if __name__ == "__main__":
    sys.exit(main())
