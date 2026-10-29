# Automation logic

Plain-language description of how the grow tent decides what to do. The
ESP32 never makes environmental decisions itself — it only reports sensor
readings and its actual relay states, and applies whatever the backend
tells it to do.

Sections up through "Manual mode" cover **fan and AC** — the two
outputs `decide_relay_state()` decides, only in **auto** mode. Fan is a
physical ESP32 relay; AC is an IR transmitter instead (see below) — both
are ESP32-driven either way. **Light, exhaust and pump** run on their own
schedules (or manual control) and are covered separately, further down —
none of them is ever decided by `decide_relay_state()` or any sensor
reading. All three schedules run in the grow profile's
`schedule_timezone` (IANA name, default `UTC`).

## What gets measured

- **Temperature** and **humidity** from the DHT22.
- **Soil moisture** from the analog probe, converted to a 0–100% scale.

Every rule below compares the current reading directly against a fixed
"grow profile" threshold - there's no baseline or history lookup. The
same reading always produces the same decision, and retuning for a
different plant/stage/tent is a live edit from the dashboard's **profile**
tab - no restart needed, and it's saved to the database so it survives
one. `backend/.env.example` only sets the first-run default, before
anyone has ever saved a profile.

## Humidity rules

- **Humidity climbing at or above `HUMIDITY_HIGH_THRESHOLD`** (default 65%):
  turn the **AC** on. The AC pulls in drier, cooler conditioned air, which
  brings both temperature and humidity down together.
- **Humidity dropping at or below `HUMIDITY_LOW_THRESHOLD`** (default 40%,
  expected to be rare with no active ventilation): turn the **AC off** and
  the **fan on**, so the tent pulls in room air instead — the room is
  normally more humid than the tent, so this raises humidity back up
  without needing a humidifier.

## Temperature rules

All absolute tent temperature, not a rise relative to anything:

- **At or above `TEMP_FAN_THRESHOLD_C`** (default 26.0°C): turn the
  **fan on alone**. Air movement alone is often enough to knock a couple
  of degrees off without pulling in outside air.
- **At or above `TEMP_AC_THRESHOLD_C`** (default 28.0°C, checked before
  the fan threshold so the higher bar wins): **escalate to AC**, which
  handles both temperature and humidity at once rather than relying on
  air movement alone.
- **At or below `TEMP_LOW_THRESHOLD_C`** (default 18.0°C, unusually
  cold): turn the **AC off** and the **fan on**, mirroring the
  low-humidity rule — pulling in comparatively warmer room air rather
  than cooling a tent that's already too cold.

## Soil moisture

The soil moisture reading is recorded and shown on the dashboard, but it
no longer drives anything — the pump has its own manual/schedule control
(see "Pump" below).

## AC: an IR transmitter, not a relay

The AC has no physical ESP32 relay, but unlike before it's no longer a
Home Assistant device either — it's driven by an IR transmitter wired
directly to the ESP32 (`firmware/src/ir_ac.*`). This deployment's AC uses
the COOLIX protocol, which IRremoteESP8266 supports natively via a
structured state class (`IRCoolixAC`), so `ir_ac.cpp` sets
mode/fan/temperature/power and sends on every transition rather than
replaying a code captured from the real remote (see `README.md`'s
"Capturing your AC's IR codes") — the target temperature
(`AC_TARGET_TEMP_C` in `config.h`) is a firmware constant, changeable by
reflashing alone, never requiring the physical remote. An AC whose
protocol isn't recognized has no structured class to use and falls back
to `sendRaw()` with the raw array the capture tool still prints
alongside. The decision engine's `ac` output is unchanged; only how it
gets applied changed:

- **Fan / pump / AC**: all three now flow the same way — the ESP32 polls
  its commanded state (including `ac`) on every telemetry cycle and
  applies it itself. Fan/pump hold a relay pin; AC fires an IR code, but
  only on an actual on→off or off→on transition, never every cycle
  (unlike a relay pin, re-sending the same IR code isn't a harmless
  no-op — many AC remotes send a full state packet on every press).
  Each transition is sent once more 30s later (`AC_IR_RESEND_DELAY_MS`)
  as a backup in case the AC missed the first signal.
