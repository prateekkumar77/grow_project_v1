# Grow tent automation system

An ESP32 reads the tent's sensors and drives its relays (fan, exhaust,
pump, light) and an IR transmitter for the AC. A FastAPI backend decides
what everything should do, stores readings, sends Telegram alerts, and
serves a browser dashboard. Home Assistant is optional, used for a
reachability badge and a smart plug's live power readings.

Nothing assumes a particular plant. What changes between grows is a small
set of thresholds (the **grow profile**), edited from the dashboard.

- [`docs/automation-logic.md`](docs/automation-logic.md): the control rules.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): why things are built the way they are.

## Architecture

Every ~20s the ESP32 POSTs its readings and actual relay states to
`/api/telemetry`. The response says what every output should be, and the
ESP32 applies it. The ESP32 makes no environmental decisions itself. It
only runs safety logic that must work without a network: timing pump runs,
the pump run cap and cooldown, killing the pump on a failed POST, and an
offline emergency temperature floor.

## Features

| Feature | Summary |
|---|---|
| **Auto / manual mode** | Auto: fan and AC follow the grow-profile thresholds. Manual: they hold what the dashboard last set, reverting to auto after `AUTO_REVERT_MINUTES` of inactivity. |
| **Light** | Schedule (turn-on and turn-off time) or manual. Never affected by mode. |
| **Exhaust** | Schedule (run N min every M min). With the schedule off it follows the AC in auto mode and the manual switch in manual mode. |
| **Pump** | Manual (run for 1-30s) or schedule (every 1/2/3/4/6/8/12/24h for 1-30s). Never driven by mode or soil moisture. The ESP32 times each run. |
| **Schedule timezone** | One IANA timezone (profile tab) for the light, exhaust and pump schedules. Stored timestamps and charts stay UTC. |
| **AC over IR** | COOLIX protocol, 20°C, high fan. Sent only when the state changes, then once more 30s later as a backup. |
| **High-temp override** | At `ALERT_TEMP_C` the backend forces fan and AC on, in any mode. |
| **Telegram alerts** | *Main*: emergency temperature and an AC power check. *All*: also every activity-log entry. |
| **Live power row** | Current, voltage and power from a Home Assistant smart plug (optional). |
| **Min/max badges** | Today's min/max on each live card, kept in the browser only, reset at 00:00 UTC. |
| **Activity log** | Last 20 actions on the dashboard; the full history is in the DB and exportable to Excel. |
| **History tab** | Day (30/60-min buckets) and week (6-hour buckets) charts plus a light on/off pie. Exports of readings and the activity log. |

## Grow profile

Edited in the dashboard's **profile** tab and saved to the database, so it
survives restarts. The matching `.env` values are only the defaults used
before the first save.

| Field (`.env` default) | Governs |
|---|---|
| `HUMIDITY_HIGH_THRESHOLD` / `HUMIDITY_LOW_THRESHOLD` | AC on above high; AC off and fan on below low |
| `TEMP_FAN_THRESHOLD_C` / `TEMP_AC_THRESHOLD_C` | °C at which the fan, then the AC, engage |
| `TEMP_LOW_THRESHOLD_C` | °C below which the AC turns off and the fan pulls in room air |
| `ALERT_TEMP_C` | forces fan and AC on, and sends a Telegram alert |
| `TELEGRAM_ALERT_MODE` | `main` or `all` |
| `SCHEDULE_TIMEZONE` | timezone the light, exhaust and pump schedules run in |
| `GROW_PROFILE_NAME`, `TENT_SIZE_M2`, `GROW_START_DATE` | header label; a start date adds a "day N" counter |

The light, exhaust and pump schedule settings are set from their own
dashboard panels. They are kept in memory and reset to their `.env`
defaults (schedules off) when the backend restarts.

## Running the backend

```bash
cd backend
cp .env.example .env      # set DASHBOARD_USERS, thresholds, tokens
docker compose -f ../docker-compose.yml up --build
```

The dashboard is at `http://localhost:8000/`. Every setting is listed in
[`backend/.env.example`](backend/.env.example).

Without Docker, and to run the tests:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
pytest
```

**Install as an app:** Chrome offers an **Install** button over `https://`
or `http://localhost`. On a plain LAN address, use **⋮ → Save and share →
Create shortcut → Open as window**.

## Flashing the firmware

```bash
cd firmware
# edit include/config.h: WiFi, backend host/port, pins
pio run -e esp32dev -t upload     # esp32dev is also the default env
```

The backend and firmware share the telemetry format, so reflash whenever
`firmware/` changes.

**Calibrate the soil sensor.** `SOIL_ADC_DRY` / `SOIL_ADC_WET` in
`config.h` are placeholders. Open the Serial monitor (115200 baud), note
the printed `soil raw=<n>` in dry air and in water, set both values, and
reflash.

**AC settings** live in `config.h`: `AC_TARGET_TEMP_C` (20) and
`AC_IR_RESEND_DELAY_MS` (30000). Change them and reflash; you don't need
the remote.

### Identifying a different AC's IR protocol

