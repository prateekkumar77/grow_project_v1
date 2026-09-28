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

The decision engine reacts to **absolute sensor values against fixed
grow-profile thresholds** — no rolling baseline, no history lookup. Every
threshold is a plain environment-variable number (see "Grow profile"
below), so the same reading always produces the same decision regardless
of what the tent was doing an hour ago.

Three independent rule groups run every cycle and combine into one relay
command — **fan, AC, and pump**. Exhaust and light are deliberately not
part of this: both are driven entirely by their own schedules (see
below), never by a sensor reading.

1. **Humidity** — humidity at or above `HUMIDITY_HIGH_THRESHOLD` escalates
   straight to the AC (it pulls in cooler, drier air, addressing both
   variables at once). At or below `HUMIDITY_LOW_THRESHOLD` does the
   opposite: AC off, fan on, to pull in comparatively humid room air
   instead.
2. **Temperature** — an escalation ladder rather than a single on/off,
   all absolute °C values: at or above `TEMP_FAN_THRESHOLD_C` tries the
   fan alone first (cheap, lower disturbance); at or above the higher
   `TEMP_AC_THRESHOLD_C` escalates to the AC. At or below
   `TEMP_LOW_THRESHOLD_C` (unusually cold) does the same thing the
   low-humidity case does: AC off, fan on to pull in warmer room air.
3. **Soil moisture** — a threshold with hysteresis: the pump turns on
   below a low-moisture threshold and only turns back off once moisture
   recovers past that threshold *plus a margin*, so it doesn't chatter
   on/off right at the boundary. The firmware backstops this
   independently with a hard maximum run time and cooldown, so a
   misbehaving backend can never over-water.

All of this only runs in **auto** mode, and only for fan/AC/pump.
**Manual** mode bypasses the decision engine entirely for those three —
relay state is whatever was last commanded from the dashboard — and
auto-reverts after a period of inactivity so a manual session can't be
left in control indefinitely by accident.

### Grow profile

Every threshold the decision engine uses is a named, environment-variable
constant (see `backend/.env.example`), not a hardcoded number — collectively,
these form the "grow profile" for whatever's in the tent:

| Variable | Governs |
|---|---|
| `HUMIDITY_HIGH_THRESHOLD` / `HUMIDITY_LOW_THRESHOLD` | when AC-on / fan-on-AC-off kicks in for humidity |
| `TEMP_FAN_THRESHOLD_C` / `TEMP_AC_THRESHOLD_C` | absolute °C at which fan, then AC, engage |
| `TEMP_LOW_THRESHOLD_C` | absolute °C below which AC turns off and fan pulls in warmer room air |
| `SOIL_MOISTURE_LOW_THRESHOLD` / `SOIL_MOISTURE_HYSTERESIS` | when the pump starts, and how far moisture must recover before it stops |
| `ALERT_TEMP_C` | when the backend force-overrides fan+AC on as a high-temp safety response |

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
rejects a manual fan/ac/pump command outside manual mode. See
`docs/automation-logic.md` for the full behavior.

## Exhaust schedule

The exhaust fan has its own ESP32 relay too, and is **never** part of
`decide_relay_state()` or any sensor-driven decision — it's controlled
exactly the same shape as the light (a schedule/manual master switch),
just with a different kind of schedule: instead of one on/off window per
day, exhaust runs a repeating **duty cycle** — on for `run_minutes`,
repeating every `interval_minutes` (both 1-60, picked from dashboard
dropdowns), off for the remainder of each interval. Anchored to 00:00 UTC
the same way the light schedule is, so it's a pure function of wall-clock
time with no stored timer to lose on a restart.

- **Schedule on**: `is_exhaust_on()` decides, recomputed every telemetry
  cycle.
- **Schedule off**: the exhaust is under direct manual control from the
  dashboard (`POST /api/exhaust/manual`), holding whatever it was last
  set to.

Same master-switch pattern as light: `POST /api/exhaust/manual` is
rejected with `409` while the schedule is enabled, and `run_minutes`
can't exceed `interval_minutes` (rejected with `422`) since running
longer than the cycle itself doesn't mean anything.

## Activity log

The dashboard has a scrollable "recent activity" panel showing the last 20
notable actions, newest first, each with a timestamp and who did it:
mode switches (`auto mode on`/`manual mode on`), relay on/off transitions
for every relay (`fan on`, `pump off`, `light on`, `exhaust off`, `ac on`
- whether triggered by a manual dashboard click or the decision
engine/schedule), light/exhaust schedule toggles and reconfiguration
(`light schedule on`, `light schedule set: 18h on/day`, `exhaust schedule
set: run 1m every 5m`), and data exports. Every entry shows its actor -
the dashboard username for a manual action, or `<auto>` for anything the
decision engine or a schedule did on its own - rendered like `<admin>` or
`<auto>` next to the message.

Only actual transitions are logged - a relay holding steady across
telemetry cycles never adds an entry, so the feed doesn't fill up with
repeats of the same state.

