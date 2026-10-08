# Grow tent automation system

Automated environmental control for a home grow tent: an ESP32 reports
sensor readings, a FastAPI backend decides what the relays (and the AC,
via IR) should do, and a browser dashboard shows/controls it, with
optional Home Assistant integration for its own reachability badge. The
dashboard is a single HTML file
with no build step - no bundler, no npm install, just edit and reload -
responsive down to a small phone, with a sticky status header and
touch-sized controls throughout. It does load a handful of CDN libraries
(Chart.js, Lucide icons, Motion, Google Fonts) for real charts/icons/
animation/type instead of hand-rolled equivalents - see "CDN dependency"
below for what that trades away.

The system is plant-agnostic: nothing in the hardware or control logic
assumes a species, strain, or growth stage. What changes between grows is
a small set of threshold values (a "grow profile," below), not code.

## Architecture

The ESP32 makes no environmental decisions — every cycle it reports its
sensor readings and actual relay states, and applies whatever command
comes back in the same response. The only logic that runs on the ESP32 is
safety logic that has to survive a dead network connection (pump run-time
cap/cooldown, an offline emergency temperature floor). Every other rule
lives in the backend.

See [`docs/automation-logic.md`](docs/automation-logic.md) for the full
control rules, and [`docs/DECISIONS.md`](docs/DECISIONS.md) for judgment
calls made where the original brief left something unspecified.

## Methodology

The decision engine compares live readings directly against fixed
grow-profile thresholds — no rolling baseline, no history lookup, so the
same reading always produces the same decision. This governs **fan, AC,
and pump**, every cycle, in **auto** mode only. **Light and exhaust** run
on their own independent schedules instead (below) and are never touched
by it. **Manual** mode bypasses the decision engine for fan/AC/pump
entirely — relay state is whatever was last commanded from the dashboard
— and auto-reverts to auto after a period of inactivity.

Full rule-by-rule behavior (humidity, temperature, soil moisture, pump
safety): [`docs/automation-logic.md`](docs/automation-logic.md).

### Grow profile

Every threshold is a named, editable value, not a hardcoded number:

| Variable | Governs |
|---|---|
| `HUMIDITY_HIGH_THRESHOLD` / `HUMIDITY_LOW_THRESHOLD` | when AC-on / fan-on-AC-off kicks in for humidity |
| `TEMP_FAN_THRESHOLD_C` / `TEMP_AC_THRESHOLD_C` | absolute °C at which fan, then AC, engage |
| `TEMP_LOW_THRESHOLD_C` | absolute °C below which AC turns off and fan pulls in warmer room air |
| `SOIL_MOISTURE_LOW_THRESHOLD` / `SOIL_MOISTURE_HYSTERESIS` | when the pump starts, and how far moisture must recover before it stops |
| `ALERT_TEMP_C` | when the backend force-overrides fan+AC on as a high-temp safety response |

Retune these from the dashboard's **profile** tab at any time — no
restart needed, and the edit is saved to the database so it survives one.
`backend/.env.example` (`HUMIDITY_HIGH_THRESHOLD` etc.) only sets the
*first-run* default, before anyone has ever saved a profile; editing it
after that has no effect on a running system. `GROW_PROFILE_NAME`,
`TENT_SIZE_M2`, and `GROW_START_DATE` live in the same profile and tab —
purely cosmetic fields that don't feed the decision engine. Setting a
start date shows a "day N" counter in the dashboard header (day 1 = that
date); leave it blank to omit the counter entirely.

## Light schedule

The grow light has its own ESP32 relay and its own daily on/off schedule
— never touched by the decision engine or auto/manual mode. Two states,
switched from the dashboard:

- **Schedule on**: a duty cycle anchored to 00:00 UTC — on for `on_hours`
  (1-24, dashboard dropdown), off for the rest of the day. Computed fresh
  from the current time every cycle, so there's no stored timer to lose
  on a restart.
- **Schedule off**: direct manual control from the dashboard, holding
  whatever it was last set to.

The schedule toggle is the master switch: `POST /api/light/manual` is
rejected with `409` while it's on, the same way `/api/relay` rejects a
manual command outside manual mode.

## Exhaust schedule

The exhaust fan has its own ESP32 relay too, controlled the same shape as
the light (a schedule/manual master switch), just with a repeating
**duty cycle** instead of a daily window — on for `run_minutes`, off for
the rest of every `interval_minutes` (both 1-60, dashboard dropdowns),
anchored to 00:00 UTC the same way. Never touched by
`decide_relay_state()` or any sensor reading.

