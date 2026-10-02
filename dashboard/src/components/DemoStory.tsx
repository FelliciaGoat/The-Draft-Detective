"use client";

/**
 * Guided demo: the 30-minute story as six steps on a timeline. A step is ticked from the run's
 * real transitions (what the engine actually decided), not from a script, so if the engine
 * behaves differently the timeline shows that too. Expected times are for default thresholds.
 */

import type { SimulationRun } from "@/lib/api";
import { mmss, storyElapsed } from "@/lib/demo";
import Icon from "./Icons";

const TOTAL = 1800;

interface Step {
  title: string;
  say: string;
  expect: number;
  /** Seconds into the story when it happened, or null if not yet. */
  reached: (run: SimulationRun, elapsed: number) => number | null;
}

function transitionAt(run: SimulationRun, test: (t: NonNullable<SimulationRun["transitions"]>[number]) => boolean): number | null {
  if (!run.start_time || !run.transitions) return null;
  const start = Date.parse(run.start_time);
  const hit = run.transitions.find(test);
  return hit ? Math.max(0, (Date.parse(hit.timestamp) - start) / 1000) : null;
}

const STEPS: Step[] = [
  {
    title: "Sensors start",
    say: "No history yet, so the room is uncertain and the system holds current settings.",
    expect: 0,
    reached: (run, elapsed) => (run.readings_generated > 0 ? Math.min(elapsed, 0) : null),
  },
  {
    title: "Meeting in progress",
    say: "Steady talking for long enough, so the room is called occupied. Comfort comes first.",
    expect: 30,
    reached: (run) => transitionAt(run, (t) => t.room_state === "occupied"),
  },
  {
    title: "Everyone leaves",
    say: "The sound stops at 5:00. The system waits before deciding, so a short silence never cuts the AC.",
    expect: 300,
    reached: (_run, elapsed) => (elapsed >= 300 ? 300 : null),
  },
  {
    title: "Vacant, save energy",
    say: "Quiet for long enough to be confident: suggest switching to energy-saving mode.",
    expect: 700,
    reached: (run) => transitionAt(run, (t) => t.recommended_action === "energy_saving_mode"),
  },
  {
    title: "Window wall drifts",
    say: "From 15:00 the window-side sensor moves away from room temperature while the room stays steady.",
    expect: 900,
    reached: (_run, elapsed) => (elapsed >= 900 ? 900 : null),
  },
  {
    title: "Leak candidate",
    say: "The gap has lasted several minutes: inspect the window and wall seals. A candidate, not a verdict.",
    expect: 1310,
    reached: (run) => transitionAt(run, (t) => t.leak_candidate || t.recommended_action === "inspect_envelope"),
  },
];

export default function DemoStory({ run, roomName, onStop }: { run: SimulationRun; roomName: string; onStop: () => void }) {
  const elapsed = Math.min(TOTAL, storyElapsed(run));
  const reached = STEPS.map((s) => s.reached(run, elapsed));
  const current = reached.findIndex((r) => r === null);
  const running = run.status === "running";
  const finished = run.status === "completed";
  const narrationIndex = current === -1 ? STEPS.length - 1 : Math.max(0, current - 1);
  const progress = (elapsed / TOTAL) * 100;

  return (
    <section className="card story" aria-labelledby="story-title" data-running={running ? "true" : undefined}>
      <div className="story-head">
        <div>
          <p className="eyebrow">
            <span className="pill" data-tone="sim">Simulated</span>
            Demo story · {roomName}
          </p>
          <h2 id="story-title">
            {finished ? "Story complete" : run.status === "stopped" ? "Demo stopped" : run.status === "failed" ? "Demo failed" : STEPS[narrationIndex].title}
          </h2>
        </div>
        <div className="story-clock">
          <span className="num">{mmss(elapsed)}</span>
          <span>of 30:00 story time</span>
          {running && (
            <button type="button" className="button quiet small" onClick={onStop}>
              <Icon name="stop" size={12} />
              Stop
            </button>
          )}
        </div>
      </div>

      <p className="story-say" aria-live="polite">
        {run.status === "failed" && run.error
          ? run.error
          : finished && current === -1
            ? "All six moments happened, each decided by the engine from the readings. Open any room in the building below to see its own evidence."
            : STEPS[narrationIndex].say}
      </p>

      <div className="story-track" aria-hidden="true">
        <span className="story-fill" style={{ width: `${progress}%` }} />
        {STEPS.map((s, i) => (
          <i key={s.title} style={{ left: `${(s.expect / TOTAL) * 100}%` }} data-done={reached[i] !== null ? "true" : undefined} />
        ))}
      </div>

      <ol className="story-steps">
        {STEPS.map((s, i) => {
          const status = reached[i] !== null ? "done" : i === current && running ? "current" : "pending";
          return (
            <li key={s.title} data-status={status}>
              <span className="step-mark" aria-hidden="true">
                {status === "done" ? <Icon name="check" size={12} /> : i + 1}
              </span>
              <div>
                <b>{s.title}</b>
                <span>{reached[i] !== null ? `at ${mmss(reached[i]!)}` : `around ${mmss(s.expect)}`}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
