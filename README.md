# Grow tent automation system

Automated environmental control for a home grow tent (Bubblegum Auto Fem
autoflower, 0.5m² tent, 75W LED): an ESP32 reports sensor readings, a
FastAPI backend decides what the relays should do, and a browser dashboard
shows/controls it. Optional Home Assistant / Google Home integration for
alerts and a smart plug.

## Architecture

The ESP32 does no environmental decision-making. Every cycle it reports
its sensor readings and its own *actual* relay states to the backend, and
applies whatever relay command comes back in the same response. The only
logic that runs on the ESP32 is safety logic that has to survive a dead
network connection (pump run-time cap/cooldown, an offline emergency
temperature floor). Every real rule — humidity/temperature/soil-moisture
control, manual mode, third-party integrations — lives in the backend.

See [`docs/automation-logic.md`](docs/automation-logic.md) for the control
rules in plain language, and [`docs/DECISIONS.md`](docs/DECISIONS.md) for
judgment calls made where the original brief didn't pin down an exact
value.

## Repository layout

```
firmware/     ESP32 firmware (PlatformIO): sensors, relays + safety, WiFi/HTTP
backend/      FastAPI app: decision engine, persistence, HA client, dashboard
docs/         Control-logic writeup and recorded design decisions
docker-compose.yml   backend + Home Assistant
```

## Running the backend

```bash
cd backend
cp .env.example .env      # edit thresholds, HA token, etc.
docker compose -f ../docker-compose.yml up --build
```

The dashboard is served at `http://localhost:8000/`. Every tunable value
(thresholds, intervals, timeouts, Home Assistant URL/token) comes from
`backend/.env` — see `.env.example` for the full list.

To run the backend directly instead of via Docker:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Run the decision-engine test suite:

```bash
cd backend
pytest
```

## Flashing the firmware

```bash
cd firmware
# edit include/config.h: WiFi credentials, backend host/port, pins
pio run --target upload
```

## API

| Method & path | Caller | Purpose |
|---|---|---|
| `POST /api/telemetry` | ESP32 | report readings + actual relay state, receive the commanded state |
| `GET /api/status` | Dashboard | live mode, commanded/reported relay state, last-seen, latest reading |
| `GET /api/history` | Dashboard | past readings (`limit`, `since`, `until`) |
| `POST /api/mode` | Dashboard | switch between `auto` and `manual` |
| `POST /api/relay` | Dashboard | command a single relay (manual mode only) |
| `POST /api/export` | Dashboard/manual | trigger an immediate Excel export |

## Home Assistant / Google Home

`backend/ha_client.py` calls Home Assistant's REST API to toggle a
Google Home-linked smart plug and to announce alerts via a Google Home
speaker (`tts.speak`), debounced so the same alert type doesn't repeat
more than once every `HA_ALERT_DEBOUNCE_SECONDS`. A Home Assistant outage
never blocks or breaks `/api/telemetry` — failures are logged and ignored.

Confirm the exact `tts.speak` payload against your own Home Assistant
version via Developer Tools → Actions before relying on it in production;
see `docs/DECISIONS.md` for why.
