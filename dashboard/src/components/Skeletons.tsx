/** Placeholder shapes shown while data loads, so the layout never jumps. */

export function PageSkeleton() {
  return (
    <div className="skeleton-page" aria-busy="true" aria-label="Connecting to the backend">
      <p className="skeleton-caption">Connecting to the backend…</p>
      <div className="grid">
        <span className="skeleton block kpi-hero" />
        <span className="skeleton block span-3" />
        <span className="skeleton block span-4" />
      </div>
      <span className="skeleton block tall" />
    </div>
  );
}

export function RoomSkeleton({ name }: { name: string }) {
  return (
    <div className="skeleton-room" aria-busy="true" aria-label={`Loading ${name}`}>
      <div className="room-head">
        <h2>{name}</h2>
        <span className="skeleton line" style={{ width: 110 }} />
      </div>
      <div className="grid">
        <span className="skeleton block span-5" />
        <span className="skeleton block span-7" />
      </div>
      <div className="metrics">
        <span className="skeleton block short" />
        <span className="skeleton block short" />
        <span className="skeleton block short" />
      </div>
      <span className="skeleton block tall" />
    </div>
  );
}
