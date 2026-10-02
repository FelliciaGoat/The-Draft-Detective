import type { HistoryPoint } from "@/lib/api";
import { ACTION_SHORT, STATE_LABEL, clock } from "@/lib/words";

const f = (v: number | null, d = 1) => (v === null ? "–" : v.toFixed(d));
const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}`);

/** The same numbers as the chart, as a table: always reachable without hovering. */
export default function DataTable({ points }: { points: HistoryPoint[] }) {
  const rows = points.slice(-80).reverse();
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Latest readings, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">State</th>
            <th scope="col">Room °C</th>
            <th scope="col">Wall °C</th>
            <th scope="col">Gap °C</th>
            <th scope="col">Occupied %</th>
            <th scope="col">Anomaly %</th>
            <th scope="col">Suggestion</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.timestamp}>
              <td>{clock(p.timestamp)}</td>
              <td>{STATE_LABEL[p.room_state]}</td>
              <td>{f(p.room_temperature)}</td>
              <td>{f(p.edge_temperature)}</td>
              <td>{f(p.delta_temperature)}</td>
              <td>{pct(p.occupancy_confidence)}</td>
              <td>{pct(p.thermal_anomaly_score)}</td>
              <td style={{ textAlign: "left" }}>
                {ACTION_SHORT[p.recommended_action]}
                {p.leak_candidate ? " ▲" : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