- `/api/status` reports the ESP32's own `reported_relay_state.ac` as
  "reported," the same as fan/pump. This is still not a *confirmed* real
  state — IR is fire-and-forget, with no feedback channel telling the
  ESP32 whether the AC actually responded — but it's at least "what we
  last told it to do" rather than a value from a separate system (Home
  Assistant) that could itself be unreachable.

Because AC is now ESP32-driven like fan/pump, a network/backend outage no
longer strands it mid-state waiting on a separate service the way a Home
Assistant outage used to — the usual "holds its last commanded state
while offline" behavior applies, same as any relay. One asymmetry
remains, unchanged by this: `EMERGENCY_TEMP_C`'s offline failsafe (below)
still only drives fan + exhaust locally, not AC, since extending it was
out of scope for this change.

## Home Assistant: reachability badge only

Home Assistant is no longer part of AC control at all — it's kept wired
in purely for its own "is Home Assistant actually reachable right now"
dashboard badge, in case this project uses HA for something else later.
A background job (`scheduler._check_ha_connection`, every
`HA_HEALTH_CHECK_INTERVAL_SECONDS`, default 30s) calls
`ha_client.check_connection()` (`GET {HA_URL}/api/`, Home Assistant's own
health-check endpoint) and caches the result. `GET /api/status` just
reports that cached value instantly - the check never runs on a request
path, so a slow or hanging Home Assistant can't add latency to a page
load the way an inline check would.

## Manual mode

When the dashboard puts the system in **manual**, the decision engine is
not consulted at all. Relay commands come only from the last thing a human
clicked on the dashboard (`POST /api/relay`). The other thing that can
still override a manual command is the ESP32's own local safety logic
(the offline emergency-temperature floor).

Manual mode automatically reverts to auto after `AUTO_REVERT_MINUTES`
(default 30) of no dashboard activity, so a manual session can't be
forgotten and left uncontrolled indefinitely.

## Light: its own schedule, independent of mode

The grow light has its own ESP32 relay, just like the fan — but it is
**never** decided by `decide_relay_state()` and is completely unaffected
by whether the system is in auto or manual mode. It has exactly two states
of its own, controlled from the dashboard:

