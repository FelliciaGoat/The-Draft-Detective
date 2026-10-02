# Acoustic Occupancy & Thermal Leak Dual-Tracker — Backend

FastAPI backend for a hackathon prototype that watches a room with an **ESP32** and answers:

| Question | Output |
|---|---|
| Is anyone probably in the room? | `occupancy_confidence` + state `occupied` / `vacant` / `uncertain` |
| Is something odd happening at the window / exterior wall? | `thermal_anomaly_score` + `leak_candidate` flag |
| What should we do about it? | `recommended_action` (`normal_operation`, `energy_saving_mode`, `inspect_envelope`, `maintain_safe_state`, `insufficient_data`) |
| How much energy could we save? | an **estimated** kWh figure (never presented as measured) |

> **Honest limits (please repeat them in your pitch).**
> Sound does not perfectly reveal occupancy: a quiet person reading looks "vacant", a noisy corridor looks "occupied".
> Two temperature sensors cannot prove a leak: sun, heaters and open doors also create a large temperature difference.
> That is why the system speaks of *confidence*, *anomaly*, *leak candidate* and *recommendation*, falls back to `uncertain` when unsure, and labels energy numbers as **estimates**.
> **Raw audio is never stored or even accepted** — the ESP32 sends one loudness number between 0 and 1.

---

## 1. Architecture

```
 ESP32 (or simulator)
      │  MQTT  building/{building}/room/{room_id}/sensors      REST  POST /api/v1/readings  (X-API-Key)
      ▼                                                          ▼
 ┌──────────────────────────── FastAPI backend ─────────────────────────────┐
 │  validate (Pydantic) ─► store reading ─► OCCUPANCY ─► THERMAL ─► FUSION  │
 │                                                          │               │
 │            ┌──────────── store analytics ◄── ENERGY ESTIMATE ◄┘          │
 │            ▼                                                             │
 │   SQLite / PostgreSQL              WebSocket broadcast  /ws/rooms/{id}   │
 └────────────┬─────────────────────────────────┬───────────────────────────┘
              │ REST (GET)                       │ live push
              ▼                                  ▼
                       Next.js dashboard (http://localhost:3000)
```

* **One pipeline for everything.** REST, MQTT and simulation all call the same `IngestionService`, so a reading is treated identically however it arrives.
* **MQTT never blocks FastAPI.** `paho-mqtt` runs in its own network thread; each message is processed there with its own database session and then pushed to WebSocket clients thread-safely.
* **Business logic lives in `app/services/`.** Route files only translate HTTP ⇄ services.
* **Sync SQLAlchemy on purpose.** Route functions that touch the database are plain `def`; FastAPI runs them in a thread pool, so they do not block the event loop, and the code stays easy to read. WebSockets, startup and background simulation are `async`.

```
backend/
├── app/
│   ├── main.py                    # app factory, CORS, lifespan (starts DB, MQTT, simulation)
│   ├── api/
│   │   ├── deps.py                # DB session, API-key check, shared services
│   │   └── routes/                # rooms, sensors, readings, analytics, simulation, health, ws
│   ├── core/                      # config.py (all thresholds), logging_config.py, enums, time helpers
│   ├── models/                    # SQLAlchemy: Room, Sensor, SensorReading, RoomAnalytics
│   ├── schemas/                   # Pydantic request/response models (the API contract)
│   ├── services/
│   │   ├── occupancy.py           # OccupancyModel interface + RuleBasedOccupancyModel
│   │   ├── thermal.py             # delta-T, anomaly score, persistence
│   │   ├── sensor_fusion.py       # rules → room_state + recommended_action
│   │   ├── energy.py              # transparent kWh ESTIMATE
│   │   ├── ingestion.py           # the shared pipeline
│   │   ├── analytics_service.py   # read-side queries (room analytics, dashboard, history)
│   │   ├── mqtt_service.py        # MQTT subscriber
│   │   ├── websocket_manager.py   # live broadcast
│   │   └── simulation.py          # fake-but-realistic data for demos
│   └── database/                  # engine + sessions, init_db.py (+ demo seed)
├── tests/                         # pytest (155 tests)
├── mosquitto/mosquitto.conf       # dev broker config used by docker-compose
├── Dockerfile · docker-compose.yml · requirements.txt · .env.example · pytest.ini
```

