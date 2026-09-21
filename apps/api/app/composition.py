"""Assemble the pipeline, with AI attached when it is configured.

Kept apart from both packages so ``app.pipeline`` never imports ``app.ai``:
the pipeline runs identically without a model, and the model is added here.

With ``GEMINI_API_KEY`` set the model is consulted in exactly two places:

* classification, only for an email no rule matched;
* extraction, only for a field no label matched - and only when it can quote
  evidence from the document that verifies.

Without a key both fall back to the deterministic path, so the system still
runs, and still escalates the cases it cannot decide.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.agents.email_classifier import EmailClassifier
from app.config import data_dir
from app.pipeline import Pipeline

if TYPE_CHECKING:
    from app.ai.client import LlmClient

logger = logging.getLogger(__name__)


def build_pipeline(dataset_root: Path | None = None, *, use_ai: bool = True) -> Pipeline:
    """Build the pipeline, attaching the model when one is configured."""
    root = dataset_root or data_dir()
    client: LlmClient | None = None

    if use_ai:
        from app.ai import build_client

        client = build_client()

    if client is None:
        return Pipeline(dataset_root=root)

    from app.ai import LlmCategoryOracle, LlmFieldResolver

    logger.info("AI enabled via %s", client.name)
    return Pipeline(
        dataset_root=root,
        classifier=EmailClassifier(oracle=LlmCategoryOracle(client)),
        field_resolver=LlmFieldResolver(client),
    )
