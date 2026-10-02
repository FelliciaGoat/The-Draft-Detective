# Room monitor (Next.js dashboard)

Live dashboard for the Acoustic Occupancy & Thermal Leak Dual-Tracker backend.
It shows:

- **Building view**: every room as a tile on its floor, coloured by state (teal occupied, grey vacant,
  hatched uncertain, dashed no data). An amber window edge means the window wall is drifting from room
  temperature; an amber glowing outline is a leak candidate. Hover a tile for details, click to open it.
- **Room detail**: chance occupied, window/wall vs room temperature, thermal anomaly, timeline and a
  "what changed" log.
- **Live notifications** when any room changes state, and numbers that animate to new values.
- **Demo without hardware**, two buttons:
  - **Run building demo**: adds 7 demo rooms (A-102…A-104, B-201…B-204) if they don't exist and plays
    a different simulated scenario in each, while the selected room plays the 30-minute story.
  - **This room only**: just the story in the selected room.
  A guided timeline above the building ticks off each step of the story (occupied, everyone leaves,
  energy saving, window drifts, leak candidate) from what the engine actually decided.
- Works on phones: the sidebar collapses to a header and the building grid reflows.

## Start it (Mac)

1. Keep the backend running on port 8000 (in its own Terminal tab):
   ```
   cd occupancy-backend
   source .venv/bin/activate
   uvicorn app.main:app --reload
   ```
2. In a second Terminal tab:
   ```
   cd dashboard
   cp .env.local.example .env.local
   npm install
   npm run dev
   ```
3. Open http://localhost:3000

Needs Node 18.18 or newer (`node --version`). If older, install the current LTS from https://nodejs.org.

## Settings (`.env.local`)

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_API_URL` | Where the backend is. Default `http://localhost:8000`. |
| `DEVICE_API_KEY` | Must equal `DEVICE_API_KEY` in the backend's `.env` (e.g. `hackathon-demo-key-2026`). Used only on the server by the demo button, never sent to the browser. |

After changing `.env.local`, stop and rerun `npm run dev`.

## Troubleshooting

- **"Can't reach the backend"**: uvicorn is not running, or the URL above is wrong. The page reconnects by itself.
- **"No rooms yet"**: set `SEED_DEMO_DATA=true` in the backend `.env` and restart it.
- **Demo button says DEVICE_API_KEY is missing / 401**: the two keys differ or `.env.local` was not created; fix and restart `npm run dev`.
- **Browser blocks requests (CORS)**: the backend's `CORS_ORIGINS` must include `http://localhost:3000` (it does by default).
- **Status shows "Offline, retrying"**: the WebSocket dropped; it retries with backoff.

## Design

Dark control-centre theme. Teal = normal/occupied, amber = thermal anomaly and warnings, grey = vacant/inactive. All colours are CSS variables at the top of `src/app/globals.css` (a light theme is available from the sun/moon button). Fonts are Geist, installed by `npm install`.

## Notes

- Occupancy comes from sound only; the temperature gap comes from two sensors. Both are indications, not proof.
- Energy figures are estimates from the HVAC rating, never measurements.
- Simulated readings are always labelled "SIMULATED DATA".
- Use "Show as table" under the chart for the raw numbers; arrow keys move the chart cursor.
