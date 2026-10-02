import type { RecommendedAction, RoomState } from "@/lib/api";
import { ACTION_LABEL, ACTION_WHY, ageText, kwh } from "@/lib/words";
import Icon, { type IconName } from "./Icons";

export interface RoomView {
  hasData: boolean;
  stale: boolean;
  simulated: boolean;
  state: RoomState;
  confidence: number | null;
  room: number | null;
  edge: number | null;
  delta: number | null;
  anomaly: number | null;
  leak: boolean;
  action: RecommendedAction;
  reason: string;
  ageSeconds: number | null;
  energyToday: number;
}

function sentence(name: string, view: RoomView): string {
  if (!view.hasData) return `No readings yet for ${name}.`;
  if (view.stale) return `${name} has gone quiet.`;
  if (view.state === "occupied") return `${name} looks occupied.`;
  if (view.state === "vacant") return `${name} looks vacant.`;
  return `Can't tell yet whether ${name} is occupied.`;
}

export type Tone = "accent" | "warn" | "neutral";

export function toneOf(view: RoomView): Tone {
  if (!view.hasData || view.stale) return "neutral";
  if (view.leak) return "warn";
  if (view.state === "occupied") return "accent";
  return "neutral";
}

const ACTION_ICON: Record<RecommendedAction, IconName> = {
  inspect_envelope: "alert",
  energy_saving_mode: "bolt",
  insufficient_data: "clock",
  maintain_safe_state: "hold",
  normal_operation: "check",
};

/** What is happening, why it matters, what to do. Amber when a thermal anomaly is being investigated. */
export default function Headline({ name, view }: { name: string; view: RoomView }) {
  const tone = toneOf(view);
  const actionable = view.hasData && !view.stale;
  const action: RecommendedAction = actionable ? view.action : "insufficient_data";
  const iconName: IconName = view.leak && actionable ? "alert" : view.state === "occupied" && actionable ? "users" : ACTION_ICON[action];

  return (
    <section className="card alert" data-tone={tone} aria-labelledby="alert-title">
      <div className="alert-head">
        <span className="alert-icon">
          <Icon name={iconName} size={18} />
        </span>
        <h3 id="alert-title">{sentence(name, view)}</h3>
      </div>

      <dl className="alert-grid">
        <div>
          <dt>What is happening</dt>
          <dd>
            {view.hasData
              ? view.reason
              : "Send a reading from the ESP32, or play the demo story from the panel on the left."}
            {view.stale && view.ageSeconds !== null ? ` Last reading ${ageText(view.ageSeconds)}.` : ""}
          </dd>
        </div>
        <div>
          <dt>Why it matters</dt>
          <dd className="soft">{ACTION_WHY[action]}</dd>
        </div>
        <div>
          <dt>Recommended action</dt>
          <dd>
            <div className="action-row">
              <Icon name={ACTION_ICON[action]} size={17} />
              <strong>{ACTION_LABEL[action]}</strong>
              <small>suggestion only, nothing is switched automatically</small>
            </div>
          </dd>
        </div>
      </dl>

      {view.energyToday > 0 && (
        <p className="saving-line">
          Estimated saving today for this room: <b>{kwh(view.energyToday)} kWh</b> (not measured).
        </p>
      )}
    </section>
  );
}
