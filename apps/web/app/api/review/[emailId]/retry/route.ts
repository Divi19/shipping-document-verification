import { NextRequest, NextResponse } from "next/server";

import { forward } from "@/lib/relay";

type Context = { params: Promise<{ emailId: string }> };

/** Run the case through the pipeline again; human decisions are kept. */
export async function POST(
  _request: NextRequest,
  { params }: Context,
): Promise<NextResponse> {
  const { emailId } = await params;
  return forward(`/cases/${encodeURIComponent(emailId)}/run`, {
    method: "POST",
  });
}
