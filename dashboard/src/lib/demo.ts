"use client";

/** Demo controller: starts a room or building demo through /api/demo and follows the story run. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { DemoStart, SimulationRun } from "./api";

export type DemoMode = "room" | "building";

export interface Demo {
  mode: DemoMode | null;
  story: SimulationRun | null;
  storyRoomId: number | null;
  otherRuns: DemoStart["others"];
  createdRooms: string[];
  running: boolean;
  starting: boolean;
  error: string | null;
  start: (mode: DemoMode, roomId: number, speed: number) => Promise<boolean>;
  stop: () => Promise<void>;
}

async function readError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (typeof body?.detail === "string") return body.detail;
  return `The demo could not start (HTTP ${response.status}).`;
}

export function useDemo(): Demo {
  const [mode, setMode] = useState<DemoMode | null>(null);
  const [story, setStory] = useState<SimulationRun | null>(null);
  const [storyRoomId, setStoryRoomId] = useState<number | null>(null);
  const [otherRuns, setOtherRuns] = useState<DemoStart["others"]>([]);
  const [createdRooms, setCreatedRooms] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const runId = story?.run_id ?? null;
  const running = story?.status === "running";

  // Follow the story run once a second while it is running.
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/demo?run=${encodeURIComponent(runId)}`, { cache: "no-store" });
        if (!response.ok || cancelled) return;
        const body = (await response.json()) as SimulationRun;
        setStory(body);
        if (body.status !== "running") window.clearInterval(timer.current);
      } catch {
        /* keep polling */
      }
    };
    timer.current = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer.current);
    };
  }, [runId]);

  const start = useCallback(async (nextMode: DemoMode, roomId: number, speed: number) => {
    setStarting(true);
    setError(null);
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roomId, speed, mode: nextMode }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return false;
      }
      const body = (await response.json()) as DemoStart;
      setMode(nextMode);
      setStory(body.story);
      setStoryRoomId(roomId);
      setOtherRuns(body.others);
      setCreatedRooms(body.created_rooms);
      return true;
    } catch {
      setError("The dashboard server could not be reached. Is npm run dev still running?");
      return false;
    } finally {
      setStarting(false);
    }
  }, []);

  const stop = useCallback(async () => {
    const ids = [story?.run_id, ...otherRuns.map((r) => r.run_id)].filter(Boolean) as string[];
    if (ids.length === 0) return;
    const query = ids.map((id) => `run=${encodeURIComponent(id)}`).join("&");
    await fetch(`/api/demo?${query}`, { method: "DELETE" }).catch(() => undefined);
    setStory((s) => (s ? { ...s, status: "stopped" } : s));
  }, [story?.run_id, otherRuns]);

  return { mode, story, storyRoomId, otherRuns, createdRooms, running, starting, error, start, stop };
}

/** Simulated seconds covered so far by a run. */
export function storyElapsed(run: SimulationRun | null, interval = 10): number {
  if (!run) return 0;
  return Math.max(0, (run.readings_generated - 1) * interval);
}

export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
