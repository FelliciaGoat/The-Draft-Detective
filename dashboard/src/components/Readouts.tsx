import type { CSSProperties } from "react";
import { degrees, percent } from "@/lib/words";
import Icon from "./Icons";
import type { RoomView } from "./Headline";

function Meter({ value, color, tick }: { value: number | null; color: string; tick?: number }) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="meter" style={{ ["--meter-color" as string]: color } as CSSProperties}>
      <span style={{ width: `${width}%` }} />
      {tick !== undefined && <i style={{ left: `${tick * 100}%` }} />}
    </div>
  );
}

export default function Readouts({ view }: { view: RoomView }) {
  const live = view.hasData && !view.stale;
  const flagged = live && view.leak;
  return (
    <div className="metrics">
      <section className="card metric" aria-labelledby="r-occ">
        <h3 id="r-occ" className="card-title">
          <Icon name="users" size={15} />
          Chance the room is occupied
        </h3>
        <p className="value">{live && view.confidence !== null ? Math.round(view.confidence * 100) : "–"}{live && view.confidence !== null && <small>%</small>}</p>
        <Meter value={live ? view.confidence : null} color="var(--accent)" tick={0.5} />
        <p className="hint">Based on sound only, so it is a confidence and not proof that someone is there.</p>
      </section>

      <section className="card metric" aria-labelledby="r-temp" data-tone={flagged ? "warn" : undefined}>
        <h3 id="r-temp" className="card-title">
          <Icon name="thermo" size={15} />
          Temperatures
        </h3>
        <dl className="temps">
          <div>
            <dt>
              <i className="key-line" style={{ ["--key" as string]: "var(--series-room)" }} />
              Room
            </dt>
            <dd>{degrees(view.room)}</dd>
          </div>
          <div>
            <dt>
              <i className="key-line" style={{ ["--key" as string]: "var(--series-edge)" }} />
              Window / wall
            </dt>
            <dd>{degrees(view.edge)}</dd>
          </div>
          <div className="gap">
            <dt>Gap</dt>
            <dd>{degrees(view.delta)}</dd>
          </div>
        </dl>
      </section>

      <section className="card metric" aria-labelledby="r-anom" data-tone={flagged ? "warn" : undefined}>
        <h3 id="r-anom" className="card-title">
          <Icon name="alert" size={15} />
          Thermal anomaly
        </h3>
        <p className="value">{live && view.anomaly !== null ? Math.round(view.anomaly * 100) : "–"}{live && view.anomaly !== null && <small>%</small>}</p>
        <Meter value={live ? view.anomaly : null} color="var(--warn)" tick={0.5} />
        <p className="hint">A leak candidate is raised only after the gap lasts several minutes. The mark shows the 50% flag level.</p>
      </section>
    </div>
  );
}