`POST /api/exhaust/manual` is rejected with `409` while the schedule is
on, and `run_minutes` can't exceed `interval_minutes` (`422`).

## Activity log

The dashboard's "recent activity" panel shows the last 20 actions,
newest first, each with a timestamp and actor: mode switches, relay
on/off transitions (manual or automatic), schedule changes, and data
exports — e.g. `fan on <admin>` or `pump off <auto>`. Only actual
transitions are logged, never a repeat of steady state.

The live feed is in-memory only (capped at 20 entries, resets on backend
restart) — but every entry is also durably written to the `activity_log`
DB table, unbounded. **"download activity log"**, next to **"download
sensor data"** on the history tab, exports that complete table.

## History charts

A second dashboard tab, **history** (a third, **profile**, covers editing
the grow profile — see above):

- **Daily readings** — temp/humidity/soil moisture for a chosen UTC day,
  30-minute or 1-hour buckets. Temperature on the left axis (°C),
  humidity + soil moisture sharing the right (already the same unit, %).
  Each series also gets a dashed horizontal line at its average over the
  currently-loaded window, with the numeric average shown in the legend.
- **Weekly averages** — same shape for a chosen UTC week, 6-hour buckets
  (28 points) — coarse enough to stay compact while keeping the intraday
  pattern visible.
- **Light schedule** — a pie chart of the current on/off split.

Charts are aggregated server-side (`GET /api/charts/day`/`week`, backed
by `backend/chart_data.py`) rather than shipping raw rows to average in
the browser — a day is 4,000+ rows, a week 30,000+. A bucket with no
readings renders as a gap, never zero or interpolated. Rendered with
Chart.js (see "CDN dependency" below) - its own tooltip fires on tap as
well as hover, so exact values are reachable on a phone with no custom
touch-target code needed.

## CDN dependency

The dashboard loads four libraries from a CDN: **Chart.js** (+ its
annotation plugin, for the average reference lines) for the history
charts, **Lucide** for every icon, **Motion** for a handful of UI
transitions (the offline/stale banners, tab switching, pending
indicators), and **Google Fonts** (Inter + JetBrains Mono) for type. This
is a deliberate departure from this project's earlier "zero CDN, works
with no internet access" stance - accepted so the UI can use a real icon
set, real charts, and a real animation library instead of hand-rolled
equivalents. See `docs/DECISIONS.md` for the reasoning and what it costs:
the dashboard still loads and the live/manual controls still work with no
internet access, but icons render blank, charts show a "charts
unavailable" message, fonts fall back to the OS default, and the handful
of Motion-driven transitions instantly snap instead of animating.

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
cp .env.example .env      # edit thresholds, HA token, DASHBOARD_USERS, etc.
docker compose -f ../docker-compose.yml up --build
```

The dashboard is served at `http://localhost:8000/`. Every tunable value
(thresholds, intervals, timeouts, Home Assistant URL/token, dashboard
logins) comes from `backend/.env` — see `.env.example` for the full list.

To run the backend directly instead of via Docker:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Run the test suite:

```bash
cd backend
pytest
```

### Installing the dashboard as an app

The dashboard ships a web app manifest (`backend/static/manifest.json`) and
icons, so Chrome/Chromium offers a real **Install** button in the address
bar — it opens in its own chromeless window from a desktop/taskbar icon,
same as a native app, with no service worker or offline support involved.
This works automatically over `https://` or `http://localhost`; on a plain
LAN address (`http://192.168.x.x:8000`) Chrome won't offer the install
button since that isn't a secure context, but **⋮ menu → Save and share →
Create shortcut → Open as window** gives the same chromeless window
regardless, no manifest required.

## Flashing the firmware

```bash
cd firmware
# edit include/config.h: WiFi credentials, backend host/port, pins
pio run --target upload
```

**Calibrate the soil moisture sensor before trusting its readings.**
`SOIL_ADC_DRY`/`SOIL_ADC_WET` in `config.h` are placeholders — every
capacitive probe reads differently. Open the Serial monitor (115200
baud), dip the probe fully in water and note the printed raw value
(`soil raw=<n> -> <pct>%`), do the same in dry air, then set both
constants to what you actually measured and reflash.

