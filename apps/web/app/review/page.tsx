import type { Metadata } from "next";

import { ReviewWorkbench } from "@/app/review/review-workbench";
import { getApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Review queue · Shipping Document Verification",
  description: "Human review of shipping cases the pipeline could not decide",
};

type ReviewPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function ReviewPage({ searchParams }: ReviewPageProps) {
  const [apiHealth, params] = await Promise.all([getApiHealth(), searchParams]);
  const initialCase = typeof params.case === "string" ? params.case : null;

  return (
    <ReviewWorkbench
      apiConnected={apiHealth?.status === "ok"}
      initialCase={initialCase}
    />
  );
}
