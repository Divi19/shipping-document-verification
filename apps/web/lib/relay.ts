import { NextResponse } from "next/server";

import { apiBaseUrl } from "@/lib/api";

export function apiUnavailable(): NextResponse {
  return NextResponse.json(
    { detail: "FastAPI is unavailable. Start it with pnpm dev:api." },
    { status: 503 },
  );
}

/** Forward a request to FastAPI and pass its JSON response through unchanged. */
export async function forward(
  path: string,
  init: RequestInit = {},
): Promise<NextResponse> {
  try {
    const response = await fetch(new URL(path, apiBaseUrl), {
      cache: "no-store",
      ...init,
    });
    return new NextResponse(await response.text(), {
      headers: {
        "content-type":
          response.headers.get("content-type") ?? "application/json",
      },
      status: response.status,
    });
  } catch {
    return apiUnavailable();
  }
}
