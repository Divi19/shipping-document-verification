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
      await fetch(new URL("/pipeline/samples", apiBaseUrl), {
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
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const role = String(
        formData.get("document_role") ?? "shipping_instruction",
      );
      formData.delete("document_role");
      const target = new URL("/pipeline/document", apiBaseUrl);
      target.searchParams.set("document_role", role);
      return relay(await fetch(target, { body: formData, method: "POST" }));
    }

    const body = (await request.json()) as {
      document_role?: string;
      filename?: string;
    };
    if (!body.filename) {
      return NextResponse.json(
        { detail: "Choose a sample document." },
        { status: 400 },
      );
    }
    const target = new URL(
      `/pipeline/sample/${encodeURIComponent(body.filename)}`,
      apiBaseUrl,
    );
    target.searchParams.set(
      "document_role",
      body.document_role ?? "shipping_instruction",
    );
    return relay(await fetch(target, { method: "POST" }));
  } catch {
    return NextResponse.json(
      { detail: "FastAPI is unavailable. Start it with pnpm dev:api." },
      { status: 503 },
    );
  }
}
