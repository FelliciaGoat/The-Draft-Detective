/**
 * Server-side proxy for the "Run demo" button.
 *
 * The backend protects simulation with the X-API-Key header. That key must never reach the
 * browser, so the browser calls THIS route and the route adds the key (from the server-only
 * DEVICE_API_KEY environment variable in .env.local).
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

function keyOrError(): { key: string } | { error: NextResponse } {
  const key = process.env.DEVICE_API_KEY;
  if (!key) {
    return {
      error: NextResponse.json(
        { detail: "DEVICE_API_KEY is missing. Add it to .env.local (same value as the backend's .env) and restart npm run dev." },
        { status: 503 },
      ),
    };
  }
  return { key };
}

async function relay(response: Response): Promise<NextResponse> {
  const body = await response.json().catch(() => ({ detail: `Backend returned ${response.status}` }));
  return NextResponse.json(body, { status: response.status });
}

async function backendUnreachable(error: unknown): Promise<NextResponse> {
  const reason = error instanceof Error ? error.message : "unknown error";
  return NextResponse.json(
    { detail: `Cannot reach the backend at ${BACKEND}. Is uvicorn running? (${reason})` },
    { status: 502 },
  );
}

/** Start a realtime demo run. Body: { roomId: number, speed?: number } */
export async function POST(request: Request) {
  const auth = keyOrError();
  if ("error" in auth) return auth.error;

  const input = (await request.json().catch(() => ({}))) as { roomId?: number; speed?: number };
  const roomId = Number(input.roomId);
  const speed = Math.min(120, Math.max(1, Number(input.speed ?? 30)));
  if (!Number.isInteger(roomId) || roomId < 1) {
    return NextResponse.json({ detail: "roomId must be a positive integer." }, { status: 422 });
  }

  try {
    const response = await fetch(`${BACKEND}/api/v1/simulation/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": auth.key },
      body: JSON.stringify({
        room_id: roomId,
        scenario: "demo_story",
        duration: 1800,
        interval: 10,
        realtime: true,
        speed,
      }),
      cache: "no-store",
    });
    return await relay(response);
  } catch (error) {
    return backendUnreachable(error);
  }
}

/** Progress of a run. Query: ?run=<run_id> */
export async function GET(request: Request) {
  const run = new URL(request.url).searchParams.get("run");
  if (!run) return NextResponse.json({ detail: "run is required." }, { status: 422 });
  try {
    const response = await fetch(`${BACKEND}/api/v1/simulation/runs/${encodeURIComponent(run)}`, { cache: "no-store" });
    return await relay(response);
  } catch (error) {
    return backendUnreachable(error);
  }
}

/** Stop a run. Query: ?run=<run_id> */
export async function DELETE(request: Request) {
  const auth = keyOrError();
  if ("error" in auth) return auth.error;
  const run = new URL(request.url).searchParams.get("run");
  if (!run) return NextResponse.json({ detail: "run is required." }, { status: 422 });
  try {
    const response = await fetch(`${BACKEND}/api/v1/simulation/runs/${encodeURIComponent(run)}/stop`, {
      method: "POST",
      headers: { "X-API-Key": auth.key },
      cache: "no-store",
    });
    return await relay(response);
  } catch (error) {
    return backendUnreachable(error);
  }
}