The IR transmitter (Adafruit 38kHz IR Transceiver) is wired IRout →
`IR_SEND_PIN` (GPIO 14). `firmware/src/ir_ac.cpp` uses IRremoteESP8266's
`IRCoolixAC`. For another AC:

1. Wire the module's IRin to GPIO 32, then flash and open the capture tool:
   `pio run -e ir_capture -t upload && pio device monitor`.
2. Press any button on the AC's remote, pointed at the module.
3. If it prints a protocol name (e.g. `COOLIX`), use IRremoteESP8266's
   matching `ir_<Protocol>.h` class in `ir_ac.cpp`. If it prints
   `UNKNOWN`, use the raw array it prints with `IRsend::sendRaw()`.
4. Optional check: `pio run -e ir_test -t upload` sends on/off every 5s.
5. Reflash the main firmware: `pio run -e esp32dev -t upload`.

## Telegram alerts

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy
   the token. It looks like `123456789:AAH...`, including the number
   before the colon.
2. Send your new bot any message so it is allowed to message you.
3. Get your numeric chat ID from [@userinfobot](https://t.me/userinfobot).
4. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` and restart.
   If either is blank, alerts are skipped and a warning is logged.

Pick the mode in the profile tab ("telegram alerts"):

- **main** (default):
  - Temperature at or above `ALERT_TEMP_C`: one message when it first
    crosses, then at most every `ALERT_NOTIFY_COOLDOWN_MINUTES` while it
    stays above.
  - **AC power check**: `AC_POWER_CHECK_DELAY_SECONDS` (60) after an AC
    command, it warns if the plug reads ≥ `AC_OFF_MAX_POWER_W` (200) when
    the AC should be off, or < `AC_ON_MIN_POWER_W` (30) when it should be
    on. Needs `HA_POWER_ENTITY`.
- **all**: also one message per activity-log entry, with no cooldown.

## Home Assistant (optional)

The dashboard shows whether Home Assistant is reachable (`HA_URL`,
`HA_TOKEN`). For the live power row, set the smart plug's sensor entity
IDs, found under **Settings → Devices & Services → Entities**:

```bash
HA_CURRENT_ENTITY=sensor.16amp_smart_plug_current
HA_VOLTAGE_ENTITY=sensor.16amp_smart_plug_voltage
HA_POWER_ENTITY=sensor.16amp_smart_plug_power
```

Each entity is read separately, so a blank or unavailable one only shows
"--". Home Assistant being down never affects the control loop.

## Dashboard access

HTTP Basic Auth with users defined in `.env`:

```
DASHBOARD_USERS=[{"username":"admin","password":"changeme-admin","role":"admin"},{"username":"viewer","password":"changeme-viewer","role":"viewer"}]
```

- **admin** can do everything.
- **viewer** is read-only; every non-GET request gets `403`.
- `POST /api/telemetry` is the only route without a login, because the
  firmware sends no credentials.
- A missing or invalid `DASHBOARD_USERS` rejects every request.

The dashboard is a single HTML file with no build step. It loads Chart.js,
Lucide icons, Motion and Google Fonts from CDNs. Without internet the
controls still work, but icons are blank, charts show "unavailable",
fonts fall back and animations snap.

## API

| Method & path | Caller | Purpose |
|---|---|---|
| `POST /api/telemetry` | ESP32 | report readings and actual state; receive commanded state and any `pump_run` |
| `GET /api/status` | Dashboard | mode, relay states, latest reading, light/exhaust/pump status, HA status, last 20 activity entries |
| `GET /api/profile` / `POST /api/profile` | Dashboard | read / save the grow profile |
| `GET /api/timezones` | Dashboard | timezone names accepted by `schedule_timezone` |
| `GET /api/history` | Dashboard | past readings (`limit`, `since`, `until`) |
| `GET /api/charts/day` / `week` | Dashboard | bucketed temp/humidity/soil averages (UTC) |
| `POST /api/mode` | Dashboard | `auto` or `manual` |
| `POST /api/relay` | Dashboard | set fan or AC (manual mode only) |
| `POST /api/light/schedule` / `manual` | Dashboard | light schedule (`on_time`, `off_time`) or direct on/off (`409` while the schedule is on) |
| `POST /api/exhaust/schedule` / `manual` | Dashboard | exhaust duty cycle (`run_minutes`, `interval_minutes`, 1-60) or direct on/off (`409` while the schedule is on or it is following the AC) |
| `POST /api/pump/schedule` | Dashboard | pump schedule (`enabled`, `interval_hours`, `run_seconds`) |
| `POST /api/pump/run` | Dashboard | one manual run of `seconds` (`409` while the schedule is on) |
| `POST /api/export` | Dashboard | readings as `.xlsx` |
| `POST /api/activity/export` | Dashboard | full activity log as `.xlsx` |
| `GET /api/me` | Dashboard | current user and role |

## Repository layout

```
firmware/            ESP32 firmware (PlatformIO): sensors, relays, IR, safety, WiFi/HTTP
backend/             FastAPI app, decision engine, schedules, alerts, dashboard (static/)
docs/                control rules and design decisions
docker-compose.yml   backend + Home Assistant
```
