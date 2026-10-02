"use client";

/** Short-lived notifications for room changes. Click one to open that room. */

import { useEffect, useState } from "react";
import type { RoomChange } from "@/lib/building";
import { ACTION_LABEL, STATE_LABEL } from "@/lib/words";
import Icon from "./Icons";

const LIFETIME_MS = 6_500;
const MAX_SHOWN = 4;

export default function Toasts({ changes, onOpen }: { changes: RoomChange[]; onOpen: (roomId: number) => void }) {
  const [now, setNow] = useState(() => Date.now());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);

  const shown = changes.filter((c) => now - c.at < LIFETIME_MS && !dismissed.has(c.id)).slice(-MAX_SHOWN);

  return (
    <div className="toasts" aria-live="polite" aria-relevant="additions">
      {shown.map((c) => {
        const tone = c.leak ? "warn" : c.action === "energy_saving_mode" ? "save" : c.state === "occupied" ? "accent" : "neutral";
        return (
          <div className="toast" data-tone={tone} key={c.id}>
            <span className="toast-icon">
              <Icon name={c.leak ? "alert" : c.action === "energy_saving_mode" ? "bolt" : c.state === "occupied" ? "users" : "eye"} size={15} />
            </span>
            <button type="button" className="toast-body" onClick={() => onOpen(c.roomId)}>
              <b>
                {c.roomName} · {c.leak ? "Leak candidate" : STATE_LABEL[c.state]}
              </b>
              <span>{ACTION_LABEL[c.action]}</span>
            </button>
            <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => setDismissed((s) => new Set(s).add(c.id))}>
              ×
            </button>
            <i className="toast-timer" style={{ animationDuration: `${LIFETIME_MS}ms` }} aria-hidden="true" />
          </div>
        );
      })}
    </div>
  );
}
