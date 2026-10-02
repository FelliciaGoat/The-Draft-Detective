"use client";

/**
 * Live snapshot of every room for the building view. Polls each room's analytics (the list is
 * small) and reports the moments a room's state, suggestion or leak flag changes, so the page can
 * pulse that tile and show a notification.
 */

import { useEffect, useRef, useState } from "react";
import { api, type RecommendedAction, type Room, type RoomAnalytics, type RoomState } from "./api";

export interface RoomChange {
  id: string;
  roomId: number;
  roomName: string;
  state: RoomState;
  action: RecommendedAction;
  leak: boolean;
  at: number;
}

export interface Building {
  /** null until the first poll answers */
  byRoom: Map<number, RoomAnalytics> | null;
  /** Wall-clock ms of the last change per room (drives the tile pulse). */
  changedAt: Map<number, number>;
  changes: RoomChange[];
}

const POLL_MS = 2_500;

function keyOf(a: RoomAnalytics): string {
  if (!a.has_data || a.stale) return "none";
  return `${a.current_state}|${a.recommendation.action}|${a.thermal_anomaly.leak_candidate}`;
}

export function useBuilding(rooms: Room[] | null): Building {
  const [byRoom, setByRoom] = useState<Map<number, RoomAnalytics> | null>(null);
  const [changedAt, setChangedAt] = useState<Map<number, number>>(new Map());
  const [changes, setChanges] = useState<RoomChange[]>([]);
  const keys = useRef<Map<number, string>>(new Map());
  const ids = (rooms ?? []).map((r) => r.id).join(",");

  useEffect(() => {
    if (!rooms || rooms.length === 0) return;
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      const results = await Promise.allSettled(rooms.map((r) => api.analytics(r.id, controller.signal)));
      if (cancelled) return;
      const next = new Map<number, RoomAnalytics>();
      const fresh: RoomChange[] = [];
      const now = Date.now();
      results.forEach((result, i) => {
        if (result.status !== "fulfilled") return;
        const a = result.value;
        next.set(a.room_id, a);
        const key = keyOf(a);
        const before = keys.current.get(a.room_id);
        keys.current.set(a.room_id, key);
        // Report real changes only: not the first sight of a room, not a room just coming online
        // (a demo starting would flood the screen), and not a room going quiet.
        if (before !== undefined && before !== "none" && before !== key && key !== "none") {
          fresh.push({
            id: `${a.room_id}-${now}`,
            roomId: a.room_id,
            roomName: rooms[i].name,
            state: a.current_state,
            action: a.recommendation.action,
            leak: a.thermal_anomaly.leak_candidate,
            at: now,
          });
        }
      });
      setByRoom(next);
      if (fresh.length) {
        setChangedAt((m) => {
          const copy = new Map(m);
          fresh.forEach((c) => copy.set(c.roomId, c.at));
          return copy;
        });
        setChanges((list) => [...list, ...fresh].slice(-30));
      }
    };

    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);

  return { byRoom, changedAt, changes };
}
