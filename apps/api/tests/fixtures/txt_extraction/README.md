# Synthetic TXT extraction corpus

This directory defines the committed benchmark for the deterministic TXT extractor.
The documents are synthetic and do not copy participant records or organizer-only labels.

`manifest.json` records the raw candidates that extraction should produce. It deliberately
does not contain normalized values: extraction must preserve source text, while Box 7 owns
normalization.

The cases cover:

- canonical SI labels;
- common BL label variants;
- multiline party blocks, including an `On behalf of` qualifier;
- contradictory values that must remain as separate candidates; and
- blank or placeholder values that must remain missing rather than being invented.

Ticket 4 should use this corpus as its first executable acceptance set.
