import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiHealth } from "./api";

const healthResponse = {
  service: "shipping-document-verification-api" as const,
  status: "ok" as const,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getApiHealth", () => {
  it("returns the typed health response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(healthResponse), {
        headers: { "content-type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getApiHealth()).resolves.toEqual(healthResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://localhost:8000/health"),
      {
        cache: "no-store",
      },
    );
  });

  it("returns null when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("unavailable")));

    await expect(getApiHealth()).resolves.toBeNull();
  });
});
