"use client";

/**
 * One SVG, three aligned panels that share a time axis:
 *   1. temperatures (room vs window/wall) with a drafting-style dimension line for the gap
 *   2. occupancy confidence and thermal anomaly score (0-100 %)
 *   3. room-state strip (hatched = uncertain) and a leak-candidate row
 * A crosshair snaps to the nearest reading and one tooltip lists everything at that moment.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { HistoryPoint } from "@/lib/api";
import { ACTION_SHORT, STATE_LABEL, degrees, percent } from "@/lib/words";

const PAD_L = 46;
const PAD_R = 112;
const A = { top: 20, h: 170 };
const B = { top: 238, h: 110 };
const STRIP = { top: 386, h: 14 };
const LEAK = { top: 404, h: 8 };
const HEIGHT = 450;
const AXIS_Y = 436;

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(860);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    setWidth(Math.max(320, Math.floor(el.getBoundingClientRect().width)));
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceTicks(min: number, max: number, target = 4): number[] {
  const span = Math.max(max - min, 0.5);
  const raw = span / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + 1e-9; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}

function linePath(xs: number[], ys: (number | null)[]): string {
  let d = "";
  let pen = false;
  ys.forEach((y, i) => {
    if (y === null || Number.isNaN(y)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${xs[i].toFixed(1)} ${y.toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** Filled band between two lines, only where both exist. */
function bandPath(xs: number[], top: (number | null)[], bottom: (number | null)[]): string {
  let d = "";
  let start = -1;
  const close = (end: number) => {
    if (start < 0 || end <= start) {
      start = -1;
      return;
    }
    let forward = "";
    let back = "";
    for (let i = start; i <= end; i++) forward += `${i === start ? "M" : "L"}${xs[i].toFixed(1)} ${(top[i] as number).toFixed(1)}`;
    for (let i = end; i >= start; i--) back += `L${xs[i].toFixed(1)} ${(bottom[i] as number).toFixed(1)}`;
    d += `${forward}${back}Z`;
    start = -1;
  };
  for (let i = 0; i < xs.length; i++) {
    if (top[i] !== null && bottom[i] !== null) {
      if (start < 0) start = i;
    } else {
      close(i - 1);
    }
  }
  close(xs.length - 1);
  return d;
}

interface Run {
  from: number;
  to: number;
  key: string;
}

function runsOf(points: HistoryPoint[], pick: (p: HistoryPoint) => string | null): Run[] {
  const runs: Run[] = [];
  points.forEach((p, i) => {
    const key = pick(p);
    if (key === null) return;
    const last = runs[runs.length - 1];
    if (last && last.key === key && last.to === i - 1) last.to = i;
    else runs.push({ from: i, to: i, key });
  });
  return runs;
}

interface Props {
  points: HistoryPoint[];
  busy?: boolean;
}

