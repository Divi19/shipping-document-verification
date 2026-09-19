import { isApiHealthy } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const apiHealthy = await isApiHealthy();

  return (
    <main>
      <h1>Shipping Document Verification</h1>
      <p>Frontend is running.</p>
      <p>FastAPI health: {apiHealthy ? "connected" : "unavailable"}</p>
    </main>
  );
}
