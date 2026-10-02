import type { HistoryPoint } from "@/lib/api";
import { deriveEvents, eventSentence } from "@/lib/events";
import { ACTION_SHORT, STATE_LABEL, clock, percent } from "@/lib/words";

export default function EventLog({ history }: { history: HistoryPoint[] }) {
  const events = deriveEvents(history).reverse().slice(0, 12);
  return (
    <section className="card events" aria-labelledby="events-title">
      <h2 id="events-title">What changed</h2>
      {events.length === 0 ? (
        <p className="empty">Changes in state or suggestion will be listed here as they happen.</p>
      ) : (
        <ol>
          {events.map((e) => {
            const markClass = e.state === "uncertain" ? "event-mark hatch" : "event-mark";
            const color = e.leak ? "var(--warn)" : e.state === "occupied" ? "var(--state-occupied)" : "var(--state-vacant)";
            return (
              <li className="event" key={e.timestamp + e.action + e.leak}>
                <time dateTime={e.timestamp}>{clock(e.timestamp)}</time>
                <span className={markClass} style={{ ["--sw" as string]: color }} aria-hidden="true" />
                <div>
                  <p className="title">
                    {ACTION_SHORT[e.action]} <span className="state">· {STATE_LABEL[e.state]}{e.confidence !== null ? `, ${percent(e.confidence)} chance occupied` : ""}</span>
                    {e.leak ? <span className="warn"> · ▲ Leak candidate</span> : null}
                  </p>
                  <p>{eventSentence(e)}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
