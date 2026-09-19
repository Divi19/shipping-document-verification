const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function isApiHealthy(): Promise<boolean> {
  try {
    const response = await fetch(new URL("/health", apiBaseUrl), {
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}