---

## 2. Installation (no Docker)

Requirements: **Python 3.11+**.

### 2.1 Create a virtual environment

macOS / Linux:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):
```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```
(If PowerShell blocks the script: `Set-ExecutionPolicy -Scope Process RemoteSigned`, then activate again.)

### 2.2 Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 Configure environment variables
```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```
Open `.env` and **replace `DEVICE_API_KEY`** with your own secret. Generate one:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./occupancy.db` | SQLite for development; `postgresql+psycopg2://user:pass@host:5432/db` for production |
| `MQTT_ENABLED` | `false` | Turn on the MQTT subscriber (needs a running broker) |
| `MQTT_BROKER` / `MQTT_PORT` | `localhost` / `1883` | Broker address |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | empty | Broker credentials, if any |
| `DEVICE_API_KEY` | *(none)* | Required in the `X-API-Key` header of `POST /readings` and simulation. **If unset the server refuses those requests (503)** |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list of allowed frontend origins |
| `SEED_DEMO_DATA` | `false` (`true` in `.env.example`) | Creates **Room A-101 (id 1)** with its sensors when the database has no rooms |
| `DATA_STALE_SECONDS` | `300` | Data older than this makes a room `uncertain` / `insufficient_data` |
| `DASHBOARD_UTC_OFFSET_MINUTES` | `0` | Defines "today" / "this month" (`330` = India) |
| `DEFAULT_HVAC_POWER_KW` | `1.5` | **Placeholder** HVAC rating for the energy estimate — set your real one (or set it per room) |
| `OCC_*`, `THERMAL_*` | see `app/core/config.py` | All algorithm thresholds (see §11) |
| `SIMULATION_ENABLED` | `true` | Set `false` in production to disable simulation endpoints |

---

## 3. Start the API

```bash
uvicorn app.main:app --reload
```
It listens on **http://localhost:8000**. On first start it creates the database tables (and Room A-101 if `SEED_DEMO_DATA=true`).

Open the interactive documentation:

* Swagger UI: **http://localhost:8000/docs** — click **Authorize** and paste your `DEVICE_API_KEY` once to try protected endpoints
* ReDoc: **http://localhost:8000/redoc**
* Health: http://localhost:8000/api/v1/health

Create the tables / demo room without starting the server (optional):
```bash
python -m app.database.init_db --seed
```

---

## 4. Start MQTT (optional but recommended)

MQTT is how the real ESP32 will normally talk to the backend.

**Option A — Docker (easiest):**
```bash
docker compose up mqtt
```

**Option B — install Mosquitto:**
* macOS: `brew install mosquitto && brew services start mosquitto`
* Ubuntu/Debian: `sudo apt install mosquitto mosquitto-clients && sudo systemctl start mosquitto`
* Windows: install from https://mosquitto.org/download/ and start the service

Then in `.env` set `MQTT_ENABLED=true` (keep `MQTT_BROKER=localhost`, `MQTT_PORT=1883`) and restart uvicorn. The log should say `MQTT connected; subscribed to 'building/+/room/+/sensors'`, and `GET /api/v1/health` should show `"mqtt": "connected"`.

**Topic format:** `building/{building_id}/room/{room_id}/sensors`
`{room_id}` is the **numeric database id** of the room (Room A-101 is `1`); `{building_id}` is informational.

Publish a test message (needs `mosquitto-clients`):
```bash
mosquitto_pub -h localhost -t "building/main/room/1/sensors" -m '{"device_id":"ESP32-A101","acoustic_level":0.72,"room_temperature":24.8,"edge_temperature":29.6}'
```
Invalid messages (bad JSON, impossible values, unknown fields, unknown room) are logged as warnings and dropped; nothing invalid is stored.

