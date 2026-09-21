import { NextRequest, NextResponse } from "next/server";

import { apiBaseUrl } from "@/lib/api";
import { apiUnavailable } from "@/lib/relay";

type Context = { params: Promise<{ emailId: string; filename: string }> };

const passedHeaders = ["content-type", "content-disposition"];

/** Stream an original attachment so the reviewer can read the source document. */
export async function GET(
  _request: NextRequest,
  { params }: Context,
): Promise<NextResponse> {
  const { emailId, filename } = await params;
  const target = new URL(
    `/review-queue/${encodeURIComponent(emailId)}/attachments/${encodeURIComponent(filename)}`,
    apiBaseUrl,
  );
  try {
    const response = await fetch(target, { cache: "no-store" });
    const headers = new Headers();
    for (const name of passedHeaders) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(response.body, {
      headers,
      status: response.status,
    });
  } catch {
    return apiUnavailable();
  }
}
