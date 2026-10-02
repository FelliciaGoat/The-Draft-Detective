/**
 * Server-side proxy for the demo buttons.
 *
 * The backend protects simulation with the X-API-Key header. That key must never reach the
 * browser, so the browser calls THIS route and the route adds the key (from the server-only
 * DEVICE_API_KEY environment variable in .env.local).
 *
 * POST { roomId, speed, mode: "room" }      plays the demo story in one room.
 * POST { roomId, speed, mode: "building" }  also creates a small demo building (if missing) and
 *                                           plays a different scenario in every other room, so the
 *                                           building view shows occupied, vacant, uncertain and
 *                                           leak-candidate rooms side by side. All readings are
 *                                           labelled simulated.
 */

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const DURATION = 1800; // simulated seconds (the 30-minute story)
const INTERVAL = 10; // simulated seconds between readings

/** The demo building: two floors, one scenario per room. Room A-101 is the backend's seeded room. */
const DEMO_BUILDING = [
  { name: "Room A-101", floor: 1, zone: "North Wing", scenario: "demo_story" },
  { name: "Room A-102", floor: 1, zone: "North Wing", scenario: "occupied_room" },
  { name: "Room A-103", floor: 1, zone: "North Wing", scenario: "empty_room_hvac_on" },
  { name: "Room A-104", floor: 1, zone: "North Wing", scenario: "noisy_acoustic" },
  { name: "Room B-201", floor: 2, zone: "South Wing", scenario: "thermal_anomaly" },
  { name: "Room B-202", floor: 2, zone: "South Wing", scenario: "occupied_normal_thermal" },
  { name: "Room B-203", floor: 2, zone: "South Wing", scenario: "empty_room" },
  { name: "Room B-204", floor: 2, zone: "South Wing", scenario: "occupied_room" },
] as const;

interface BackendRoom {
  id: number;
  name: string;
}

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

function backendUnreachable(error: unknown): NextResponse {
  const reason = error instanceof Error ? error.message : "unknown error";
  return NextResponse.json(
    { detail: `Cannot reach the backend at ${BACKEND}. Is uvicorn running? (${reason})` },
    { status: 502 },
  );
}

class BackendError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Backend returned ${status}`);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BACKEND}${path}`, { cache: "no-store", ...init });
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) throw new BackendError(response.status, body?.detail ?? `Backend returned ${response.status}`);
  return body as T;
}

function startRun(key: string, roomId: number, scenario: string, speed: number) {
  return call<Record<string, unknown> & { run_id: string }>("/api/v1/simulation/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": key },
    body: JSON.stringify({ room_id: roomId, scenario, duration: DURATION, interval: INTERVAL, realtime: true, speed }),
  });
}

/** Create the demo rooms that do not exist yet. Returns every room and the names created. */
async function ensureDemoBuilding(): Promise<{ rooms: BackendRoom[]; created: string[] }> {
  const rooms = await call<BackendRoom[]>("/api/v1/rooms?limit=500");
  const have = new Set(rooms.map((r) => r.name));
  const created: string[] = [];
  for (const spec of DEMO_BUILDING) {
    if (have.has(spec.name)) continue;
    const room = await call<BackendRoom>("/api/v1/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: spec.name,
        building: "Main Building",
        floor: spec.floor,
        zone: spec.zone,
        climate_zone: "Composite",
        hvac_power_kw: 1.5,
      }),
    });
    rooms.push(room);
    created.push(room.name);
  }
  return { rooms, created };
}

/** Start a realtime demo. Body: { roomId: number, speed?: number, mode?: "room" | "building" } */
export async function POST(request: Request) {
  const auth = keyOrError();
  if ("error" in auth) return auth.error;

  const input = (await request.json().catch(() => ({}))) as { roomId?: number; speed?: number; mode?: string };
  const roomId = Number(input.roomId);
  const speed = Math.min(120, Math.max(1, Number(input.speed ?? 30)));
  const mode = input.mode === "building" ? "building" : "room";
  if (!Number.isInteger(roomId) || roomId < 1) {
    return NextResponse.json({ detail: "roomId must be a positive integer." }, { status: 422 });
  }

  try {
    let created: string[] = [];
    const others: { room_id: number; room_name: string; scenario: string; run_id: string }[] = [];

    if (mode === "building") {
      const building = await ensureDemoBuilding();
      created = building.created;
      const byName = new Map(building.rooms.map((r) => [r.name, r]));
      // The story plays in the selected room; every other demo room gets its own scenario.
      for (const spec of DEMO_BUILDING) {
        const room = byName.get(spec.name);
        if (!room || room.id === roomId) continue;
        const scenario = spec.scenario === "demo_story" ? "occupied_room" : spec.scenario;
        const run = await startRun(auth.key, room.id, scenario, speed);
        others.push({ room_id: room.id, room_name: room.name, scenario, run_id: run.run_id });
      }
    }

    const story = await startRun(auth.key, roomId, "demo_story", speed);
    return NextResponse.json({ story, others, created_rooms: created }, { status: 202 });
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ detail: error.detail }, { status: error.status });
    }
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

/** Stop one or more runs. Query: ?run=<id>&run=<id>… */
export async function DELETE(request: Request) {
  const auth = keyOrError();
  if ("error" in auth) return auth.error;
  const runs = new URL(request.url).searchParams.getAll("run").filter(Boolean);
  if (runs.length === 0) return NextResponse.json({ detail: "run is required." }, { status: 422 });
  try {
    const results = await Promise.all(
      runs.map((run) =>
        fetch(`${BACKEND}/api/v1/simulation/runs/${encodeURIComponent(run)}/stop`, {
          method: "POST",
          headers: { "X-API-Key": auth.key },
          cache: "no-store",
        }).then((r) => r.status),
      ),
    );
    return NextResponse.json({ stopped: runs.length, statuses: results });
  } catch (error) {
    return backendUnreachable(error);
  }
}
