# Grow tent automation system

Automated environmental control for a home grow tent: an ESP32 reports
sensor readings, a FastAPI backend decides what the relays should do, and
a browser dashboard shows/controls it. Optional Home Assistant / Google
Home integration for alerts and a smart plug.

The system is plant-agnostic by design. Nothing about the hardware or
control logic assumes a particular species, strain, or growth stage — what
changes between grows is a small set of threshold values (a "grow
profile," see below), not code.

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

## Methodology

The decision engine doesn't react to absolute sensor values — it reacts to
**change relative to a rolling baseline**. Every telemetry cycle, the
backend computes an average temperature and humidity over the last
`BASELINE_WINDOW_MINUTES` and measures the current reading against that,
not against a fixed number. A tent that's steadily warm isn't a rise; a
sudden climb is. This matters because "normal" varies a lot by plant,
growth stage, and time of day, and a baseline-relative approach keeps
working as those conditions drift without needing new code.

On top of that baseline comparison, three independent rule groups run
every cycle and combine into one relay command:

1. **Humidity** — rising humidity escalates straight to the AC (it pulls
   in cooler, drier air, addressing both variables at once). Unusually low
   humidity does the opposite: AC off, fan on, to pull in comparatively
   humid room air instead.
2. **Temperature** — an escalation ladder rather than a single on/off.
   A moderate rise above baseline tries the fan alone first (cheap, lower
   disturbance); only a larger or sustained rise escalates to the AC.
   This avoids running the more disruptive/expensive intervention for
   fluctuations the fan alone can handle.
3. **Soil moisture** — a threshold with hysteresis: the pump turns on
   below a low-moisture threshold and only turns back off once moisture
   recovers past that threshold *plus a margin*, so it doesn't chatter
   on/off right at the boundary. The firmware backstops this
   independently with a hard maximum run time and cooldown, so a
   misbehaving backend can never over-water.

All of this only runs in **auto** mode. **Manual** mode bypasses the
decision engine entirely — relay state is whatever was last commanded from
the dashboard — and auto-reverts after a period of inactivity so a manual
session can't be left in control indefinitely by accident.

### Grow profile

Every threshold the decision engine uses is a named, environment-variable
constant (see `backend/.env.example`), not a hardcoded number — collectively,
these form the "grow profile" for whatever's in the tent:

| Variable | Governs |
|---|---|
| `HUMIDITY_HIGH_THRESHOLD` / `HUMIDITY_LOW_THRESHOLD` | when AC-on / fan-on-AC-off kicks in for humidity |
| `TEMP_RISE_FAN_THRESHOLD_C` / `TEMP_RISE_AC_THRESHOLD_C` | how far above baseline before fan, then AC, engage |
| `SOIL_MOISTURE_LOW_THRESHOLD` / `SOIL_MOISTURE_HYSTERESIS` | when the pump starts, and how far moisture must recover before it stops |
| `BASELINE_WINDOW_MINUTES` | how far back the rolling baseline looks |
| `ALERT_TEMP_C` | when the backend pushes a Home Assistant alert |

Different plants, growth stages, and tent setups call for different
values here — e.g. an early/vegetative stage generally tolerates higher
humidity and wants a narrower temperature band than a later/flowering
stage, and a larger or more densely planted tent may need a lower soil
moisture threshold to avoid over-triggering the pump. None of that is
encoded in the code: retuning for a different plant or stage means editing
`.env` and restarting the backend, not touching `decision_engine.py`.
Swap in a different `.env` (or maintain one per grow stage and switch
between them) to reuse this same system across completely different
grows.

The dashboard header reflects this too, rather than naming a plant in
code: `GROW_PROFILE_NAME` and `TENT_SIZE_M2` in `.env` are free-text,
display-only fields served from `GET /api/profile` and rendered by the
dashboard on load. They don't feed the decision engine — change them
purely to relabel what's currently in the tent.

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
| `GET /api/profile` | Dashboard | display-only grow profile name/tent size for the header, sourced from `.env` |
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