### Capturing your AC's IR codes

The AC is driven by an IR transmitter (an Adafruit 38KHz IR Transceiver,
wired IRout → `IR_SEND_PIN` in `config.h`, default GPIO 14), replaying raw
codes captured from your actual remote — not a protocol library, so it
works with any AC brand. `firmware/include/ir_codes.h` ships with
placeholder codes that control nothing; capture your own before relying
on it:

1. Wire the module's IRin pin to GPIO 32 (also VIN/GND as normal) —
   needed for this one-time capture only.
2. Build and flash the capture utility, a **separate** PlatformIO
   environment from the main firmware:
   ```bash
   cd firmware
   pio run -e ir_capture -t upload
   pio device monitor
   ```
3. Point your real AC remote at the module and press the button for the
   state you want captured — typically **ON** at whatever temperature/mode
   you'll actually run it at, then **OFF**. Most AC remotes send a
   complete state (power + temperature + mode + fan speed) on every press
   rather than a simple toggle, so whatever was showing on the remote when
   you pressed ON is what gets replayed every time the dashboard turns the
   AC on — there's no separate temperature control.
4. Each press prints a ready-to-paste raw array to Serial. Copy the ON
   array into `AC_ON_RAW_CODE` and the OFF array into `AC_OFF_RAW_CODE` in
   `firmware/include/ir_codes.h`.
5. Reflash the **main** firmware (`pio run -t upload`, the default
   `esp32dev` environment) — the capture utility is never part of it.

## API

| Method & path | Caller | Purpose |
|---|---|---|
| `POST /api/telemetry` | ESP32 | report readings + actual relay state, receive the commanded state |
| `GET /api/status` | Dashboard | live mode, commanded/reported relay state, last-seen, latest reading, last 20 activity-log entries |
| `GET /api/profile` | Dashboard | the active grow profile (every decision-engine threshold plus the cosmetic name/tent size) |
| `POST /api/profile` | Dashboard | save an edited grow profile (admin-only) — persists to the database, survives a restart |
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

HTTP Basic Auth — no sessions, no new dependency, just `base64`/`secrets`
from the standard library. Users are declared in `.env`:

```
DASHBOARD_USERS=[{"username":"admin","password":"changeme-admin","role":"admin"},{"username":"viewer","password":"changeme-viewer","role":"viewer"}]
```

- **admin** — full control.
- **viewer** — can view everything, but every mutating call is rejected
  with `403`; the UI also disables the matching controls, but the `403`
  is what actually enforces it.

`POST /api/telemetry` is the one unauthenticated route (the firmware
sends no credentials). Everything else, including static files, requires
a valid login. Passwords are plaintext in `.env` — same trust model as
`HA_TOKEN` — and a missing/malformed `DASHBOARD_USERS` fails closed
(rejects everything, no default login shipped).

Basic Auth is stateless: no session, no timeout, no working "log out" —
staying logged in is just the browser caching credentials for as long as
it wants to.

## AC control

Fan, exhaust, pump, light, and now AC are all directly ESP32-driven — the
first four via physical relays, AC via an IR transmitter replaying raw
codes captured from the real remote (see "Capturing your AC's IR codes"
above). AC is still part of the decision engine's humidity/temperature
escalation exactly as before; only the actuation mechanism changed, from
a push to Home Assistant to a command in the same telemetry response the
ESP32 already polls for fan/pump/light.

IR is fire-and-forget like any IR remote — there's no confirmation
channel, so `reported_relay_state.ac` is "what the ESP32 last told the AC
to do," not a verified real state. The firmware only transmits on an
actual on→off or off→on transition (never every telemetry cycle), since
unlike a relay pin, re-sending the same IR code isn't a harmless no-op.

There's no separate notification channel — no speaker/media device is
connected, so crossing `ALERT_TEMP_C` forces fan and AC on directly
instead of announcing anything.

## Home Assistant

No longer used for AC (see above) — Home Assistant integration is now
just a reachability badge on the dashboard (`backend/ha_client.py`),
kept in case this project uses HA for something else later. Checked on
its own background schedule (`HA_HEALTH_CHECK_INTERVAL_SECONDS`, default
30s), never inline with a request, so a slow/hanging HA can't add latency
to a page load. An HA outage has no effect on anything else — it never
blocked `/api/telemetry` even when it did drive AC, and now has even
less to do with the control loop.
