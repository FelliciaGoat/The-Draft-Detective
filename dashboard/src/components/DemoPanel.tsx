"use client";

import { useState } from "react";
import type { Demo } from "@/lib/demo";
import Icon from "./Icons";

const SPEEDS = [
  { value: 60, label: "60× (about 30 seconds)" },
  { value: 30, label: "30× (about 1 minute)" },
  { value: 10, label: "10× (about 3 minutes)" },
  { value: 1, label: "Real time (30 minutes)" },
];

/** Sidebar controls for the simulated demos. The story itself is shown in the main column. */
export default function DemoPanel({ roomId, demo }: { roomId: number | null; demo: Demo }) {
  const [speed, setSpeed] = useState(30);
  const running = demo.running;
  const busy = demo.starting || roomId === null;

  return (
    <section className="demo" aria-labelledby="demo-title">
      <h2 id="demo-title">
        <Icon name="play" size={14} />
        Demo without hardware
      </h2>
      <p>
        Plays a 30-minute story in the selected room. The building demo also fills seven more rooms with their own
        scenarios. Every reading is labelled simulated.
      </p>
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
        <button type="button" className="button quiet" onClick={() => void demo.stop()}>
          <Icon name="stop" size={13} />
          Stop demo
        </button>
      ) : (
        <div className="demo-buttons">
          <button type="button" className="button" onClick={() => roomId !== null && void demo.start("building", roomId, speed)} disabled={busy}>
            <Icon name="overview" size={13} />
            {demo.starting ? "Starting…" : "Run building demo"}
          </button>
          <button type="button" className="button quiet" onClick={() => roomId !== null && void demo.start("room", roomId, speed)} disabled={busy}>
            <Icon name="play" size={13} />
            This room only
          </button>
        </div>
      )}
      {demo.createdRooms.length > 0 && <p className="ok-text">Added {demo.createdRooms.length} demo rooms to the building.</p>}
      {demo.error && <p className="error-text">{demo.error}</p>}
    </section>
  );
}
