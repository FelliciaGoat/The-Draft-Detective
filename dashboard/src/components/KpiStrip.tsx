import type { DashboardSummary } from "@/lib/api";
import { kwh } from "@/lib/words";
import AnimatedNumber from "./AnimatedNumber";
import Icon from "./Icons";

interface Props {
  summary: DashboardSummary | null;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Building-wide numbers. The three cards are deliberately different sizes and tones:
 * occupancy is the hero, thermal anomalies turn amber the moment one exists, energy is a quiet teal.
 */
export default function KpiStrip({ summary }: Props) {
  const s = summary;
  const total = s?.total_rooms ?? 0;
  const anomalies = s?.thermal_anomalies ?? 0;
  const saving = s?.rooms_recommended_for_energy_saving ?? 0;

  return (
    <section className="grid" aria-label="Building overview">
      <div className="card kpi kpi-hero">
        <div className="card-title">
          <Icon name="users" size={15} />
          Occupancy
        </div>
        <div className="kpi-value">
          <span className="big">{s ? <AnimatedNumber value={s.occupied_rooms} /> : "–"}</span>
          <span className="of">{s ? `of ${plural(total, "room", "rooms")} occupied` : ""}</span>
        </div>
        <div className="segments" role="img" aria-label={s ? `${s.occupied_rooms} occupied, ${s.vacant_rooms} vacant, ${s.uncertain_rooms} uncertain` : "No data"}>
          {s && total > 0 ? (
            <>
              {s.occupied_rooms > 0 && <i data-s="occupied" style={{ flexGrow: s.occupied_rooms }} />}
              {s.vacant_rooms > 0 && <i data-s="vacant" style={{ flexGrow: s.vacant_rooms }} />}
              {s.uncertain_rooms > 0 && <i data-s="uncertain" style={{ flexGrow: s.uncertain_rooms }} />}
            </>
          ) : (
            <i data-s="vacant" style={{ flexGrow: 1, opacity: 0.25 }} />
          )}
        </div>
        <div className="seg-legend">
          <span>
            <i style={{ background: "var(--accent)" }} />
            Occupied <b>{s?.occupied_rooms ?? "–"}</b>
          </span>
          <span>
            <i style={{ background: "var(--muted)" }} />
            Vacant <b>{s?.vacant_rooms ?? "–"}</b>
          </span>
          <span>
            <i style={{ background: "var(--warn)", opacity: 0.6 }} />
            Uncertain <b>{s?.uncertain_rooms ?? "–"}</b>
          </span>
        </div>
        {s && s.rooms_without_fresh_data > 0 && (
          <p className="kpi-note">
            {s.rooms_without_fresh_data} of {s.total_rooms} rooms have no recent data and count as uncertain.
          </p>
        )}
      </div>

      <div className="card kpi compact span-3" data-tone={anomalies > 0 ? "warn" : undefined}>
        <div className="card-title">
          <Icon name={anomalies > 0 ? "alert" : "thermo"} size={15} />
          Thermal anomalies
        </div>
        <div className="kpi-value">
          <span className="big">{s ? <AnimatedNumber value={anomalies} /> : "–"}</span>
          <span className="of">{anomalies === 1 ? "leak candidate" : "leak candidates"}</span>
        </div>
        <p className="kpi-sub">
          {!s ? "" : anomalies > 0 ? `${plural(anomalies, "room needs", "rooms need")} a look at the seals.` : "No room is flagged."}
        </p>
      </div>

      <div className="card kpi compact span-4" data-tone={s && s.estimated_energy_saved_today > 0 ? "accent" : undefined}>
        <div className="card-title">
          <Icon name="bolt" size={15} />
          Estimated saving today
        </div>
        <div className="kpi-value">
          <span className="big">{s ? <AnimatedNumber value={s.estimated_energy_saved_today} format={(n) => kwh(n)} /> : "–"}</span>
          <span className="unit">kWh</span>
        </div>
        <p className="kpi-sub">
          {s ? `${kwh(s.estimated_energy_saved_this_month)} kWh this month · ${plural(saving, "room", "rooms")} could switch to energy saving` : ""}
        </p>
        <p className="kpi-note">
          Estimates from the HVAC rating, not measurements.
          {s?.includes_simulated_data ? " Includes simulated data." : ""}
        </p>
      </div>
    </section>
  );
}
