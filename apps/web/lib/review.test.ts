import { describe, expect, it } from "vitest";

import {
  buildDecision,
  comparisonRows,
  comparisonStatus,
  decisionBlocker,
  errorMessage,
} from "./review";

describe("buildDecision", () => {
  it("sends only filled-in corrections, trimmed and in field order", () => {
    const decision = buildDecision(" Ops reviewer ", "corrected", "  ", {
      "gross_weight_kg:bl": " 131,322 KG ",
      "shipper:si": "",
      "consignee:si": "EAST BRIGHT FZ-LLC",
    });

    expect(decision).toEqual({
      action: "corrected",
      corrections: [
        { field: "consignee", side: "si", value: "EAST BRIGHT FZ-LLC" },
        { field: "gross_weight_kg", side: "bl", value: "131,322 KG" },
      ],
      note: null,
      reviewer: "Ops reviewer",
    });
  });

  it("drops corrections for any other action", () => {
    const decision = buildDecision("Ops", "unable_to_verify", "No reply.", {
      "gross_weight_kg:bl": "131,322 KG",
    });

    expect(decision.corrections).toEqual([]);
    expect(decision.note).toBe("No reply.");
  });
});

describe("decisionBlocker", () => {
  it("names what is missing before a decision can be sent", () => {
    expect(decisionBlocker(buildDecision("", "confirmed", "", {}))).toMatch(
      /your name/,
    );
    expect(
      decisionBlocker(buildDecision("Ops", "information_requested", " ", {})),
    ).toMatch(/note/);
    expect(decisionBlocker(buildDecision("Ops", "corrected", "", {}))).toMatch(
      /corrected value/,
    );
    expect(
      decisionBlocker(buildDecision("Ops", "confirmed", "", {})),
    ).toBeNull();
  });
});

describe("comparisonRows", () => {
  it("returns all seven fields even when nothing was compared", () => {
    const rows = comparisonRows([]);

    expect(rows).toHaveLength(7);
    expect(rows.every((row) => row.comparison === null)).toBe(true);
    expect(comparisonStatus(null)).toBe("not compared");
  });
});

describe("errorMessage", () => {
  it("reads both plain and validation-list FastAPI errors", () => {
    expect(errorMessage({ detail: "already resolved" }, 409)).toBe(
      "already resolved",
    );
    expect(
      errorMessage(
        { detail: [{ msg: "String should have at least 1 character" }] },
        422,
      ),
    ).toBe("String should have at least 1 character");
    expect(errorMessage(null, 503)).toBe("Request failed with status 503");
  });
});