> MQTT messages are protected by your **broker** (username/password, TLS), not by `X-API-Key`. The bundled Mosquitto config allows anonymous access for local development only.

---

## 5. Send a test sensor reading (REST)

```bash
export KEY="paste-your-DEVICE_API_KEY-here"     # PowerShell: $KEY = "..."

curl -X POST http://localhost:8000/api/v1/readings \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"device_id":"ESP32-A101","room_id":1,"acoustic_level":0.72,"room_temperature":24.8,"edge_temperature":29.6,"humidity":54.0}'
```
Example response (`201 Created`) — note that the **first** reading is `uncertain`, because the engines need some time to gather evidence:
```json
{
  "reading_id": 1,
  "analytics_id": 1,
  "simulated": false,
  "result": {
    "room_id": 1,
    "timestamp": "2026-09-29T09:42:54.227896Z",
    "simulated": false,
    "room_state": "uncertain",
    "temperature": { "room": 24.8, "edge": 29.6, "delta": 4.8 },
    "occupancy": { "state": "uncertain", "confidence": 0.65, "activity_score": 0.72 },
    "thermal": {
      "delta_temperature": 4.8,
      "thermal_anomaly_score": 0.467,
      "leak_candidate": false,
      "explanation": "Small temperature differential (delta 4.8 C); within the normal range."
    },
    "recommendation": {
      "action": "maintain_safe_state",
      "reason": "Occupancy is uncertain; keeping current comfort settings."
    }
  }
}
```

Read the results:
```bash
curl http://localhost:8000/api/v1/rooms/1/analytics
curl http://localhost:8000/api/v1/dashboard/summary
curl "http://localhost:8000/api/v1/rooms/1/history?limit=100"
```

Notes on the payload:
* Only `device_id` and `room_id` plus **at least one measurement** are required. Acoustic + two temperatures is enough; `humidity`, `co2_ppm`, `hvac_on`, `hvac_power_kw` are optional.
* **Omit `timestamp`** unless the ESP32 has a synchronised clock — the server then uses its own time. Timestamps more than 5 minutes in the future are rejected.
* Rejected with `422`: temperatures outside −40…80 °C (this also catches the DS18B20 error codes **−127** and **85.0**), `acoustic_level` outside 0…1, humidity outside 0…100, NaN/∞, empty payloads, and **any unknown field** (so a firmware bug can never upload `raw_audio`).
* Send all sensors in **one** message. If a message has only acoustic data, the thermal part is skipped for that message (and vice versa).

---

## 6. Simulation mode (demo without hardware)

Every simulated row and response is labelled **`simulated: true`** (readings also have `source: "simulation"`, device `SIMULATOR-<room_id>`, and the dashboard reports `includes_simulated_data`). Simulated readings go through the **real** algorithms.

List the scenarios:
```bash
curl http://localhost:8000/api/v1/simulation/scenarios
```

| Scenario | What you should see (default thresholds) |
|---|---|
| `occupied_room` | uncertain ~30 s → **occupied** → `normal_operation` (only acoustic + temperatures, no HVAC info) |
| `empty_room` | uncertain → **vacant** after 5 min → `normal_operation` (HVAC reported off: nothing to save) |
| `empty_room_hvac_on` | vacant after 5 min → **`energy_saving_mode`**, estimated kWh accumulate |
| `occupied_normal_thermal` | occupied; moderate window/room difference stays at score ≈ 0 (a moderate ΔT is *not* a leak) |
| `thermal_anomaly` | occupied, then a large persistent ΔT → leak candidate → **`inspect_envelope`** |
| `noisy_acoustic` | stays **uncertain** → `maintain_safe_state` (the system refuses to guess) |
| `demo_story` | **the hackathon demo**, see below |

### The demo story (Room A-101)

Batch mode (computes 30 simulated minutes instantly and returns the story):
```bash
curl -X POST http://localhost:8000/api/v1/simulation/generate \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"room_id":1,"scenario":"demo_story","duration":1800,"interval":10}'
```

