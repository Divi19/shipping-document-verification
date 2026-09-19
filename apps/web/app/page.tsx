import { getApiHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const apiHealth = await getApiHealth();

  return (
    <main>
      <h1>Shipping Document Verification</h1>
      <p>Frontend is running.</p>
      <p>
        FastAPI health:{" "}
        {apiHealth?.status === "ok" ? "connected" : "unavailable"}
      </p>
    </main>
  );
}
