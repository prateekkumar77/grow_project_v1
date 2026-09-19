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

## Light schedule

The grow light has its own ESP32 relay and its own daily on/off schedule
— it is never touched by the decision engine or by auto/manual mode. Two
states, switched from the dashboard:

- **Schedule on**: the light follows a duty cycle anchored to 00:00 UTC —
  on for `on_hours` (1-24, picked from a dashboard dropdown), off for the
  rest of the day. Computed fresh from the current time every cycle, so
  there's no stored timer to lose on a restart.
- **Schedule off**: the light is under direct manual control from the
  dashboard, holding whatever it was last set to.

The schedule toggle is the master switch: `POST /api/light/manual` is
rejected with `409` while the schedule is on, the same way `/api/relay`
rejects a manual fan/AC/pump command outside manual mode. See
`docs/automation-logic.md` for the full behavior and
`docs/DECISIONS.md` for why it's a separate relay rather than reusing the
AC's now-unused one.

## History charts

The dashboard has a second tab, **history**, alongside the live view:

- **Daily readings** — temperature/humidity/soil moisture for a chosen
  UTC day, bucketed into 30-minute or 1-hour averages (a date picker and
  a step toggle control which). Temperature reads off the left axis
  (°C), humidity and soil moisture share the right axis (%), since they're
  already the same unit.
- **Weekly averages** — the same chart shape for a chosen UTC week, at a
  coarser 6-hour resolution (4 points/day, 28 points total) so a week's
  intraday pattern is still visible rather than flattened into one
  average per day.
- **Light schedule** — a pie chart of the current schedule's on/off
  split (green/red, proportional to `on_hours`/`off_hours`), or a
  full-circle single color when the schedule is off and the light is
  under manual control.

Both line charts are aggregated server-side (`GET /api/charts/day` /
`GET /api/charts/week`, backed by the pure functions in
`backend/chart_data.py`) rather than shipping raw rows to the browser to
average client-side — a day at the default telemetry interval is over
4,000 rows, a week over 30,000. A bucket with no readings in it (e.g. the
ESP32 was offline) renders as a genuine gap in the line, not an
interpolated or zeroed value.

Charts are hand-rolled inline SVG with no charting library — consistent
with the rest of the dashboard avoiding external/CDN dependencies (see
`docs/DECISIONS.md`), so the dashboard keeps working with no internet
access at all.

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
| `GET /api/charts/day` | Dashboard | server-aggregated temp/humidity/soil averages for one UTC day, bucketed by `step_minutes` (30 or 60) |
| `GET /api/charts/week` | Dashboard | server-aggregated temp/humidity/soil averages for 7 UTC days, 6-hour buckets (4 points/day) |
| `POST /api/mode` | Dashboard | switch between `auto` and `manual` |
| `POST /api/relay` | Dashboard | command a single relay (manual mode only; fan/ac/pump, not light) |
| `POST /api/light/schedule` | Dashboard | enable/disable the light schedule and set `on_hours` (1-24) |
| `POST /api/light/manual` | Dashboard | command the light directly (only while its schedule is off) |
| `POST /api/export` | Dashboard/manual | generate an Excel export and return the `.xlsx` file itself |

## Home Assistant / Google Home

`backend/ha_client.py` calls Home Assistant's REST API to toggle a
Google Home-linked smart plug and to announce alerts via a Google Home
speaker (`tts.speak`), debounced so the same alert type doesn't repeat
more than once every `HA_ALERT_DEBOUNCE_SECONDS`. A Home Assistant outage
never blocks or breaks `/api/telemetry` — failures are logged and ignored.

Confirm the exact `tts.speak` payload against your own Home Assistant
version via Developer Tools → Actions before relying on it in production;
see `docs/DECISIONS.md` for why.

The backend never talks to Google directly — it only ever calls Home
Assistant's REST API over the local network; HA is what actually reaches
your Google Home devices (Cast for speakers, whatever integration matches
your smart plug/AC for switches).

### AC as a Google Home device (no physical relay)

If your AC is a Google Home device (smart plug or native smart AC) rather
than something wired to the ESP32's relay board, the backend can drive it
entirely through Home Assistant instead: set `HA_AC_ENTITY` to its entity
ID and `HA_AC_DOMAIN` to `switch` (smart plug) or `climate` (native smart
AC). The decision engine's `ac` output is pushed to that entity via
`ha_client.set_ac()` whenever it changes — automatically after each
`/api/telemetry` cycle in auto mode, or immediately on a manual
`/api/relay` toggle, since there's no ESP32 relay for a manual command to
reach otherwise.

One consequence: the firmware's offline emergency-temperature floor
(`EMERGENCY_TEMP_C`) can only drive a physical relay, so it no longer
protects the AC specifically if it has no relay — only the fan still has
that offline backstop. See `docs/automation-logic.md` and
`docs/DECISIONS.md` for the full reasoning.

Because of that dependency, the dashboard puts AC control in its own
"home assistant" panel, separate from the ESP32 relay tiles, with a live
badge showing whether Home Assistant is actually reachable right now.
That check runs on its own background schedule
(`HA_HEALTH_CHECK_INTERVAL_SECONDS`, default 30s) against Home Assistant's
own `GET /api/` health endpoint — never inline with a request — so a
slow or hanging Home Assistant can't add latency to a dashboard load.
