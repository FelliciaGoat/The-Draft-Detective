/** Small stroke icon set, one place so every screen draws icons the same way. */

const PATHS = {
  overview: "M4 4h7v7H4z M13 4h7v4h-7z M13 11h7v9h-7z M4 14h7v6H4z",
  room: "M4 20V5.5L12 3l8 2.5V20 M3 20h18 M9.5 20v-5.5h5V20",
  bolt: "M13 2 5 13.5h6L10 22l8-11.5h-6z",
  thermo: "M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0z",
  users: "M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20 M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35 M15.5 4.2a3.5 3.5 0 0 1 0 6.6",
  alert: "M12 3.5 21.5 20h-19z M12 10v4.5 M12 17.4v.1",
  check: "M5 12.5l4.5 4.5L19 7",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3 2",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M12 2.5v2 M12 19.5v2 M5.3 5.3l1.4 1.4 M17.3 17.3l1.4 1.4 M2.5 12h2 M19.5 12h2 M5.3 18.7l1.4-1.4 M17.3 6.7l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  play: "M8 5v14l11-7z",
  stop: "M7 7h10v10H7z",
  wave: "M3 12h2.5l2-6 3.5 12 3-9 2 3H21",
  hold: "M8 5v14 M16 5v14",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
} as const;

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
