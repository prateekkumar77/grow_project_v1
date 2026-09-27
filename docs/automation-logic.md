# Automation logic

Plain-language description of how the grow tent decides what to do. The
ESP32 never makes environmental decisions itself — it only reports sensor
readings and its actual relay states, and applies whatever the backend
tells it to do.

Everything from here down through "Manual mode" covers **fan, exhaust,
AC, and pump** — the four outputs `backend/decision_engine.py` actually
decides, and only while the system is in **auto** mode. Fan, exhaust, and
pump are physical ESP32 relays; AC has no relay at all and is driven
through Home Assistant instead (see "AC: no physical relay" below). The
**light** is covered separately, further below, because it isn't part of
any of that: it has its own schedule and is never touched by
`decide_relay_state()` or by auto/manual mode at all.

## What gets measured

- **Temperature** and **humidity** from the DHT22.
- **Soil moisture** from the analog probe, converted to a 0–100% scale.
- A **rolling baseline** temperature and humidity, averaged over the last
  `BASELINE_WINDOW_MINUTES` (default 30) of readings. "Rising" or "falling"
  always means relative to this baseline, not an absolute number — a tent
  that's steadily warm isn't a rise; a sudden climb is.

## Humidity rules

- **Humidity climbing at or above `HUMIDITY_HIGH_THRESHOLD`** (default 65%):
  turn **exhaust and AC on together**. Exhaust vents the tent's humid air
  out locally; AC actively conditions the air via Home Assistant. Both
  escalate on the same trigger rather than one standing in for the other.
- **Humidity dropping at or below `HUMIDITY_LOW_THRESHOLD`** (default 40%,
  expected to be rare with no active ventilation): turn **exhaust and AC
  off** and the **fan on**, so the tent pulls in room air instead — the
  room is normally more humid than the tent, so this raises humidity back
  up without needing a humidifier.

## Temperature rules

Measured as a rise above the rolling baseline:

- **A moderate rise** (`TEMP_RISE_FAN_THRESHOLD_C` to `TEMP_RISE_EXHAUST_THRESHOLD_C`,
  default 2–3°C): turn the **fan on alone**. Air movement alone is often
  enough to knock a couple of degrees off without pulling in outside air.
- **A larger or sustained rise** (at or above `TEMP_RISE_EXHAUST_THRESHOLD_C`,
  default 3°C): **escalate to exhaust and AC together**, which handles
  both temperature and humidity at once rather than relying on air
  movement alone.

## Soil moisture / watering

- **Soil moisture at or below `SOIL_MOISTURE_LOW_THRESHOLD`** (default 35%):
  command the **pump on**.
- **Soil moisture at or above that threshold plus `SOIL_MOISTURE_HYSTERESIS`**
  (default 5 points, i.e. 40%): command the pump off.
- In between those two numbers, the pump holds whatever it was already
  doing — this hysteresis band stops the pump from rapidly clicking on/off
  right at the boundary.
- The backend does not need to worry about spamming "pump on" every cycle —
  the ESP32 itself only ever *starts* the pump timer on an off→on
  transition, and independently enforces a **hard 30 second max run** with
  a **60 second cooldown** afterwards, regardless of what the backend asks
  for. That's a firmware safety limit, not a decision the backend makes.

## AC: no physical relay, controlled via Home Assistant

Unlike fan, exhaust, and pump, the AC in this deployment is a Google Home
device (a smart plug or native smart AC/mini-split), not something wired
to an ESP32 relay. The decision engine's `ac` output escalates in
lockstep with `exhaust` (same triggers, same section above) - what
differs is how it gets applied:

- **Fan / exhaust / pump**: the ESP32 polls its commanded state on every
  telemetry cycle and drives the physical relay itself.
- **AC**: the backend pushes the state directly to Home Assistant
  (`ha_client.set_ac()`, entity configured via `HA_AC_ENTITY`/
  `HA_AC_DOMAIN`) whenever it changes — once from `/api/telemetry` in
  auto mode, or immediately from `/api/relay` in manual mode, since
  there's no ESP32 relay for a manual click to reach otherwise. The call
  runs in the background so a slow or unreachable Home Assistant never
  delays the ESP32's telemetry response.
