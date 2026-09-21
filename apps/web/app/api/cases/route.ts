import { NextRequest, NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

async function relay(response: Response): Promise<NextResponse> {
  const payload = await response.text();
  return new NextResponse(payload, {
    headers: {
      "content-type":
        response.headers.get("content-type") ?? "application/json",
    },
    status: response.status,
  });
}

export async function GET(): Promise<NextResponse> {
  try {
    return relay(
      await fetch(new URL("/cases/available", apiBaseUrl), {
        cache: "no-store",
      }),
    );
  } catch {
    return NextResponse.json(
      { detail: "FastAPI is unavailable. Start it with pnpm dev:api." },
      { status: 503 },
    );
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = (await request.json()) as { email_id?: string };
    if (!body.email_id) {
      return NextResponse.json(
        { detail: "Choose an email case first." },
        { status: 400 },
      );
    }
    const target = new URL(
      `/cases/${encodeURIComponent(body.email_id)}/run-report`,
      apiBaseUrl,
    );
    return relay(await fetch(target, { method: "POST" }));
  } catch {
    return NextResponse.json(
      { detail: "FastAPI is unavailable. Start it with pnpm dev:api." },
      { status: 503 },
    );
  }
}
