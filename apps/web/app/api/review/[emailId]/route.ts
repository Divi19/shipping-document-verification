import { NextRequest, NextResponse } from "next/server";

import { forward } from "@/lib/relay";

type Context = { params: Promise<{ emailId: string }> };

export async function GET(
  _request: NextRequest,
  { params }: Context,
): Promise<NextResponse> {
  const { emailId } = await params;
  return forward(`/review-queue/${encodeURIComponent(emailId)}`);
}

/** Record a reviewer's decision; FastAPI validates it and returns the package. */
export async function POST(
  request: NextRequest,
  { params }: Context,
): Promise<NextResponse> {
  const { emailId } = await params;
  return forward(`/review-queue/${encodeURIComponent(emailId)}/decision`, {
    body: await request.text(),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}