| Simulated time | What happens | Backend result |
|---|---|---|
| 0:00 | Room occupied, 24 °C, edge 25 °C, moderate talking, HVAC on | `uncertain` for ~30 s |
| 0:30 | Persistence period for "occupied" satisfied | `occupied` → `normal_operation` |
| 5:00 | Person leaves, acoustic activity drops | still `occupied` (persistence + hysteresis hold the state) |
| ~11:40 | 5 minutes of very low activity | **`vacant`** + HVAC on → **`energy_saving_mode`** |
| 15:00 | Exterior-wall temperature climbs to ≈ +8 °C above the room | anomaly score rises |
| ~21:50 | Differential has persisted 5 minutes | **thermal anomaly / leak candidate** → **`inspect_envelope`** |

The response contains `transitions` (each change of state/recommendation) and `final_state`. Real output:
```json
"transitions": [
  { "timestamp": "…09:13:04Z", "room_state": "uncertain", "recommended_action": "maintain_safe_state", "occupancy_confidence": 0.496, "thermal_anomaly_score": 0.0,   "leak_candidate": false },
  { "timestamp": "…09:13:34Z", "room_state": "occupied",  "recommended_action": "normal_operation",    "occupancy_confidence": 0.79,  "thermal_anomaly_score": 0.0,   "leak_candidate": false },
  { "timestamp": "…09:24:44Z", "room_state": "vacant",    "recommended_action": "energy_saving_mode",  "occupancy_confidence": 0.05,  "thermal_anomaly_score": 0.0,   "leak_candidate": false },
  { "timestamp": "…09:34:54Z", "room_state": "vacant",    "recommended_action": "inspect_envelope",    "occupancy_confidence": 0.05,  "thermal_anomaly_score": 0.997, "leak_candidate": true  }
]
```

**Live for the dashboard** — stream it in the background (HTTP `202`) while the Next.js page listens on the WebSocket. `speed: 30` compresses 30 simulated minutes into about one real minute:
```bash
curl -X POST http://localhost:8000/api/v1/simulation/generate \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"room_id":1,"scenario":"demo_story","duration":1800,"interval":10,"realtime":true,"speed":30}'
```
Check or stop a run: `GET /api/v1/simulation/runs/{run_id}` · `POST /api/v1/simulation/runs/{run_id}/stop` (with `X-API-Key`).

Good to know:
* `duration` and `interval` are in **seconds**. Persistence periods default to 5 minutes, so use `duration ≥ 900` (and `demo_story` needs ≥ 1500). To get quick transitions with short demos, lower `OCC_VACANT_PERSISTENCE_SECONDS` and `THERMAL_PERSISTENCE_SECONDS` in `.env`.
* With `realtime: true` and `speed > 1`, reading timestamps run *ahead* of the wall clock (accelerated time).
* `clear_previous` (default `true`) deletes earlier **simulated** data of that room before a run so repeated demos do not add up in the energy estimates. Real sensor data is never deleted.
* Use `seed` for identical, reproducible runs.

---

## 7. Run the tests

```bash
pytest                     # everything (about 7 seconds)
pytest tests/test_occupancy.py -v
pytest -k hysteresis
```
The tests use their own temporary SQLite file; they never touch your `occupancy.db`. Coverage: valid/invalid readings, occupancy classification and hysteresis, thermal anomaly persistence, sensor fusion rules, energy maths, all REST endpoints, API-key security, CORS, WebSocket delivery, MQTT message handling (broker-free), simulation scenarios, and swapping the occupancy model without changing the API.

---

## 8. Docker (backend + PostgreSQL + Mosquitto)

```bash
cp .env.example .env       # set DEVICE_API_KEY
docker compose up --build
```
* API + docs: http://localhost:8000/docs
* PostgreSQL: `localhost:5432` (bound to your machine only), MQTT broker: `localhost:1883`
* Inside Docker the backend uses PostgreSQL and MQTT automatically (`DATABASE_URL`, `MQTT_*` are set by `docker-compose.yml`; your `.env` is only used for `DEVICE_API_KEY`, `CORS_ORIGINS`, etc.).
* Stop: `docker compose down` (add `-v` to also delete the database volume).