The live feed itself is in-memory only (an `ActivityLog` ring buffer
capped at the last 20 entries, see `backend/activity_log.py`) and resets
on backend restart, like the rest of `AppState` - but every entry is also
durably written to the `activity_log` DB table (unbounded, never capped
or reset) the moment it's recorded. **"download activity log .xlsx"**, next
to the readings export button on the history tab, exports that complete
table - not just the last 20 the live feed shows - the same way "download
.xlsx" exports the full `readings` table.

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
| `GET /api/status` | Dashboard | live mode, commanded/reported relay state, last-seen, latest reading, last 20 activity-log entries |
| `GET /api/profile` | Dashboard | display-only grow profile name/tent size for the header, sourced from `.env` |
| `GET /api/history` | Dashboard | past readings (`limit`, `since`, `until`) |
| `GET /api/charts/day` | Dashboard | server-aggregated temp/humidity/soil averages for one UTC day, bucketed by `step_minutes` (30 or 60) |
| `GET /api/charts/week` | Dashboard | server-aggregated temp/humidity/soil averages for 7 UTC days, 6-hour buckets (4 points/day) |
| `POST /api/mode` | Dashboard | switch between `auto` and `manual` |
| `POST /api/relay` | Dashboard | command a single relay (manual mode only; fan/ac/pump, not light or exhaust) |
| `POST /api/light/schedule` | Dashboard | enable/disable the light schedule and set `on_hours` (1-24) |
| `POST /api/light/manual` | Dashboard | command the light directly (only while its schedule is off) |
| `POST /api/exhaust/schedule` | Dashboard | enable/disable the exhaust duty-cycle schedule and set `run_minutes`/`interval_minutes` (1-60 each) |
| `POST /api/exhaust/manual` | Dashboard | command the exhaust directly (only while its schedule is off) |
| `POST /api/export` | Dashboard/manual | generate an Excel export and return the `.xlsx` file itself |
| `POST /api/activity/export` | Dashboard/manual | export the complete `activity_log` table (not just the last 20) and return the `.xlsx` file itself |
| `GET /api/me` | Dashboard | who's currently authenticated (`username`, `role`) |

## Dashboard access / roles

The dashboard is protected with HTTP Basic Auth - no new dependency, no
sessions, just `base64`/`secrets` from the standard library, matching the
single-file/no-build-step/no-CDN dashboard's own minimal-dependency stance.
Users are declared in the backend's `.env` as a JSON array:

```
DASHBOARD_USERS=[{"username":"admin","password":"changeme-admin","role":"admin"},{"username":"viewer","password":"changeme-viewer","role":"viewer"}]
```

Two roles, nothing configurable beyond them:

- **admin** - full control, identical to the pre-auth dashboard.
- **viewer** - can see everything (`GET` routes: status, history, charts,
  profile) but every mutating call (`POST /api/mode`, `/api/relay`,
  `/api/light/*`, `/api/exhaust/*`, `/api/export`) is rejected with `403`.
  The dashboard UI also disables every button/dropdown for a viewer so
  there's nothing clickable to try in the first place - but the `403` is
  enforced server-side regardless of what the browser does.

`POST /api/telemetry` is the one route with no auth at all - the ESP32
firmware sends no `Authorization` header, so protecting it would just
break every telemetry post. Everything else, including the dashboard's own
static files, requires valid credentials.

Passwords are plaintext in `.env`, same trust model as `HA_TOKEN` and every
other credential already in that file - keep `.env` out of version control.
If `DASHBOARD_USERS` is missing, empty, or malformed, the dashboard fails
closed and rejects every request rather than falling back to a shipped
default login.

**No session timeout.** Basic Auth is stateless - the backend checks
credentials on every request and never issues or tracks a session, so
there's nothing here that expires like `AUTO_REVERT_MINUTES` does for
manual mode. Staying "logged in" is purely the browser caching your
credentials for this origin and resending them automatically; how long
that lasts (until the browser/tab closes, site data is cleared, etc.) is
up to the browser, not this app. There's also no working "log out" button
possible under Basic Auth - only the browser can drop cached credentials.

## Home Assistant / Google Home

Fan, exhaust, pump, and light are physical ESP32 relays. **AC is the one
exception**: it's a Google Home device (a smart plug or native smart
AC/mini-split) with no ESP32 relay, driven entirely through Home
Assistant instead — `backend/ha_client.py` calls Home Assistant's REST
API to turn it on/off, as part of the decision engine's humidity/
temperature escalation (see "Methodology" above). A Home Assistant outage
never blocks or breaks `/api/telemetry` — failures are logged and
ignored, and AC just holds its last state until HA comes back.

The backend never talks to Google directly — it only ever calls Home
Assistant's REST API over the local network; HA is what actually reaches
your AC (whatever integration matches it — a smart-plug switch or a
native smart AC).

There's no separate notification/alert channel — no media or speaker
device is connected, so a high temperature reading doesn't announce
anything. Instead, crossing `ALERT_TEMP_C` forces fan and AC on directly
(see the grow-profile table above), which is itself routed through this
same Home Assistant call for AC.

### AC as a Google Home device (no physical relay)

Set `HA_AC_ENTITY` to your AC's entity ID and `HA_AC_DOMAIN` to `switch`
(smart plug) or `climate` (native smart AC). The decision engine's `ac`
output is pushed to that entity via `ha_client.set_ac()` whenever it
changes — automatically after each `/api/telemetry` cycle in auto mode,
or immediately on a manual `/api/relay` toggle, since there's no ESP32
relay for a manual command to reach otherwise.

One consequence: the firmware's offline emergency-temperature floor
(`EMERGENCY_TEMP_C`) can only drive a physical relay, so while it forces
the fan and exhaust on locally, AC gets no such offline backstop — it's
inherent to AC being an HA-only device. See `docs/automation-logic.md`
and `docs/DECISIONS.md` for the full reasoning.

Because AC control depends on Home Assistant being reachable, the
dashboard gives it its own panel, separate from the ESP32 relay tiles,
with a live badge showing whether Home Assistant is actually reachable
right now. That check runs on its own background schedule
(`HA_HEALTH_CHECK_INTERVAL_SECONDS`, default 30s) against Home Assistant's
own `GET /api/` health endpoint — never inline with a request — so a
slow or hanging Home Assistant can't add latency to a dashboard load.
