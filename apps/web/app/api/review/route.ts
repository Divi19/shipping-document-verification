import { NextResponse } from "next/server";

import { forward } from "@/lib/relay";

export async function GET(): Promise<NextResponse> {
  return forward("/review-queue");
}

/** Process every inbox email not processed yet, which fills the queue. */
export async function POST(): Promise<NextResponse> {
  return forward("/cases/run-inbox", { method: "POST" });
}