- **Schedule on**: the light follows a daily duty cycle, computed fresh
  every telemetry cycle from the current time — there's no stored "next
  toggle" timer to lose track of, so it's correct immediately even right
  after a backend restart. You set a **turn-on time** and a **turn-off
  time** (`on_time`/`off_time`, HH:MM from the dashboard's time pickers)
  in the schedule timezone: on 06:00 / off 00:00 means on from 06:00 to
  midnight. An off time earlier than the on time wraps past midnight
  (on 18:00 / off 06:00 is on overnight); equal times are rejected
  (`422`).
- **Schedule off**: the light is under direct manual control from the
  dashboard (`POST /api/light/manual`) — it just holds whatever it was
  last set to, with no automatic behavior at all.

The dashboard's schedule toggle is the master switch between these two
states; attempting a manual command while the schedule is on is rejected
(`409`), the same way `/api/relay` rejects a manual fan/ac command
outside manual mode.

There's no offline-specific logic for the light beyond what every other
physical relay already gets: it holds its last-commanded state if the
network drops, same as fan. Unlike fan, though, its schedule keeps
computing correctly in the background even while offline — it just can't
reach the ESP32 to apply a change until connectivity returns.

## Exhaust: its own duty-cycle schedule, or following the AC

The exhaust fan has its own ESP32 relay too, with a schedule/manual master
switch like the light — but the schedule *shape* is different, and with
the schedule off it follows the AC in auto mode. Rather than one on/off window per day, it's
a repeating **duty cycle**: on for `run_minutes`, then off for the rest of
every `interval_minutes` window, anchored to midnight in the schedule
timezone, cycling continuously (`exhaust_schedule.
is_exhaust_on()`). Both `run_minutes` and `interval_minutes` are 1-60,
picked from dashboard dropdowns, and the API rejects `run_minutes` greater
than `interval_minutes` (`422`) since running longer than the cycle itself
is meaningless.

- **Schedule on**: `is_exhaust_on()` decides, recomputed fresh every
  telemetry cycle - same restart-safety property as the light schedule,
  since it's a pure function of wall-clock time with no stored "next
  toggle" state.
- **Schedule off, auto mode**: the exhaust mirrors the final commanded
  AC state — on whenever AC is on, off whenever AC is off — including the
  `ALERT_TEMP_C` override, since it's set after that override is applied
  (`exhaust_schedule.exhaust_follows_ac()`).
- **Schedule off, manual mode**: the exhaust is under direct manual
  control from the dashboard (`POST /api/exhaust/manual`) — it just holds
  whatever it was last set to.

A manual command is rejected with `409` while the schedule is enabled or
while the exhaust is following the AC. `decide_relay_state()` itself still
never sets the exhaust; it only reaches it indirectly, through the AC
decision it makes in auto mode.

## Pump: manual timed runs or an interval schedule

The pump is never part of auto mode or `decide_relay_state()`, and soil
moisture never turns it on. Two states, switched from the dashboard:

- **Manual**: a **run** button plus a seconds dropdown (1-30) —
  `POST /api/pump/run` requests one run of that length.
- **Schedule**: "every N hours for N seconds" — interval 1, 2, 3, 4, 6, 8,
  12 or 24 hours, run 1-30 seconds. Slots are anchored to midnight in the
  schedule timezone (`pump_schedule.slot_start()`), so every 12h runs at
  00:00 and 12:00; one run is requested per slot. Enabling the schedule
  or changing the interval marks the current slot as done, so the first
  run is at the next boundary rather than immediately.
  `POST /api/pump/run` is rejected with `409` while it's on.

The ESP32 only polls every ~20s, too coarse to time a 3s run from the
backend, so each run is a one-time request the firmware times itself:

- While a run is pending, every telemetry reply carries
  `pump_run: {id, seconds}`. The firmware starts the pump for `seconds`
  the first time it sees a new `id`, and reports it back as
  `pump_last_run_id`; once that matches, the backend stops sending it.
  A repeated reply therefore never re-runs, and ids start from the
  current Unix time so a backend restart can't reuse one.
- A request not picked up within `PUMP_RUN_REQUEST_TTL_SECONDS` (default
  300) is dropped and logged, so an offline ESP32 doesn't water hours late.
- The run finishes on the ESP32's own timer even if WiFi drops mid-run.
  `relay_state.pump` in the reply is always false and ignored.

## What the firmware does entirely on its own

This is the *only* logic that lives on the ESP32, and it runs regardless of
mode or what the backend says, because it has to survive a dead network
connection:

- **Pump runs**: time each requested run itself (above), clamped to
  `MAX_PUMP_RUN_SECONDS`.
- **Pump cap**: force the pump off after `MAX_PUMP_RUN_SECONDS` (default
  30s) of continuous running, and refuse to turn it back on for
  `PUMP_COOLDOWN_SECONDS` (default 60s) afterwards — a backstop; a normal
  timed run ending doesn't start a cooldown. The firmware still reports
  `pump_cooldown_remaining_s`, shown on the dashboard's pump panel.
- **On any failed telemetry POST**: force the pump off immediately and
  unconditionally.
- **While offline, if temperature reaches `EMERGENCY_TEMP_C`** (default
  35.0°C — sanity-check this against your actual tent before trusting it):
  force the fan and exhaust on locally, as a one-way floor. This is not
  real climate control, just a last-resort heat cutoff while nothing else
  is watching. **AC gets no such floor** - not a hardware limitation
  anymore (it has its own IR actuation path now, see above), just not
  wired into this specific failsafe; while offline it holds whatever it
  was last set to, same as fan/light do for everything this floor
  doesn't cover.
- Everything else holds its last-commanded state while offline.
