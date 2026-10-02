"use client";

/** Live data for one room: REST for the first load, WebSocket for every update after that. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  messageToPoint,
  WS_URL,
  type HistoryPoint,
  type LiveMessage,
  type RoomAnalytics,
} from "./api";

export type Connection = "connecting" | "live" | "offline";

const MAX_POINTS = 600;
const RECONCILE_MS = 15_000;

export interface RoomLive {
  analytics: RoomAnalytics | null;
  history: HistoryPoint[];
  latest: LiveMessage | null;
  connection: Connection;
  /** Fetch analytics + history again right now (used after starting a demo). */
  refresh: () => void;
}

export function useRoomLive(roomId: number | null): RoomLive {
  const [analytics, setAnalytics] = useState<RoomAnalytics | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [latest, setLatest] = useState<LiveMessage | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [tick, setTick] = useState(0);
  const lastMs = useRef<number>(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // REST: initial load, periodic reconciliation (also refreshes the energy totals and stale flag)
  useEffect(() => {
    if (roomId === null) return;
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const [a, h] = await Promise.all([
          api.analytics(roomId, controller.signal),
          api.history(roomId, MAX_POINTS, controller.signal),
        ]);
        if (cancelled) return;
        setAnalytics(a);
        setHistory(h);
        lastMs.current = h.length ? Date.parse(h[h.length - 1].timestamp) : 0;
      } catch {
        /* the connection indicator tells the story; keep the last good data on screen */
      }
    };

    setAnalytics(null);
    setHistory([]);
    setLatest(null);
    lastMs.current = 0;
    void load();
    const timer = window.setInterval(load, RECONCILE_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [roomId, tick]);

  // WebSocket: push updates with automatic reconnect
  useEffect(() => {
    if (roomId === null) return;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let closedByUs = false;
    let attempt = 0;

    const onMessage = (event: MessageEvent<string>) => {
      let message: LiveMessage;
      try {
        message = JSON.parse(event.data) as LiveMessage;
      } catch {
        return;
      }
      if (message.room_id !== roomId) return;
      const point = messageToPoint(message);
      const ms = Date.parse(point.timestamp);
      setLatest(message);
      setHistory((previous) => {
        // Time went backwards: a new simulation replaced the old data, so start the chart over.
        if (ms < lastMs.current) {
          lastMs.current = ms;
          return [point];
        }
        // Same reading we already have (the snapshot sent right after connecting).
        if (ms === lastMs.current) return previous;
        lastMs.current = ms;
        const next = previous.length >= MAX_POINTS ? previous.slice(previous.length - MAX_POINTS + 1) : previous.slice();
        next.push(point);
        return next;
      });
    };

    const connect = () => {
      setConnection("connecting");
      socket = new WebSocket(`${WS_URL}/ws/rooms/${roomId}`);
      socket.onopen = () => {
        attempt = 0;
        setConnection("live");
      };
      socket.onmessage = onMessage;
      socket.onclose = () => {
        if (closedByUs) return;
        setConnection("offline");
        attempt += 1;
        retry = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 15_000));
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closedByUs = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [roomId]);

  return { analytics, history, latest, connection, refresh };
}
