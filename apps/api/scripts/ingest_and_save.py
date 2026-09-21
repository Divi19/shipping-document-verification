#!/usr/bin/env python3
"""Ingest all attachments from the sample data folder and save markdown.

Run from the repository root:

    python apps/api/scripts/ingest_and_save.py [output_dir]

If ``output_dir`` is omitted the script creates ``markdown-output`` in the
project root. The input directory follows ``SDOC_DATA_DIR`` and the script
disables Gemini Vision because it requires a cloud API key.
"""

import sys
from pathlib import Path

# Add the API directory to ``sys.path`` so ``import app`` works.
# ``ingest_and_save.py`` lives in ``apps/api/scripts`` → repo root is three levels up.
api_root = Path(__file__).resolve().parents[1]
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(api_root))

from app.config import resolve_data_dir  # noqa: E402
from app.ingestion.service import (  # noqa: E402
    DocumentIngestionConfig,
    DocumentIngestionService,
)


def main() -> None:
    data_dir = resolve_data_dir()
    attachments_dir = data_dir / "attachments"
    if not attachments_dir.is_dir():
        print(f"[!] Attachments directory not found: {attachments_dir}")
        print(f"    Set SDOC_DATA_DIR or place the participant bundle at: {data_dir}")
        sys.exit(1)

    # Destination for markdown files.
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else repo_root / "markdown-output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build a service instance – no Gemini Vision fallback (no API key needed).
    cfg = DocumentIngestionConfig(enable_vision_fallback=False)
    service = DocumentIngestionService(cfg)

    for src_path in sorted(attachments_dir.iterdir()):
        if not src_path.is_file():
            continue
        try:
            result = service.ingest_file(src_path)
            # Write a .md file using the same stem as the source.
            dst_path = out_dir / f"{src_path.stem}.md"
            dst_path.write_text(result.content, encoding="utf-8")
            print(f"✔ {src_path.name} → {dst_path.name}")
        except Exception as exc:
            print(f"[ERROR] {src_path.name}: {exc}")

    # Clean up thread‑pool and cache connections.
    service.shutdown()
    print(f"\nAll markdown files written to: {out_dir}")


if __name__ == "__main__":
    main()
