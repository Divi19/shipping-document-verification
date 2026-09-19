import { describe, expectTypeOf, it } from "vitest";

import type { HealthResponse } from "./index";

describe("HealthResponse", () => {
  it("matches the generated FastAPI health contract", () => {
    expectTypeOf<HealthResponse>().toEqualTypeOf<{
      service: "shipping-document-verification-api";
      status: "ok";
    }>();
  });
});
