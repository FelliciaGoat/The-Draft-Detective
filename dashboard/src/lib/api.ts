/** Typed client for the FastAPI backend (mirrors the backend's Pydantic schemas). */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");

export type RoomState = "occupied" | "vacant" | "uncertain";
export type RecommendedAction =
  | "normal_operation"
  | "energy_saving_mode"
  | "inspect_envelope"
  | "maintain_safe_state"
  | "insufficient_data";

export interface Room {
  id: number;
  name: string;
  building: string;
  floor: number;
  zone: string | null;
  climate_zone: string | null;
}

export interface DashboardSummary {
  total_rooms: number;
  occupied_rooms: number;
  vacant_rooms: number;
  uncertain_rooms: number;
  thermal_anomalies: number;
  rooms_recommended_for_energy_saving: number;
  estimated_energy_saved_today: number;
  estimated_energy_saved_this_month: number;
  includes_simulated_data: boolean;
  rooms_without_fresh_data: number;
}

export interface Energy {
  estimated_savings_kwh_today: number;
  avoided_runtime_hours_today: number;
  measured_savings_kwh_today: number | null;
}

export interface RoomAnalytics {
  room_id: number;
  room_name: string;
  has_data: boolean;
  stale: boolean;
  simulated: boolean;
  last_updated: string | null;
  data_age_seconds: number | null;
  current_state: RoomState;
  occupancy_confidence: number | null;
  temperature: { room: number | null; edge: number | null; delta: number | null };
  thermal_anomaly: { score: number | null; leak_candidate: boolean; explanation: string };
  recommendation: { action: RecommendedAction; reason: string };
  energy: Energy;
}

export interface HistoryPoint {
  timestamp: string;
  simulated: boolean;
  room_state: RoomState;
  occupancy_confidence: number | null;
  activity_score: number | null;
  room_temperature: number | null;
  edge_temperature: number | null;
  delta_temperature: number | null;
  thermal_anomaly_score: number | null;
  leak_candidate: boolean;
  recommended_action: RecommendedAction;
}

/** Message pushed over the WebSocket (and returned by POST /readings). */
export interface LiveMessage {
  room_id: number;
  timestamp: string;
  simulated: boolean;
  room_state: RoomState;
  temperature: { room: number | null; edge: number | null; delta: number | null };
  occupancy: { state: RoomState; confidence: number | null; activity_score: number | null };
  thermal: {
    delta_temperature: number | null;
    thermal_anomaly_score: number | null;
    leak_candidate: boolean;
    explanation: string;
  };
  recommendation: { action: RecommendedAction; reason: string };
}

export interface SimulationRun {
  run_id: string;
  status: "completed" | "running" | "stopped" | "failed";
  readings_planned: number;
  readings_generated: number;
  error: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", signal });
  if (!response.ok) throw new ApiError(`${path} returned ${response.status}`, response.status);
  return (await response.json()) as T;
}

export const api = {
  rooms: (signal?: AbortSignal) => getJson<Room[]>("/api/v1/rooms", signal),
  summary: (signal?: AbortSignal) => getJson<DashboardSummary>("/api/v1/dashboard/summary", signal),
  analytics: (roomId: number, signal?: AbortSignal) =>
    getJson<RoomAnalytics>(`/api/v1/rooms/${roomId}/analytics`, signal),
  history: (roomId: number, limit = 400, signal?: AbortSignal) =>
    getJson<HistoryPoint[]>(`/api/v1/rooms/${roomId}/history?limit=${limit}`, signal),
};

/** Convert a live message into a chart/history point. */
export function messageToPoint(message: LiveMessage): HistoryPoint {
  return {
    timestamp: message.timestamp,
    simulated: message.simulated,
    room_state: message.room_state,
    occupancy_confidence: message.occupancy.confidence,
    activity_score: message.occupancy.activity_score,
    room_temperature: message.temperature.room,
    edge_temperature: message.temperature.edge,
    delta_temperature: message.thermal.delta_temperature,
    thermal_anomaly_score: message.thermal.thermal_anomaly_score,
    leak_candidate: message.thermal.leak_candidate,
    recommended_action: message.recommendation.action,
  };
}