The project runs perfectly **without** Docker (sections 2–6).

---

## 9. Connect a Next.js dashboard

CORS already allows `http://localhost:3000`. To allow other origins: `CORS_ORIGINS=http://localhost:3000,https://my-dashboard.example.com`.

`.env.local` in the Next.js project:
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

Fetch data (client component or route handler):
```ts
const API = process.env.NEXT_PUBLIC_API_URL;

export async function getSummary() {
  const res = await fetch(`${API}/api/v1/dashboard/summary`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function getRoomAnalytics(roomId: number) {
  const res = await fetch(`${API}/api/v1/rooms/${roomId}/analytics`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
```

Live updates (no refresh needed):
```tsx
"use client";
import { useEffect, useState } from "react";

export function useRoomLive(roomId: number) {
  const [update, setUpdate] = useState<any>(null);

  useEffect(() => {
    const ws = new WebSocket(`${process.env.NEXT_PUBLIC_WS_URL}/ws/rooms/${roomId}`);
    ws.onmessage = (event) => setUpdate(JSON.parse(event.data));
    return () => ws.close();
  }, [roomId]);

  return update; // { room_id, timestamp, simulated, room_state, occupancy, thermal, recommendation, temperature }
}
```
Dashboard tips:
* Show a visible **"SIMULATED"** badge whenever `simulated === true` (or `includes_simulated_data`).
* Show energy as **"Estimated savings"**. `measured_savings_kwh_today` / `measured_energy_saved_today` are always `null` until a power meter is integrated — use that field to keep estimated and measured apart.
* Treat `uncertain` as a first-class state (grey badge), not as an error.
* If `stale` is `true` in the analytics response, the sensor has stopped reporting.
* WebSocket messages: right after connecting you receive the latest known state (if any), then one message per processed reading. A room that does not exist closes the socket with code `4404`.
* Charts: `GET /api/v1/rooms/{id}/history?limit=200`.

The browser cannot send your `DEVICE_API_KEY` safely — never put it in `NEXT_PUBLIC_*` variables. If the dashboard needs a "run demo" button, call the simulation endpoint from a Next.js **server** route handler that holds the key.

---

## 10. Endpoint overview

| Method & path | Purpose | Auth |
|---|---|---|
| `GET /api/v1/health` | database + MQTT status | — |
| `GET/POST /api/v1/rooms`, `GET/PUT/DELETE /api/v1/rooms/{id}` | room CRUD | — (prototype) |
| `GET/POST /api/v1/sensors`, `GET/PUT /api/v1/sensors/{id}` | sensor registry | — (prototype) |
| `POST /api/v1/readings` | **ESP32 ingestion** (store + analyse) | `X-API-Key` |
| `GET /api/v1/readings` | stored readings (newest first) | — |
| `GET /api/v1/rooms/{id}/analytics` | current state, thermal, recommendation, estimated energy | — |
| `GET /api/v1/rooms/{id}/history` | recent analytics points for charts | — |
| `GET /api/v1/dashboard/summary` | building-level numbers | — |
| `GET /api/v1/energy/estimate` | what-if kWh calculator (`hvac_power_kw`, `avoided_runtime_hours`) | — |
| `POST /api/v1/simulation/generate` (+ `/scenarios`, `/runs/{id}`, `/runs/{id}/stop`) | simulation mode | `X-API-Key` (generate, stop) |
| `WS /ws/rooms/{room_id}` | live updates | — |

Prototype security: only data **ingestion** (and simulation) is protected. Room/sensor management and all reads are open — put the API behind a reverse proxy / login before exposing it beyond a demo network.

---

## 11. How the algorithms work (and how to tune them)

