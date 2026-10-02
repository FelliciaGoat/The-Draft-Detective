/** Turn a history into a short list of moments where the answer changed. */

import type { HistoryPoint, RecommendedAction, RoomState } from "./api";

export interface RoomEvent {
  timestamp: string;
  state: RoomState;
  action: RecommendedAction;
  leak: boolean;
  confidence: number | null;
}

export function deriveEvents(history: HistoryPoint[]): RoomEvent[] {
  const events: RoomEvent[] = [];
  let key = "";
  for (const p of history) {
    const next = `${p.room_state}|${p.recommended_action}|${p.leak_candidate}`;
    if (next === key) continue;
    key = next;
    events.push({
      timestamp: p.timestamp,
      state: p.room_state,
      action: p.recommended_action,
      leak: p.leak_candidate,
      confidence: p.occupancy_confidence,
    });
  }
  return events;
}

/** One-sentence explanation for an event, written for people rather than for the code. */
export function eventSentence(e: RoomEvent): string {
  if (e.leak) {
    return "The window or wall has stayed much warmer or cooler than the room for several minutes. This is a leak candidate, not a confirmed leak.";
  }
  switch (e.action) {
    case "energy_saving_mode":
      return "Quiet for long enough to call the room vacant while the HVAC may be running.";
    case "normal_operation":
      return e.state === "occupied"
        ? "Steady sound for long enough to call the room occupied."
        : "Room is vacant and nothing needs to change.";
    case "maintain_safe_state":
      return "The sensors do not agree or have not run long enough, so settings stay as they are.";
    case "insufficient_data":
      return "Not enough sensor data to say anything yet.";
    default:
      return "";
  }
}
