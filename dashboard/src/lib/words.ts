/** Plain-language wording for states and actions. One place, so every screen says the same thing. */

import type { RecommendedAction, RoomState } from "./api";

export const STATE_LABEL: Record<RoomState, string> = {
  occupied: "Occupied",
  vacant: "Vacant",
  uncertain: "Uncertain",
};

export const ACTION_LABEL: Record<RecommendedAction, string> = {
  normal_operation: "Keep normal operation",
  energy_saving_mode: "Switch to energy-saving mode",
  inspect_envelope: "Inspect window and wall seals",
  maintain_safe_state: "Hold current settings",
  insufficient_data: "Waiting for sensor data",
};

/** Short form for the event log and tooltips. */
export const ACTION_SHORT: Record<RecommendedAction, string> = {
  normal_operation: "Normal operation",
  energy_saving_mode: "Energy-saving mode",
  inspect_envelope: "Inspect envelope",
  maintain_safe_state: "Hold settings",
  insufficient_data: "No data",
};

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

export function degrees(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "–" : `${value.toFixed(digits)} °C`;
}

export function kwh(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value >= 100 ? value.toFixed(0) : value.toFixed(2);
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function clockShort(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ageText(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 5) return "just now";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

/** Why each suggestion matters, in one sentence a facilities person would say. */
export const ACTION_WHY: Record<RecommendedAction, string> = {
  normal_operation: "People are in the room, so heating or cooling it is doing its job.",
  energy_saving_mode:
    "Heating or cooling an empty room wastes energy. Relaxing the setpoint saves money and nobody notices.",
  inspect_envelope:
    "A window or wall that stays far from the room temperature can mean air is leaking in or out, which makes the HVAC work harder. Sun, a heater or an open door can look the same, so check the seals before concluding anything.",
  maintain_safe_state: "The sensors disagree or have not run long enough, so changing settings now could be a mistake.",
  insufficient_data: "Without fresh readings the system cannot judge the room, so it makes no suggestion.",
};