**Occupancy (`services/occupancy.py`, baseline).** Raw loudness → *smoothing* (time-aware moving average) → *rolling average* over 120 s = `activity_score` → evidence `high` (≥ 0.30) / `low` (≤ 0.15) / `ambiguous` → *temporal persistence* (30 s of high evidence to become occupied, 300 s of low evidence to become vacant) → *hysteresis* (the 0.15–0.30 band keeps the current state; ambiguity for 10 minutes degrades to `uncertain`). `occupancy_confidence` is P(occupied), consistent with the state and capped at 0.95/0.05 because sound alone is never certain.

**Thermal (`services/thermal.py`).** `ΔT = |room − edge|` → linear score (≤ 2 °C → 0, ≥ 8 °C → 1) → smoothing → the smoothed score must stay ≥ 0.5 for 300 s before `leak_candidate` becomes true; it clears only below 0.35 (hysteresis). A single abnormal reading never raises an alert, and explanations always say "candidate", never "leak confirmed".

**Fusion (`services/sensor_fusion.py`).** Ordered rules, first match wins: no data → `insufficient_data`; leak candidate → `inspect_envelope`; missing acoustics → `insufficient_data`; contradiction (vacant but CO₂ high) → `maintain_safe_state`; uncertain → `maintain_safe_state`; occupied → `normal_operation`; vacant + HVAC on/unknown → `energy_saving_mode`; vacant + HVAC off → `normal_operation`.

**Energy (`services/energy.py`).** `estimated_energy_saved_kwh = hvac_power_kw × avoided_runtime_hours`; monthly = ×30, annual = ×365. In the live pipeline the "avoided runtime" is the time a room spent in `energy_saving_mode` (each reading-to-reading interval is capped at `ENERGY_MAX_INTERVAL_SECONDS`, default 15 min, so a sensor outage is not counted as savings) multiplied by the HVAC rating (reading → room → `DEFAULT_HVAC_POWER_KW`). No savings percentages are invented.

Engine state (rolling windows, timers) is kept **in memory**. After a restart a room starts as `uncertain` and re-learns from new readings — the safe behaviour.

Tune everything in `.env` (defaults in `app/core/config.py`): `OCC_ON_THRESHOLD`, `OCC_OFF_THRESHOLD`, `OCC_OCCUPIED_PERSISTENCE_SECONDS`, `OCC_VACANT_PERSISTENCE_SECONDS`, `THERMAL_DELTA_LOW_C`, `THERMAL_DELTA_HIGH_C`, `THERMAL_PERSISTENCE_SECONDS`, `CO2_OCCUPIED_PPM`, … Invalid combinations (e.g. OFF ≥ ON) stop the server at startup with a clear error.

---

## 12. Example ESP32 payloads

