import type { HealthResponse } from "@sdoc/contracts";

export const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function getApiHealth(): Promise<HealthResponse | null> {
  try {
    const response = await fetch(new URL("/health", apiBaseUrl), {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as HealthResponse;
  } catch {
    return null;
  }
}
