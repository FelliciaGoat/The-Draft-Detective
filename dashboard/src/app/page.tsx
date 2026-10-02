"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, api, type DashboardSummary, type Room } from "@/lib/api";
import { useRoomLive } from "@/lib/useRoomLive";
import { useBuilding } from "@/lib/building";
import { useDemo } from "@/lib/demo";
import { ageText, STATE_LABEL } from "@/lib/words";
import BuildingView, { tileFromAnalytics, type TileData } from "@/components/BuildingView";
import DataTable from "@/components/DataTable";
import DemoPanel from "@/components/DemoPanel";
import DemoStory from "@/components/DemoStory";
import EventLog from "@/components/EventLog";
import Headline, { toneOf, type RoomView } from "@/components/Headline";
import Icon from "@/components/Icons";
import KpiStrip from "@/components/KpiStrip";
import RoomPlan from "@/components/RoomPlan";
import Readouts from "@/components/Readouts";
import ThemeToggle from "@/components/ThemeToggle";
import Toasts from "@/components/Toasts";
import { RoomSkeleton, PageSkeleton } from "@/components/Skeletons";
import TimelineChart from "@/components/TimelineChart";

const SUMMARY_MS = 2_500;
const ROOMS_MS = 10_000;

export default function Dashboard() {
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [roomId, setRoomId] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const [roomsTick, setRoomsTick] = useState(0);
  const roomHead = useRef<HTMLDivElement>(null);

  // Rooms list
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await api.rooms();
        if (cancelled) return;
        setRooms(list);
        setBackendDown(false);
        setRoomId((current) => (current !== null && list.some((r) => r.id === current) ? current : (list[0]?.id ?? null)));
      } catch {
        if (!cancelled) setBackendDown(true);
      }
    };
    void load();
    const timer = window.setInterval(load, ROOMS_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [roomsTick]);

  // Building summary
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await api.summary();
        if (!cancelled) setSummary(s);
      } catch {
        /* the rooms poll reports the outage */
      }
    };
    void load();
    const timer = window.setInterval(load, SUMMARY_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const { analytics, history, latest, connection, refresh } = useRoomLive(roomId);
  const room = rooms?.find((r) => r.id === roomId) ?? null;

  // Prefer the WebSocket message when it is newer than the last REST fetch.
  const view: RoomView = useMemo(() => {
    const newer =
      latest !== null && (analytics === null || analytics.last_updated === null || Date.parse(latest.timestamp) > Date.parse(analytics.last_updated));
    if (newer && latest) {
      return {
        hasData: true,
        stale: false,
        simulated: latest.simulated,
        state: latest.room_state,
        confidence: latest.occupancy.confidence,
        room: latest.temperature.room,
        edge: latest.temperature.edge,
        delta: latest.temperature.delta,
        anomaly: latest.thermal.thermal_anomaly_score,
        leak: latest.thermal.leak_candidate,
        action: latest.recommendation.action,
        reason: latest.recommendation.reason,
        ageSeconds: 0,
        energyToday: analytics?.energy.estimated_savings_kwh_today ?? 0,
      };
    }
    if (analytics) {
      return {
        hasData: analytics.has_data,
        stale: analytics.stale,
        simulated: analytics.simulated,
        state: analytics.current_state,
        confidence: analytics.occupancy_confidence,
        room: analytics.temperature.room,
        edge: analytics.temperature.edge,
        delta: analytics.temperature.delta,
        anomaly: analytics.thermal_anomaly.score,
        leak: analytics.thermal_anomaly.leak_candidate,
        action: analytics.recommendation.action,
        reason: analytics.recommendation.reason,
        ageSeconds: analytics.data_age_seconds,
        energyToday: analytics.energy.estimated_savings_kwh_today,
      };
    }
    return {
      hasData: false,
      stale: false,
      simulated: false,
      state: "uncertain",
      confidence: null,
      room: null,
      edge: null,
      delta: null,
      anomaly: null,
      leak: false,
      action: "insufficient_data",
      reason: "",
      ageSeconds: null,
      energyToday: 0,
    };
  }, [analytics, latest]);

  const demo = useDemo();
  const building = useBuilding(rooms);

  // A demo just started: reload the room list (the building demo may have added rooms) and this room.
  const demoRunId = demo.story?.run_id;
  useEffect(() => {
    if (!demoRunId) return;
    setRoomsTick((t) => t + 1);
    const timer = window.setTimeout(refresh, 700);
    return () => window.clearTimeout(timer);
  }, [demoRunId, refresh]);

  const openRoom = useCallback((id: number, scroll = true) => {
    setRoomId(id);
    if (scroll && window.matchMedia("(max-width: 999px)").matches) {
      window.setTimeout(() => roomHead.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  }, []);

  const runBuildingDemo = useCallback(() => {
    if (roomId !== null) void demo.start("building", roomId, 30);
  }, [demo, roomId]);

  // Tiles: building poll for every room, with the faster live view for the open room.
  const tiles = useMemo(() => {
    if (!building.byRoom) return null;
    const map = new Map<number, TileData>();
    building.byRoom.forEach((a, id) => {
      const t = tileFromAnalytics(a);
      if (t) map.set(id, t);
    });
    if (roomId !== null && (latest !== null || analytics !== null)) {
      map.set(roomId, {
        hasData: view.hasData,
        stale: view.stale,
        simulated: view.simulated,
        state: view.state,
        confidence: view.confidence,
        delta: view.delta,
        anomaly: view.anomaly,
        leak: view.leak,
        action: view.action,
      });
    }
    return map;
  }, [building.byRoom, roomId, latest, analytics, view]);

  const roomLoading = roomId !== null && analytics === null && latest === null;
  const storyRoom = rooms?.find((r) => r.id === demo.storyRoomId) ?? null;

  const status =
    connection === "live" ? "Live" : connection === "connecting" ? "Connecting" : "Offline, retrying";
  const loading = rooms === null && !backendDown;

  const tone = toneOf(view);
  const live = view.hasData && !view.stale;

  return (
    <div className="app">
      <aside className="side" aria-label="Navigation and demo">
        <div className="brand">
          <span className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 20V6h16v14" />
              <path d="M4 15l16-7" style={{ stroke: "var(--warn)" }} />
              <path d="M9 20v-4" />
            </svg>
          </span>
          <div>
            <strong>Room monitor</strong>
            <span>Occupancy and thermal envelope</span>
          </div>
        </div>

        <div className="side-section">
          <p className="nav-label">Views</p>
          <nav className="nav" aria-label="Views">
            <button type="button" className="nav-item" aria-current="page">
              <Icon name="overview" size={16} />
              Overview
            </button>
          </nav>
        </div>

        <div className="side-section">
          <p className="nav-label">Rooms</p>
          <nav className="nav" aria-label="Rooms">
            {(rooms ?? []).map((r) => (
              <button key={r.id} type="button" className="nav-item" aria-pressed={r.id === roomId} onClick={() => openRoom(r.id, false)}>
                <Icon name="room" size={16} />
                {r.name}
                <span className="tag" data-tone={tagTone(tiles?.get(r.id))} aria-hidden="true" />
              </button>
            ))}
            {rooms !== null && rooms.length === 0 && <span className="nav-label">None yet</span>}
          </nav>
        </div>

        <DemoPanel roomId={roomId} demo={demo} />

        <div className="side-spacer" />
        <div className="side-foot">
          <span className="live">
            <span className="dot" data-on={connection} aria-hidden="true" />
            {status}
          </span>
          <ThemeToggle />
        </div>
      </aside>

      <main className="main">
        <div className="page-head">
          <div>
            <h1>Overview</h1>
            <p>Live status for every room, with the evidence behind each suggestion.</p>
          </div>
          <div className="head-meta">
            {view.simulated && view.hasData && (
              <span className="pill" data-tone="sim">
                Simulated data
              </span>
            )}
            {view.hasData && view.ageSeconds !== null && !view.stale && <span>Updated {ageText(view.ageSeconds)}</span>}
          </div>
        </div>

        {loading && <PageSkeleton />}

        {backendDown && rooms === null && (
          <div className="card blank">
            <h1>Can&apos;t reach the backend.</h1>
            <p>
              The dashboard looks for it at <code>{API_URL}</code>. Start it in the backend folder with{" "}
              <code>uvicorn app.main:app --reload</code>, then this page reconnects by itself.
            </p>
          </div>
        )}

        {rooms !== null && rooms.length === 0 && (
          <div className="card blank">
            <h1>No rooms yet.</h1>
            <p>
              Create one in the backend docs at <code>{API_URL}/docs</code> (POST /api/v1/rooms), or set{" "}
              <code>SEED_DEMO_DATA=true</code> in the backend&apos;s <code>.env</code> and restart it to get Room A-101.
            </p>
          </div>
        )}

        {rooms !== null && rooms.length > 0 && <KpiStrip summary={summary} />}

        {demo.story && storyRoom && (demo.running || demo.story.status !== "stopped") && (
          <DemoStory run={demo.story} roomName={storyRoom.name} onStop={() => void demo.stop()} />
        )}

        {rooms !== null && rooms.length > 0 && (
          <BuildingView
            rooms={rooms}
            tiles={tiles}
            changedAt={building.changedAt}
            selectedId={roomId}
            onSelect={(id) => openRoom(id)}
            onRunBuildingDemo={runBuildingDemo}
            demoBusy={demo.starting}
          />
        )}

        {room && roomLoading && <RoomSkeleton name={room.name} />}

        {room && !roomLoading && (
          <div className="room-enter" key={room.id}>
            <div className="room-head" ref={roomHead}>
              <h2>{room.name}</h2>
              <span className="pill" data-tone={!live ? undefined : tone === "warn" ? "warn" : view.state === "occupied" ? "occupied" : view.state === "uncertain" ? "uncertain" : undefined}>
                <span className="dot" />
                {live ? (tone === "warn" ? `${STATE_LABEL[view.state]}, leak candidate` : STATE_LABEL[view.state]) : view.hasData ? "No recent data" : "No readings yet"}
              </span>
            </div>

            <div className="grid">
              <div className="span-5">
                <Headline name={room.name} view={view} />
              </div>
              <div className="span-7">
                <RoomPlan name={room.name} view={view} />
              </div>
            </div>

            <Readouts view={view} />

            <section className="card chart-block" aria-labelledby="chart-title">
              <div className="chart-head">
                <h2 id="chart-title">
                  {room.name}, last {history.length} readings
                </h2>
                <button type="button" className="link-button" onClick={() => setShowTable((v) => !v)} aria-expanded={showTable}>
                  {showTable ? "Hide table" : "Show as table"}
                </button>
              </div>
              <div className="legend" aria-label="Chart key">
                <span>
                  <i className="key-line" style={{ ["--key" as string]: "var(--series-room)" }} />
                  Room
                </span>
                <span>
                  <i className="key-line" style={{ ["--key" as string]: "var(--series-edge)" }} />
                  Window / wall
                </span>
                <span>
                  <i className="key-line" style={{ ["--key" as string]: "var(--series-conf)" }} />
                  Chance occupied
                </span>
                <span>
                  <i className="key-line" style={{ ["--key" as string]: "var(--series-anom)" }} />
                  Thermal anomaly
                </span>
                <span>
                  <i className="swatch" style={{ ["--sw" as string]: "var(--state-occupied)" }} />
                  Occupied
                </span>
                <span>
                  <i className="swatch" style={{ ["--sw" as string]: "var(--state-vacant)" }} />
                  Vacant
                </span>
                <span>
                  <i className="swatch hatch" />
                  Uncertain
                </span>
                <span>
                  <i className="swatch" style={{ ["--sw" as string]: "var(--warn)" }} />
                  ▲ Leak candidate
                </span>
              </div>
              <TimelineChart points={history} />
              {showTable && <DataTable points={history} />}
            </section>

            <EventLog history={history} />

            <p className="footnote">
              Times follow each reading&apos;s own clock, so a sped-up demo runs ahead of your wall clock. Occupancy comes from
              sound alone and the temperature gap comes from two sensors; both are indications to check, not proof.
            </p>
          </div>
        )}
      </main>
      <Toasts changes={building.changes} onOpen={(id) => openRoom(id)} />
    </div>
  );
}

function tagTone(t: TileData | undefined): string | undefined {
  if (!t || !t.hasData || t.stale) return undefined;
  if (t.leak) return "warn";
  if (t.state === "occupied") return "occupied";
  return undefined;
}
