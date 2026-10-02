"use client";

/**
 * Building view: every room as a tile on its floor. Colour follows the room's state (teal occupied,
 * grey vacant, hatched uncertain, dashed when there is no fresh data); the window edge of a tile
 * turns amber when that room's window wall drifts from room temperature, and a full amber outline
 * marks a leak candidate. A tile pulses when its state changes. Click or press a tile to open it.
 */

import type { Room, RoomAnalytics, RoomState } from "@/lib/api";
import { ACTION_SHORT, STATE_LABEL, degrees, percent } from "@/lib/words";
import Icon, { type IconName } from "./Icons";

export interface TileData {
  hasData: boolean;
  stale: boolean;
  simulated: boolean;
  state: RoomState;
  confidence: number | null;
  delta: number | null;
  anomaly: number | null;
  leak: boolean;
  action: RoomAnalytics["recommendation"]["action"];
}

export function tileFromAnalytics(a: RoomAnalytics | undefined): TileData | null {
  if (!a) return null;
  return {
    hasData: a.has_data,
    stale: a.stale,
    simulated: a.simulated,
    state: a.current_state,
    confidence: a.occupancy_confidence,
    delta: a.temperature.delta,
    anomaly: a.thermal_anomaly.score,
    leak: a.thermal_anomaly.leak_candidate,
    action: a.recommendation.action,
  };
}

interface Props {
  rooms: Room[];
  tiles: Map<number, TileData> | null;
  changedAt: Map<number, number>;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onRunBuildingDemo?: () => void;
  demoBusy?: boolean;
}

function shortName(name: string): string {
  return name.replace(/^room\s+/i, "");
}

function stateOf(t: TileData | null): "occupied" | "vacant" | "uncertain" | "none" {
  if (!t || !t.hasData || t.stale) return "none";
  return t.state;
}

const STATE_ICON: Record<string, IconName> = {
  occupied: "users",
  vacant: "eye",
  uncertain: "clock",
  none: "wave",
};

function Tile({ room, tile, changed, selected, onSelect }: { room: Room; tile: TileData | null; changed?: number; selected: boolean; onSelect: () => void }) {
  const state = stateOf(tile);
  const live = state !== "none";
  const warm = live && tile !== null && (tile.leak || (tile.anomaly ?? 0) >= 0.5);
  const label = live ? (tile!.leak ? `${STATE_LABEL[tile!.state]}, leak candidate` : STATE_LABEL[tile!.state]) : tile?.hasData ? "No recent data" : "No readings yet";
  const conf = live && tile!.confidence !== null ? Math.max(0, Math.min(1, tile!.confidence)) : 0;

  return (
    <button
      type="button"
      className="tile"
      data-state={state}
      data-leak={live && tile!.leak ? "true" : undefined}
      data-warm={warm ? "true" : undefined}
      aria-pressed={selected}
      onClick={onSelect}
      aria-label={`${room.name}: ${label}${live ? `, ${percent(tile!.confidence)} chance occupied, gap ${degrees(tile!.delta)}, suggestion ${ACTION_SHORT[tile!.action]}` : ""}`}
    >
      <span className="tile-window" aria-hidden="true" />
      {changed !== undefined && <span key={changed} className="tile-pulse" aria-hidden="true" />}
      <span className="tile-top">
        <span className="tile-name">{shortName(room.name)}</span>
        <span className="tile-icon">
          <Icon name={live && tile!.leak ? "alert" : STATE_ICON[state]} size={14} />
        </span>
      </span>
      <span className="tile-state">{label}</span>
      <span className="tile-bar" aria-hidden="true">
        <i style={{ width: `${conf * 100}%` }} />
      </span>
      <span className="tile-meta">
        <span>{live ? percent(tile!.confidence) : "–"}</span>
        <span className={warm ? "warm" : undefined}>{live && tile!.delta !== null ? `Δ ${tile!.delta.toFixed(1)}°` : ""}</span>
      </span>
      {live && (
        <span className="tile-pop" role="presentation">
          <b>{ACTION_SHORT[tile!.action]}</b>
          <span>
            {percent(tile!.confidence)} chance occupied · gap {degrees(tile!.delta)} · anomaly {percent(tile!.anomaly)}
          </span>
        </span>
      )}
    </button>
  );
}

export default function BuildingView({ rooms, tiles, changedAt, selectedId, onSelect, onRunBuildingDemo, demoBusy }: Props) {
  const floors = new Map<number, Room[]>();
  rooms.forEach((r) => floors.set(r.floor, [...(floors.get(r.floor) ?? []), r]));
  const ordered = [...floors.entries()].sort((a, b) => b[0] - a[0]);
  ordered.forEach(([, list]) => list.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })));

  const counts = { occupied: 0, vacant: 0, uncertain: 0, none: 0, leak: 0 };
  rooms.forEach((r) => {
    const t = tiles?.get(r.id) ?? null;
    counts[stateOf(t)] += 1;
    if (stateOf(t) !== "none" && t?.leak) counts.leak += 1;
  });
  const anyLive = counts.occupied + counts.vacant + counts.uncertain > 0;
  const loading = tiles === null;

  return (
    <section className="card building" aria-labelledby="building-title">
      <div className="building-head">
        <div>
          <h2 id="building-title">Building</h2>
          <p>
            {loading
              ? "Reading every room…"
              : `${rooms.length} ${rooms.length === 1 ? "room" : "rooms"} · ${counts.occupied} occupied · ${counts.vacant} vacant · ${counts.uncertain} uncertain${counts.leak ? ` · ${counts.leak} leak candidate${counts.leak > 1 ? "s" : ""}` : ""}`}
          </p>
        </div>
        <ul className="building-key" aria-label="Key">
          <li><i data-k="occupied" />Occupied</li>
          <li><i data-k="vacant" />Vacant</li>
          <li><i data-k="uncertain" />Uncertain</li>
          <li><i data-k="leak" />Leak candidate</li>
          <li><i data-k="none" />No data</li>
        </ul>
      </div>

      <div className="floors">
        {ordered.map(([floor, list]) => (
          <div className="floor" key={floor}>
            <div className="floor-label">
              <strong>{floor === 0 ? "Ground" : `Floor ${floor}`}</strong>
              {list[0]?.zone && <span>{list[0].zone}</span>}
            </div>
            <div className="floor-rooms">
              {list.map((room) =>
                loading ? (
                  <span key={room.id} className="tile skeleton" aria-hidden="true" />
                ) : (
                  <Tile
                    key={room.id}
                    room={room}
                    tile={tiles.get(room.id) ?? null}
                    changed={changedAt.get(room.id)}
                    selected={room.id === selectedId}
                    onSelect={() => onSelect(room.id)}
                  />
                ),
              )}
            </div>
          </div>
        ))}
      </div>

      {!loading && !anyLive && onRunBuildingDemo && (
        <div className="building-empty">
          <p>
            <b>No live readings in any room.</b> Connect an ESP32, or fill a demo building with eight simulated rooms to see
            every state at once.
          </p>
          <button type="button" className="button" onClick={onRunBuildingDemo} disabled={demoBusy}>
            <Icon name="play" size={13} />
            {demoBusy ? "Starting…" : "Run building demo"}
          </button>
        </div>
      )}
    </section>
  );
}
