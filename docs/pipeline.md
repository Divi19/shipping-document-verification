# Verification pipeline

How a case flows, and the contracts the other workstreams plug into.

## Flow

```text
email record
  -> classify            five categories; rules first, LLM for the remainder
  -> read documents      reader chosen by file type, bounded retries
  -> identify roles      SI / BL / other, decided from the content
  -> extract fields      seven fields, each with evidence
  -> normalise           labels, names, ports, numbers, units
  -> compare             deterministic, SI is the reference
  -> decide              one documented rule order
  -> persist + escalate  NEEDS_REVIEW is recorded immediately, not held back
```

Everything lands on one `CaseRecord` (`app/pipeline/models.py`): the category,
the documents read, the seven `FieldComparison`s with both values and their
evidence, the outcome, and every stage attempt including the failed ones.

## Outcomes

| Outcome | Meaning | Submitted as |
|---|---|---|
| `VERIFIED` | all seven compared, all agree | `OK` |
| `MISMATCH` | compared cleanly, at least one differs | `MISMATCH` + `defect_fields` |
| `NEEDS_REVIEW` | could not decide; carries a reason | `NEEDS_REVIEW` |
| `AWAITING_DOCUMENTS` | comparison requested, documents not sent yet | `OK` |
| `NOT_APPLICABLE` | not a comparison request | `OK` |

`AWAITING_DOCUMENTS` exists because the dataset scores those emails as `OK`
while nothing was actually compared. The distinction is kept internally and
flattened only in `app/pipeline/submission.py`. **The interface must never show
"all seven fields verified" for one of these cases.**

Escalation reasons are `wrong_doc_type`, `missing_attachment`, `unreadable` and
`missing_value`, matching the evaluation schema.

## Rules worth knowing before changing anything

- **A filename proves nothing.** `email_501_BL.txt` contains a Commercial
  Invoice; the PDF and Excel SIs are titled `BILL OF LADING INSTRUCTION` and
  `BL INSTRUCTION`. Roles are decided from the document header, and
  "instruction" wins over "bill of lading".
- **Blank is not different.** `N/A`, `TBA`, `???` and `_______` make a field
  undecidable, which escalates. Reporting them as a discrepancy is a false
  alarm, and false alarms are what the accuracy target is about.
- **One document, one reading.** Two different values for the same field inside
  one document is a contradiction, not a choice to make silently.
- **Weights come from the total.** A container table lists a weight per
  container; the shipment's gross weight is the `TOTAL` line. Injected defects
  are +/-500-2000 kg, so picking a row produces a plausible false mismatch.
- **Retries must be able to help.** Another reader for a file that failed to
  parse, yes. A missing attachment, never.

## Adding a document reader

Implement `app/pipeline/readers.py::DocumentReader` and pass it to the
`Pipeline`; nothing else changes.

```python
class MyPdfReader:
    name = "pdf-layout"

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def read(self, path: Path) -> str:
        ...  # raise ReaderError when the document cannot be read
```

Contract:

- return text, or markdown with `| label | value |` rows for tabular layouts -
  the extractor reads both, plus a bare label line followed by its value
- **raise `ReaderError`**; never return empty text for a failure, or an
  unreadable scan becomes an empty comparison instead of an escalation
- the PDF SI/BL pair is a two-column form whose text order does not match the
  visual layout, so use word coordinates (or vision) rather than line order,
  otherwise the consignee reads as part of the shipper's address

## Adding label synonyms

`app/pipeline/fields.py::LABEL_SYNONYMS`, keyed by the output of
`normalize_label()` (lowercased, CJK dropped, parentheticals removed). Add a
test alongside: label handling is where formatting differences turn into false
discrepancies.

## Running it

```bash
pnpm pipeline:run -- --text-only          # quick pass, no extraction extras
pnpm pipeline:run                          # all readers
pnpm pipeline:score local-data/submission.json
```

Scoring uses the organisers' own `scoring.py` and `ground_truth.json` from
`local-data/`, which the organisers confirmed on 19 September 2026 is intended
for teams to evaluate their own work. It is a development tool only: nothing in
`app/` reads it.

## Where the score comes from

`final = 0.30 x classification macro-F1 + 0.20 x defect F1 + 0.50 x end-to-end`,
where end-to-end only counts an email if it is routed to `BL_COMPARISON`, marked
as a defect, **and** the defect field set matches exactly. Escalation quality is
reported separately and is not part of the final score - it is a differentiator
for judges, not a scoreboard lever.

Current measured state, with plain text, Excel and Word readable:

| Axis | Value |
|---|---|
| final score | 0.934 |
| classification macro-F1 | 1.000 |
| defect precision / recall | 1.00 / 0.89 |
| end-to-end | 41/46 |
| exact defect-field set | 0.97 |
| escalation recall | 20/20, correct reason on all four types |

The remaining 5 end-to-end cases are the PDF pairs. They escalate as
`unreadable` because the PDF extractor currently produces no text without
Docling installed or a vision key configured - honest, and where the last of
the points are.

Re-measure after any change with:

```bash
pnpm pipeline:run && pnpm pipeline:score local-data/submission.json
```

Watch defect *precision* as much as the score: every false discrepancy is a
reviewer's wasted trip through two documents that actually agreed.
