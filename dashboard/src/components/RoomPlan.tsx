"use client";

/**
 * Plan view of the selected room: the room itself, its window wall, the sound sensor and the two
 * temperature sensors. Colour follows state (teal occupied, grey vacant, hatched amber uncertain);
 * the window wall turns amber when the thermal anomaly is flagged. Hover or focus a zone to read it.
 */

import { useId, useState } from "react";
import { STATE_LABEL, degrees, percent } from "@/lib/words";
import Icon from "./Icons";
import type { RoomView } from "./Headline";

type Zone = "room" | "wall";

export default function RoomPlan({ name, view }: { name: string; view: RoomView }) {
  const uid = useId().replace(/:/g, "");
  const live = view.hasData && !view.stale;
  const [hover, setHover] = useState<Zone | null>(null);

  const flagged = live && view.leak;
  const zone: Zone = hover ?? (flagged ? "wall" : "room");
  const state = live ? view.state : "uncertain";
  const anomaly = live && view.anomaly !== null ? Math.max(0, Math.min(1, view.anomaly)) : 0;
  const warm = flagged || anomaly >= 0.5;

  const roomFill = !live ? "var(--surface-2)" : state === "occupied" ? "var(--accent-wash)" : state === "vacant" ? "var(--surface-2)" : `url(#hatch-${uid})`;
  const roomStroke = !live ? "var(--line-strong)" : state === "occupied" ? "var(--accent-line)" : state === "vacant" ? "var(--line-strong)" : "var(--warn-line)";
  const wallColor = warm ? "var(--warn)" : live ? "var(--ink-3)" : "var(--line-strong)";
  const sensorColor = !live ? "var(--ink-3)" : state === "occupied" ? "var(--accent)" : "var(--ink-2)";

  const label = (text: string, x: number, y: number, anchor: "start" | "middle" | "end" = "start", fill = "var(--ink-3)", size = 11) => (
    <text x={x} y={y} textAnchor={anchor} style={{ fill, fontSize: size, fontFamily: "var(--font)" }}>
      {text}
    </text>
  );

  const zoneProps = (z: Zone) => ({
    className: "plan-zone",
    tabIndex: 0,
    role: "group" as const,
    onMouseEnter: () => setHover(z),
    onMouseLeave: () => setHover(null),
    onFocus: () => setHover(z),
    onBlur: () => setHover(null),
  });

  return (
    <section className="card plan-card" aria-labelledby="plan-title">
      <div className="plan-top">
        <h3 id="plan-title" className="card-title">
          <Icon name="room" size={15} />
          Room plan
        </h3>
        <span className="pill" data-tone={!live ? undefined : flagged ? "warn" : state === "occupied" ? "occupied" : state === "uncertain" ? "uncertain" : undefined}>
          <span className="dot" />
          {live ? STATE_LABEL[state] : "No recent data"}
        </span>
      </div>

      <div className="plan-frame">
        <svg viewBox="0 0 600 310" role="img" aria-label={`Plan of ${name}. ${live ? `${STATE_LABEL[state]}. Room ${degrees(view.room)}, window wall ${degrees(view.edge)}.` : "No recent data."}`}>
          <defs>
            <pattern id={`hatch-${uid}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="7" height="7" fill="var(--surface-2)" />
              <line x1="0" y1="0" x2="0" y2="7" strokeWidth="1.4" style={{ stroke: "var(--hatch)", opacity: 0.55 }} />
            </pattern>
            <pattern id={`grid-${uid}`} width="34" height="34" patternUnits="userSpaceOnUse">
              <path d="M34 0H0V34" fill="none" strokeWidth="1" style={{ stroke: "var(--line)" }} />
            </pattern>
            <linearGradient id={`heat-${uid}`} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" style={{ stopColor: "var(--warn)", stopOpacity: 0.26 }} />
              <stop offset="1" style={{ stopColor: "var(--warn)", stopOpacity: 0 }} />
            </linearGradient>
          </defs>

          {/* outside */}
          <rect x="0" y="0" width="600" height="310" fill="none" />
          <rect x="40" y="40" width="340" height="230" fill={`url(#grid-${uid})`} opacity="0.7" />

          {/* thermal wash leaving the window wall: width follows the anomaly score */}
          <rect
            x="386"
            y="52"
            width={20 + anomaly * 150}
            height="206"
            fill={`url(#heat-${uid})`}
            style={{ opacity: live ? 0.4 + anomaly * 0.6 : 0, transition: "width 500ms ease, opacity 400ms ease" }}
          />

          {/* room */}
          <g {...zoneProps("room")} aria-label={`${name}: ${live ? `${STATE_LABEL[state]}, ${percent(view.confidence)} chance occupied` : "no recent data"}`}>
            <rect x="40" y="40" width="340" height="230" rx="3" fill={roomFill} strokeWidth="1.5" style={{ stroke: roomStroke, strokeDasharray: live ? undefined : "5 5", transition: "fill 400ms ease, stroke 400ms ease" }} />
            <rect className="zone-ring" x="34" y="34" width="352" height="242" rx="7" fill="none" strokeWidth="1" style={{ stroke: "var(--accent)" }} />
          </g>

          {/* door on the left wall */}
          <rect x="37" y="196" width="6" height="44" style={{ fill: "var(--surface)" }} />
          <path d="M40 240 A44 44 0 0 1 84 240" fill="none" strokeWidth="1" strokeDasharray="3 3" style={{ stroke: "var(--ink-3)" }} />
          <line x1="40" y1="240" x2="40" y2="196" strokeWidth="1.5" style={{ stroke: "var(--ink-3)" }} />
          {label("Door", 52, 188)}

          {/* sound sensor */}
          <g>
            {live && state === "occupied" && (
              <g aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <circle key={i} className="wave" cx="130" cy="155" r="52" fill="none" strokeWidth="1.25" style={{ stroke: "var(--accent)" }} />
                ))}
              </g>
            )}
            <circle cx="130" cy="155" r="13" strokeWidth="1.5" style={{ fill: "var(--surface)", stroke: sensorColor }} />
            <path d="M121 155h4l2.5-6 3.5 12 3-9 2 3h5" fill="none" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" style={{ stroke: sensorColor }} />
            {label("Sound sensor", 130, 188, "middle")}
          </g>

          {/* room temperature sensor */}
          <g>
            <circle cx="262" cy="155" r="5" strokeWidth="2" style={{ fill: "var(--series-room)", stroke: "var(--surface)" }} />
            {label("Room", 262, 128, "middle")}
            <text x="262" y="178" textAnchor="middle" style={{ fill: "var(--ink)", fontSize: 15, fontFamily: "var(--mono)", letterSpacing: "-0.03em" }}>
              {live ? degrees(view.room) : "–"}
            </text>
          </g>

          {/* the gap between the two sensors */}
          {live && view.delta !== null && view.delta > 0.3 && (
            <g aria-hidden="true">
              <line x1="274" x2="374" y1="155" y2="155" className={warm ? "flow" : undefined} strokeWidth="1.5" strokeDasharray="5 3" style={{ stroke: warm ? "var(--warn)" : "var(--ink-3)" }} />
              <path d="M368 150 l6 5 -6 5" fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ stroke: warm ? "var(--warn)" : "var(--ink-3)" }} />
              <text x="324" y="146" textAnchor="middle" style={{ fill: warm ? "var(--warn)" : "var(--ink-2)", fontSize: 11.5, fontFamily: "var(--mono)" }}>
                gap {view.delta.toFixed(1)} °C
              </text>
            </g>
          )}

          {/* window wall */}
          <g {...zoneProps("wall")} aria-label={`Window wall: ${live ? `${degrees(view.edge)}, gap ${degrees(view.delta)}, thermal anomaly ${percent(view.anomaly)}` : "no recent data"}`}>
            <rect x="372" y="34" width="60" height="242" fill="transparent" />
            <line x1="380" x2="380" y1="40" y2="270" strokeWidth="5" strokeLinecap="butt" style={{ stroke: wallColor, transition: "stroke 400ms ease" }} />
            {/* glazing */}
            {[60, 130, 200].map((y) => (
              <rect key={y} x="376" y={y} width="8" height="40" rx="1" style={{ fill: "var(--surface)", stroke: wallColor, strokeWidth: 1, transition: "stroke 400ms ease" }} />
            ))}
            <rect className="zone-ring" x="368" y="34" width="24" height="242" rx="6" fill="none" strokeWidth="1" style={{ stroke: warm ? "var(--warn)" : "var(--accent)" }} />
            <circle cx="380" cy="155" r="5" strokeWidth="2" style={{ fill: "var(--series-edge)", stroke: "var(--surface)" }} />
            <text x="398" y="152" style={{ fill: "var(--ink)", fontSize: 15, fontFamily: "var(--mono)", letterSpacing: "-0.03em" }}>
              {live ? degrees(view.edge) : "–"}
            </text>
            {label("Window / wall", 398, 170, "start")}
          </g>

          {label(name, 40, 292, "start", "var(--ink-2)", 12)}
          {label("Outside", 600, 292, "end")}
        </svg>
      </div>

      <dl className="plan-readout" aria-live="polite">
        {zone === "room" ? (
          <>
            <div>
              <dt>State</dt>
              <dd>{live ? STATE_LABEL[state] : "No data"}</dd>
            </div>
            <div>
              <dt>Chance occupied</dt>
              <dd className="num">{live ? percent(view.confidence) : "–"}</dd>
            </div>
            <div>
              <dt>Room temperature</dt>
              <dd className="num">{live ? degrees(view.room) : "–"}</dd>
            </div>
          </>
        ) : (
          <>
            <div>
              <dt>Window / wall</dt>
              <dd className="num">{live ? degrees(view.edge) : "–"}</dd>
            </div>
            <div>
              <dt>Gap to room</dt>
              <dd className="num" style={{ color: warm ? "var(--warn)" : undefined }}>{live ? degrees(view.delta) : "–"}</dd>
            </div>
            <div>
              <dt>Thermal anomaly</dt>
              <dd className="num" style={{ color: warm ? "var(--warn)" : undefined }}>{live ? percent(view.anomaly) : "–"}</dd>
            </div>
          </>
        )}
      </dl>
    </section>
  );
}
