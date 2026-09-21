import { PipelineWorkbench } from "@/app/pipeline-workbench";
import { getApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const apiHealth = await getApiHealth();

  return <PipelineWorkbench apiConnected={apiHealth?.status === "ok"} />;
}