REST body of `POST /api/v1/readings` (header `X-API-Key: <key>`):
```json
{
  "device_id": "ESP32-A101",
  "room_id": 1,
  "acoustic_level": 0.72,
  "room_temperature": 24.8,
  "edge_temperature": 29.6,
  "humidity": 54.0
}
```
MQTT payload (topic `building/main/room/1/sensors`; `room_id` comes from the topic):
```json
{
  "device_id": "ESP32-A101",
  "acoustic_level": 0.72,
  "room_temperature": 24.8,
  "edge_temperature": 29.6
}
```
Firmware guidance: compute `acoustic_level` **on the device** (for example a normalised RMS of a short microphone window, mapped to 0…1 using your microphone's quiet/loud calibration), send one message every 5–30 seconds, and never transmit audio samples.

---

## 13. Future ML architecture (where to plug things in)

The API never knows which occupancy model is running. `services/occupancy.py` defines:

```python
class OccupancyModel(ABC):
    def predict(self, features: OccupancyFeatures) -> OccupancyPrediction: ...
    def reset(self) -> None: ...
```
`RuleBasedOccupancyModel` is today's implementation. To replace it with TinyML, scikit-learn, ONNX or TensorFlow Lite: write a class that implements `OccupancyModel` (loading its model file in `__init__`), return an `OccupancyPrediction`, and register it — one line in `build_registry()` (`services/ingestion.py`) or, in code, `registry.set_occupancy_factory(MyOnnxModel)`. Routes, database, WebSocket and dashboard stay untouched (`tests/test_api.py::test_occupancy_model_can_be_swapped_without_changing_the_api` proves it). `OccupancyFeatures` already has optional `co2_ppm` and `humidity` slots for richer models, and `scikit-learn` / `onnxruntime` are simply *not installed yet* — add them only when you train a model.

| Later feature | Where it plugs in |
|---|---|
| **TinyML on the ESP32** (on-device occupancy classifier) | Send its output as an extra optional field (add it to `ReadingCreate` + `OccupancyFeatures`) or as `acoustic_level`; the backend model becomes a validator/fuser |
| **Server-side ML** (scikit-learn / ONNX) | New `OccupancyModel` implementation as above; train on the stored history (`sensor_readings`, `room_analytics`) exported with pandas |
| **Better thermal reasoning** | Add `outdoor_temperature` (a new optional reading field) and compare ΔT against the expected value for the weather; extend `ThermalAnalyzer` |
| **Digital twin** | A new service that consumes `RoomUpdateMessage`s / history and simulates the room; expose it as another router under `app/api/routes/` |
| **MPC (model-predictive control)** | Consumes the digital twin + occupancy forecast and produces setpoints; today's `recommended_action` becomes one input |
| **BMS integration (BACnet / Modbus / MQTT)** | Publish recommendations from `IngestionService` (e.g. to `building/{b}/room/{r}/recommendation`); keep humans in the loop until measured results justify automation |
| **Measured savings** | Add a `power` sensor (`hvac_power_kw` is already accepted), compute savings against a baseline, and fill the `measured_*` fields that are always `null` today |
| **Migrations / scale** | Replace `create_all` with Alembic; move engine state from memory to Redis if you run several workers |

---

## 14. Data flow, step by step

1. The ESP32 (or the simulator) sends a reading by **MQTT** or **REST**.
2. **Pydantic** validates it; impossible values and unknown fields are rejected.
3. The reading is **stored** (`sensor_readings`); registered sensors of that device get a new `last_seen` (simulated data never does).
4. **Occupancy engine** → smoothing, rolling average, persistence, hysteresis → `occupancy_confidence` + state.
5. **Thermal engine** → ΔT, anomaly score, persistence → `leak_candidate`.
6. **Sensor fusion** → `room_state` + `recommended_action` (+ reason).
7. **Energy estimate** → estimated kWh for the time slice, only while `energy_saving_mode` is recommended.
8. The result is **stored** (`room_analytics`), so `GET …/analytics` and `GET …/dashboard/summary` can read it.
9. A `RoomUpdateMessage` is **pushed over the WebSocket** to dashboards watching that room.

---

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| `401 Invalid or missing API key` | Send the header `X-API-Key: <DEVICE_API_KEY>` exactly as in your `.env` |
| `503 DEVICE_API_KEY is not configured` | You have no `.env` (or an empty key). `cp .env.example .env` and restart |
| `422` on a reading | Read the `detail` list — it names the field and the rule that failed |
| `"mqtt": "disabled"` | Set `MQTT_ENABLED=true` in `.env` and restart |
| `"mqtt": "disconnected"` | Broker not running or wrong `MQTT_BROKER`/`MQTT_PORT`; the backend keeps retrying |
| Room always `uncertain` | Normal for the first ~30 s (occupied) or ~5 min (vacant). Also check that each message contains `acoustic_level` |
| Room `insufficient_data` and `stale: true` | No fresh data for `DATA_STALE_SECONDS` (default 5 min) — the sensor stopped, or the device sends an old timestamp (omit `timestamp`) |
| Dashboard energy numbers look too big after several demos | Keep `clear_previous: true` (default) in simulation requests |
| Browser blocks requests (CORS) | Add your frontend origin to `CORS_ORIGINS` and restart |