export default function TimelineChart({ points, busy = false }: Props) {
  const [frameRef, width] = useWidth();
  const patternId = useId().replace(/:/g, "");
  const [active, setActive] = useState<number | null>(null);

  const g = useMemo(() => {
    const times = points.map((p) => Date.parse(p.timestamp));
    let t0 = times[0] ?? 0;
    let t1 = times[times.length - 1] ?? 1;
    if (t1 - t0 < 60_000) {
      t0 -= 30_000;
      t1 = t0 + 60_000;
    }
    const plotW = Math.max(120, width - PAD_L - PAD_R);
    const xAt = (t: number) => PAD_L + ((t - t0) / (t1 - t0)) * plotW;
    const xs = times.map(xAt);

    const temps = points.flatMap((p) => [p.room_temperature, p.edge_temperature]).filter((v): v is number => v !== null);
    let lo = temps.length ? Math.min(...temps) : 20;
    let hi = temps.length ? Math.max(...temps) : 30;
    lo = Math.floor(lo - 1);
    hi = Math.ceil(hi + 1);
    if (hi - lo < 4) hi = lo + 4;
    const yTemp = (v: number | null) => (v === null ? null : A.top + A.h - ((v - lo) / (hi - lo)) * A.h);
    const yUnit = (v: number | null) => (v === null ? null : B.top + B.h - Math.min(1, Math.max(0, v)) * B.h);

    const roomY = points.map((p) => yTemp(p.room_temperature));
    const edgeY = points.map((p) => yTemp(p.edge_temperature));
    const confY = points.map((p) => yUnit(p.occupancy_confidence));
    const anomY = points.map((p) => yUnit(p.thermal_anomaly_score));

    const span = t1 - t0;
    const tickCount = Math.max(2, Math.min(6, Math.floor(plotW / 110)));
    const xTicks = Array.from({ length: tickCount }, (_, i) => t0 + (span * i) / (tickCount - 1));

    return {
      times, t0, t1, plotW, xs, lo, hi, yTemp, yUnit, roomY, edgeY, confY, anomY,
      tempTicks: niceTicks(lo, hi, 4),
      xTicks,
      showSeconds: span < 10 * 60_000,
      stateRuns: runsOf(points, (p) => p.room_state),
      leakRuns: runsOf(points, (p) => (p.leak_candidate ? "leak" : null)),
    };
  }, [points, width]);

  const lastIndex = points.length - 1;
  const focusIndex = active !== null && active <= lastIndex ? active : null;
  const markerIndex = focusIndex ?? lastIndex;

  const nearest = useCallback(
    (clientX: number, rect: DOMRect): number => {
      const x = clientX - rect.left;
      let lo = 0;
      let hi = g.xs.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (g.xs[mid] < x) lo = mid;
        else hi = mid;
      }
      return Math.abs(g.xs[lo] - x) <= Math.abs(g.xs[hi] - x) ? lo : hi;
    },
    [g.xs],
  );

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    if (!points.length) return;
    setActive(nearest(event.clientX, event.currentTarget.ownerSVGElement!.getBoundingClientRect()));
  };

  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    if (!points.length) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setActive((i) => Math.max(0, (i ?? lastIndex) - 1));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setActive((i) => Math.min(lastIndex, (i ?? lastIndex) + 1));
    } else if (event.key === "Escape") {
      setActive(null);
    }
  };

  if (points.length === 0) {
    return <div className="chart-empty">No readings yet. They will appear here as soon as the sensors report.</div>;
  }

  const m = markerIndex;
  const p = points[m];
  const x = g.xs[m];
  const timeLabel = (t: number) =>
    new Date(t).toLocaleTimeString([], g.showSeconds ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { hour: "2-digit", minute: "2-digit" });

  // end labels (only when they do not collide, so they never have to be nudged apart)
  const xEnd = g.xs[lastIndex] + 10;
  const end = points[lastIndex];
  const roomEndY = g.roomY[lastIndex];
  const edgeEndY = g.edgeY[lastIndex];
  const confEndY = g.confY[lastIndex];
  const anomEndY = g.anomY[lastIndex];
  const tempLabelsFit = roomEndY !== null && edgeEndY !== null && Math.abs(roomEndY - edgeEndY) >= 15;
  const unitLabelsFit = confEndY !== null && anomEndY !== null && Math.abs(confEndY - anomEndY) >= 15;

  const dimTop = g.roomY[m] !== null && g.edgeY[m] !== null ? Math.min(g.roomY[m]!, g.edgeY[m]!) : null;
  const dimBottom = g.roomY[m] !== null && g.edgeY[m] !== null ? Math.max(g.roomY[m]!, g.edgeY[m]!) : null;

  const tooltipLeft = x > width * 0.62 ? x - 262 : x + 14;

  const summary =
    `Temperature, occupancy confidence and thermal anomaly over ${points.length} readings. ` +
    `Latest: ${STATE_LABEL[end.room_state]}, room ${degrees(end.room_temperature)}, wall ${degrees(end.edge_temperature)}, ` +
    `occupancy confidence ${percent(end.occupancy_confidence)}, anomaly score ${percent(end.thermal_anomaly_score)}` +
    `${end.leak_candidate ? ", leak candidate" : ""}. Use the left and right arrow keys to inspect readings.`;

  return (
    <div className="chart-frame" ref={frameRef} data-busy={busy}>
      <svg
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="group"
        aria-label={summary}
        tabIndex={0}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        <defs>
          <pattern id={`hatch-${patternId}`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="5" height="5" style={{ fill: "var(--sheet)" }} />
            <line x1="0" y1="0" x2="0" y2="5" strokeWidth="1.6" style={{ stroke: "var(--hatch)" }} />
          </pattern>
        </defs>

        {/* panel titles */}
        <text x={PAD_L} y={A.top - 8} className="svg-title" style={{ fill: "var(--ink-2)", fontSize: 11.5 }}>
          Temperature
        </text>
        <text x={PAD_L} y={B.top - 10} style={{ fill: "var(--ink-2)", fontSize: 11.5 }}>
          Occupancy confidence and thermal anomaly
        </text>
        <text x={PAD_L} y={STRIP.top - 6} style={{ fill: "var(--ink-2)", fontSize: 11.5 }}>
          Room state
        </text>

        {/* gridlines + y ticks (temperature) */}
        {g.tempTicks.map((t) => {
          const y = g.yTemp(t)!;
          return (
            <g key={`ta${t}`}>
              <line x1={PAD_L} x2={PAD_L + g.plotW} y1={y} y2={y} style={{ stroke: "var(--rule)" }} strokeWidth={1} />
              <text x={PAD_L - 8} y={y + 4} textAnchor="end" style={{ fill: "var(--ink-3)", fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
                {t}
              </text>
            </g>
          );
        })}

        {/* gridlines + y ticks (0-100 %) */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = g.yUnit(t)!;
          return (
            <g key={`tb${t}`}>
              <line x1={PAD_L} x2={PAD_L + g.plotW} y1={y} y2={y} style={{ stroke: "var(--rule)" }} strokeWidth={1} />
              <text x={PAD_L - 8} y={y + 4} textAnchor="end" style={{ fill: "var(--ink-3)", fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
                {Math.round(t * 100)}
              </text>
            </g>
          );
        })}

        {/* flagged periods: a faint amber region across all three panels */}
        {g.leakRuns.map((r, i) => {
          const x1 = g.xs[r.from];
          const next = r.to + 1 <= lastIndex ? g.xs[r.to + 1] : g.xs[r.to] + Math.max(3, g.plotW / 400);
          return (
            <rect key={`w${i}`} x={x1} y={A.top - 4} width={Math.max(1, next - x1)} height={LEAK.top + LEAK.h - A.top + 8} rx={2} style={{ fill: "var(--warn)" }} opacity={0.055} />
          );
        })}

        {/* soft area under the 0-100 lines */}
        <path d={bandPath(g.xs, g.confY, g.confY.map((v) => (v === null ? null : B.top + B.h)))} style={{ fill: "var(--series-conf)" }} opacity={0.08} />
        <path d={bandPath(g.xs, g.anomY, g.anomY.map((v) => (v === null ? null : B.top + B.h)))} style={{ fill: "var(--series-anom)" }} opacity={0.1} />

        {/* gap between room and wall: a quiet wash, like a hatched cut in a drawing */}
        <path d={bandPath(g.xs, g.edgeY, g.roomY)} style={{ fill: "var(--series-edge)" }} opacity={0.08} />

        {/* temperature lines */}
        <path d={linePath(g.xs, g.roomY)} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" style={{ stroke: "var(--series-room)" }} />
        <path d={linePath(g.xs, g.edgeY)} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" style={{ stroke: "var(--series-edge)" }} />

        {/* 0-100 lines */}
        <path d={linePath(g.xs, g.confY)} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" style={{ stroke: "var(--series-conf)" }} />
        <path d={linePath(g.xs, g.anomY)} fill="none" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" style={{ stroke: "var(--series-anom)" }} />

        {/* end dots with a surface ring + direct labels */}
        {[
          { y: roomEndY, color: "--series-room" },
          { y: edgeEndY, color: "--series-edge" },
          { y: confEndY, color: "--series-conf" },
          { y: anomEndY, color: "--series-anom" },
        ].map((d, i) =>
          d.y === null ? null : (
            <circle key={i} cx={g.xs[lastIndex]} cy={d.y} r={4} strokeWidth={2} style={{ fill: `var(${d.color})`, stroke: "var(--sheet)" }} />
          ),
        )}
        {tempLabelsFit && (
          <>
            <text x={xEnd} y={edgeEndY! + 4} style={{ fill: "var(--ink)", fontSize: 11.5 }}>
              Wall <tspan fontWeight={650}>{end.edge_temperature?.toFixed(1)}</tspan>
            </text>
            <text x={xEnd} y={roomEndY! + 4} style={{ fill: "var(--ink)", fontSize: 11.5 }}>
              Room <tspan fontWeight={650}>{end.room_temperature?.toFixed(1)}</tspan>
            </text>
          </>
        )}
        {unitLabelsFit && (
          <>
            <text x={xEnd} y={confEndY! + 4} style={{ fill: "var(--ink)", fontSize: 11.5 }}>
              Occupied <tspan fontWeight={650}>{percent(end.occupancy_confidence)}</tspan>
            </text>
            <text x={xEnd} y={anomEndY! + 4} style={{ fill: "var(--ink)", fontSize: 11.5 }}>
              Anomaly <tspan fontWeight={650}>{percent(end.thermal_anomaly_score)}</tspan>
            </text>
          </>
        )}

        {/* dimension line: the temperature gap, drawn the way a drawing would dimension it */}
        {dimTop !== null && dimBottom !== null && dimBottom - dimTop > 3 && (
          <g style={{ stroke: "var(--ink-2)" }} strokeWidth={1.25} fill="none">
            <line x1={x} x2={x} y1={dimTop} y2={dimBottom} />
            <line x1={x - 5} x2={x + 5} y1={dimTop} y2={dimTop} />
            <line x1={x - 5} x2={x + 5} y1={dimBottom} y2={dimBottom} />
          </g>
        )}
        {dimTop !== null && dimBottom !== null && dimBottom - dimTop > 16 && p.delta_temperature !== null && (
          <text
            x={x - 9}
            y={(dimTop + dimBottom) / 2 + 4}
            textAnchor="end"
            strokeWidth={4}
            paintOrder="stroke"
            style={{ fill: "var(--ink)", stroke: "var(--sheet)", fontSize: 11.5, fontWeight: 650 }}
          >
            gap {p.delta_temperature.toFixed(1)} °C
          </text>
        )}

        {/* state strip: dark = occupied, light = vacant, hatched = uncertain (a 2 px gap separates runs) */}
        {g.stateRuns.map((r, i) => {
          const x1 = g.xs[r.from];
          const next = r.to + 1 <= lastIndex ? g.xs[r.to + 1] : g.xs[r.to] + Math.max(3, g.plotW / 400);
          const w = Math.max(1, next - x1 - 2);
          const fill =
            r.key === "occupied" ? "var(--state-occupied)" : r.key === "vacant" ? "var(--state-vacant)" : `url(#hatch-${patternId})`;
          return (
            <rect key={i} x={x1 + 1} y={STRIP.top} width={w} height={STRIP.h} rx={r.key === "uncertain" ? 0 : 2} style={{ fill }}>
              <title>{STATE_LABEL[r.key as keyof typeof STATE_LABEL]}</title>
            </rect>
          );
        })}
        {/* uncertain runs need an outline so the hatch reads as a shape on any surface */}
        {g.stateRuns
          .filter((r) => r.key === "uncertain")
          .map((r, i) => {
            const x1 = g.xs[r.from];
            const next = r.to + 1 <= lastIndex ? g.xs[r.to + 1] : g.xs[r.to] + Math.max(3, g.plotW / 400);
            return (
              <rect key={`o${i}`} x={x1 + 1.5} y={STRIP.top + 0.5} width={Math.max(1, next - x1 - 3)} height={STRIP.h - 1} fill="none" strokeWidth={1} style={{ stroke: "var(--rule-strong)" }} />
            );
          })}

        {/* leak candidate row: red bar + triangle, never colour alone */}
        {g.leakRuns.map((r, i) => {
          const x1 = g.xs[r.from];
          const next = r.to + 1 <= lastIndex ? g.xs[r.to + 1] : g.xs[r.to] + Math.max(3, g.plotW / 400);
          return (
            <g key={`l${i}`}>
              <rect x={x1 + 1} y={LEAK.top} width={Math.max(1, next - x1 - 2)} height={LEAK.h} rx={2} style={{ fill: "var(--warn)" }}>
                <title>Leak candidate</title>
              </rect>
              <path d={`M${x1 + 1} ${LEAK.top - 3} l5 -9 l5 9 Z`} style={{ fill: "var(--warn)" }} transform="translate(0 0)" />
            </g>
          );
        })}

        {/* x axis */}
        {g.xTicks.map((t, i) => (
          <text
            key={i}
            x={Math.min(PAD_L + g.plotW, Math.max(PAD_L, g.xs.length ? PAD_L + ((t - g.t0) / (g.t1 - g.t0)) * g.plotW : PAD_L))}
            y={AXIS_Y}
            textAnchor={i === 0 ? "start" : i === g.xTicks.length - 1 ? "end" : "middle"}
            style={{ fill: "var(--ink-3)", fontSize: 11, fontVariantNumeric: "tabular-nums" }}
          >
            {timeLabel(t)}
          </text>
        ))}

        {/* crosshair + focus dots */}
        {focusIndex !== null && (
          <g>
            <line x1={x} x2={x} y1={A.top} y2={LEAK.top + LEAK.h} strokeWidth={1} style={{ stroke: "var(--ink-3)" }} />
            {[
              [g.roomY[m], "--series-room"],
              [g.edgeY[m], "--series-edge"],
              [g.confY[m], "--series-conf"],
              [g.anomY[m], "--series-anom"],
            ].map(([y, color], i) =>
              y === null ? null : (
                <circle key={i} cx={x} cy={y as number} r={4.5} strokeWidth={2} style={{ fill: `var(${color as string})`, stroke: "var(--sheet)" }} />
              ),
            )}
          </g>
        )}

        {/* pointer capture over the plot area */}
        <rect
          x={PAD_L}
          y={A.top - 4}
          width={g.plotW}
          height={LEAK.top + LEAK.h - A.top + 8}
          fill="transparent"
          onPointerMove={onMove}
          onPointerDown={onMove}
          onPointerLeave={() => setActive(null)}
        />
      </svg>

      {focusIndex !== null && (
        <div className="tooltip" role="status" style={{ left: Math.max(0, tooltipLeft) }}>
          <div className="when">{new Date(p.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</div>
          <div className="row">
            <i className="key-line" style={{ ["--key" as string]: "var(--series-room)" }} />
            <span className="name">Room</span>
            <strong>{degrees(p.room_temperature)}</strong>
          </div>
          <div className="row">
            <i className="key-line" style={{ ["--key" as string]: "var(--series-edge)" }} />
            <span className="name">Window / wall</span>
            <strong>{degrees(p.edge_temperature)}</strong>
          </div>
          <div className="row">
            <i className="key-line" style={{ ["--key" as string]: "var(--series-conf)" }} />
            <span className="name">Chance occupied</span>
            <strong>{percent(p.occupancy_confidence)}</strong>
          </div>
          <div className="row">
            <i className="key-line" style={{ ["--key" as string]: "var(--series-anom)" }} />
            <span className="name">Thermal anomaly</span>
            <strong>{percent(p.thermal_anomaly_score)}</strong>
          </div>
          <div className="state-line">
            {STATE_LABEL[p.room_state]} · {ACTION_SHORT[p.recommended_action]}
            {p.leak_candidate ? <span className="warn"> · ▲ Leak candidate</span> : null}
          </div>
        </div>
      )}
    </div>
  );
}
