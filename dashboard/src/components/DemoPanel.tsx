"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SimulationRun } from "@/lib/api";
import Icon from "./Icons";

interface Props {
  roomId: number | null;
  /** Called shortly after a run starts so the page can reload its history. */
  onStarted: () => void;
}

const SPEEDS = [
  { value: 60, label: "60× (about 30 seconds)" },
  { value: 30, label: "30× (about 1 minute)" },
  { value: 10, label: "10× (about 3 minutes)" },
  { value: 1, label: "Real time (30 minutes)" },
];

async function readError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : `The demo could not start (HTTP ${response.status}).`;
}

export default function DemoPanel({ roomId, onStarted }: Props) {
  const [speed, setSpeed] = useState(30);
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const running = run?.status === "running";

  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const response = await fetch(`/api/demo?run=${encodeURIComponent(runId)}`, { cache: "no-store" });
        if (!response.ok) return;
        const body = (await response.json()) as SimulationRun;
        setRun(body);
        if (body.status !== "running") window.clearInterval(timer.current);
      } catch {
        /* keep polling */
      }
    };
    timer.current = window.setInterval(poll, 1000);
    return () => window.clearInterval(timer.current);
  }, [runId]);

  const start = useCallback(async () => {
    if (roomId === null) return;
    setStarting(true);
    setError(null);
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roomId, speed }),
      });
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const body = (await response.json()) as SimulationRun;
      setRun(body);
      setRunId(body.run_id);
      window.setTimeout(onStarted, 700);
    } catch {
      setError("The dashboard server could not be reached. Is npm run dev still running?");
    } finally {
      setStarting(false);
    }
  }, [roomId, speed, onStarted]);

  const stop = useCallback(async () => {
    if (!runId) return;
    await fetch(`/api/demo?run=${encodeURIComponent(runId)}`, { method: "DELETE" }).catch(() => undefined);
  }, [runId]);

  const progress = run && run.readings_planned > 0 ? Math.round((run.readings_generated / run.readings_planned) * 100) : 0;

  return (
    <section className="demo" aria-labelledby="demo-title">
      <h2 id="demo-title">
        <Icon name="play" size={14} />
        Demo without hardware
      </h2>
      <p>
        Plays a 30-minute story in this room: people talking, everyone leaves, then the window wall drifts away from room temperature. Every reading is labelled simulated.
      </p>
      <div className="demo-controls">
        <label className="sr-only" htmlFor="demo-speed">
          Playback speed
        </label>
        <select id="demo-speed" className="select" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} disabled={running}>
          {SPEEDS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {running ? (
          <button type="button" className="button quiet" onClick={stop}>
            <Icon name="stop" size={13} />
            Stop demo
          </button>
        ) : (
          <button type="button" className="button" onClick={start} disabled={roomId === null || starting}>
            <Icon name="play" size={13} />
            {starting ? "Starting…" : "Run demo story"}
          </button>
        )}
      </div>
      {running && (
        <div className="progress" role="progressbar" aria-label="Demo progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: `${progress}%` }} />
        </div>
      )}
      {run && !running && run.status !== "completed" && !error && (
        <p>{run.status === "stopped" ? "Demo stopped." : run.error ? `Demo failed: ${run.error}` : ""}</p>
      )}
      {run?.status === "completed" && <p>Demo finished. The readings stay on screen until you run it again.</p>}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}