- `/api/status` reports the AC's last **Home Assistant-confirmed** state
  as its "reported" value, since the ESP32 has no relay pin for it to
  report at all.

This does mean the AC loses the one piece of true offline resilience the
other relays have: if the network or Home Assistant is down, the AC just
stays wherever it last was, with no local device watching temperature for
it - exhaust still gets that offline backstop since it has a real relay
(see `EMERGENCY_TEMP_C` below), AC does not.

Because AC control depends entirely on Home Assistant being reachable,
the dashboard gives it its own panel, separate from the ESP32 relay tiles,
with a live "is Home Assistant actually reachable right now" indicator.
The backend checks this independently of any AC command - a background
job (`scheduler._check_ha_connection`, every `HA_HEALTH_CHECK_INTERVAL_SECONDS`,
default 30s) calls `ha_client.check_connection()` (`GET {HA_URL}/api/`,
Home Assistant's own health-check endpoint) and caches the result. `GET
/api/status` just reports that cached value instantly - the check never
runs on a request path, so a slow or hanging Home Assistant can't add
latency to a page load the way an inline check would.

## Manual mode

When the dashboard puts the system in **manual**, the decision engine is
not consulted at all. Relay commands come only from the last thing a human
clicked on the dashboard (`POST /api/relay`). The only thing that can still
override a manual command is the ESP32's own local safety logic (pump
cap/cooldown, and the offline emergency-temperature floor) — never another
piece of backend logic.

Manual mode automatically reverts to auto after `AUTO_REVERT_MINUTES`
(default 30) of no dashboard activity, so a manual session can't be
forgotten and left uncontrolled indefinitely.

## Light: its own schedule, independent of mode

The grow light has its own ESP32 relay, just like fan and pump — but it is
**never** decided by `decide_relay_state()` and is completely unaffected
by whether the system is in auto or manual mode. It has exactly two states
of its own, controlled from the dashboard:

- **Schedule on**: the light follows a daily duty cycle, computed fresh
  every telemetry cycle from the current time — there's no stored "next
  toggle" timer to lose track of, so it's correct immediately even right
  after a backend restart. You set how many hours per day it should be on
  (`on_hours`, 1–24, picked from the dashboard's dropdown); off-hours is
  always `24 - on_hours`, computed automatically. The cycle is anchored to
  **00:00 UTC** every day: light on hours 1 (say, `on_hours = 18`) means on
  from 00:00 to 18:00 UTC, then off from 18:00 to 24:00, repeating daily.
- **Schedule off**: the light is under direct manual control from the
  dashboard (`POST /api/light/manual`) — it just holds whatever it was
  last set to, with no automatic behavior at all.

The dashboard's schedule toggle is the master switch between these two
states; attempting a manual command while the schedule is on is rejected
(`409`), the same way `/api/relay` rejects a manual fan/exhaust/ac/pump
command outside manual mode.

There's no offline-specific logic for the light beyond what every other
physical relay already gets: it holds its last-commanded state if the
network drops, same as fan. Unlike fan, though, its schedule keeps
computing correctly in the background even while offline — it just can't
reach the ESP32 to apply a change until connectivity returns.

## What the firmware does entirely on its own

This is the *only* logic that lives on the ESP32, and it runs regardless of
mode or what the backend says, because it has to survive a dead network
connection:

- **Pump cap**: force the pump off after `MAX_PUMP_RUN_SECONDS` (default
  30s) of continuous running, and refuse to turn it back on for
  `PUMP_COOLDOWN_SECONDS` (default 60s) afterwards.
- **On any failed telemetry POST**: force the pump off immediately and
  unconditionally.
- **While offline, if temperature reaches `EMERGENCY_TEMP_C`** (default
  35.0°C — sanity-check this against your actual tent before trusting it):
  force the fan and exhaust on locally, as a one-way floor. This is not
  real climate control, just a last-resort heat cutoff while nothing else
  is watching. **AC gets no such floor** - it has no physical relay for
  this firmware-only logic to drive, so while offline it just holds
  whatever it was last set to.
- Everything else holds its last-commanded state while offline.
