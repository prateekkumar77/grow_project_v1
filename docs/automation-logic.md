# Automation logic

Plain-language description of how the grow tent decides what to do. The
ESP32 never makes environmental decisions itself — it only reports sensor
readings and its actual relay states, and applies whatever the backend
tells it to do.

Sections up through "Manual mode" cover **fan, AC, and pump** — the three
outputs `decide_relay_state()` decides, only in **auto** mode. Fan and
pump are physical ESP32 relays; AC is an IR transmitter instead (see
below) — all three are ESP32-driven either way. **Light and exhaust** run
on their own schedules and are covered separately, further down — neither
is ever touched by `decide_relay_state()`, auto/manual mode, or any
sensor reading.

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
- While that cooldown is active, the firmware silently refuses a commanded
  pump-on — it doesn't turn on, and it doesn't tell the backend *why* it
  didn't, just that it's still off. The dashboard would otherwise show a
  generic, seemingly-stuck "pending" for as long as the cooldown lasts, so
  the firmware also reports how many seconds are left in it
  (`pump_cooldown_remaining_s` in the telemetry payload), and the dashboard
  shows "cooldown ~Xs" instead while it's nonzero.

## AC: an IR transmitter, not a relay

The AC has no physical ESP32 relay, but unlike before it's no longer a
Home Assistant device either — it's driven by an IR transmitter wired
directly to the ESP32 (`firmware/src/ir_ac.*`), replaying the exact
ON/OFF codes captured from the real AC remote (see `README.md`'s
"Capturing your AC's IR codes"). This deployment's AC uses the COOLIX
protocol, which IRremoteESP8266 recognizes natively, so the captured
codes are sent via its `sendCOOLIX()` rather than raw timing replay; an
AC whose protocol isn't recognized would fall back to `sendRaw()` with
the raw array the capture tool still prints alongside. The decision
engine's `ac` output is unchanged; only how it gets applied changed:

- **Fan / pump / AC**: all three now flow the same way — the ESP32 polls
  its commanded state (including `ac`) on every telemetry cycle and
  applies it itself. Fan/pump hold a relay pin; AC fires an IR code, but
  only on an actual on→off or off→on transition, never every cycle
  (unlike a relay pin, re-sending the same IR code isn't a harmless
  no-op — many AC remotes send a full state packet on every press).
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
(pump cap/cooldown, and the offline emergency-temperature floor).

**Pump is the one exception.** Manual mode has no concept of "re-arming" a
relay — whatever was last clicked just gets resent every cycle, forever,
until clicked again. That's fine for fan/ac/light/exhaust, but not for the
pump: the firmware's 30s-run/60s-cooldown safety cap (below) can force it
off without telling the backend why, so the backend would otherwise keep
resending the same stale "on" command and the pump would settle into a
perpetual 30-seconds-on/60-seconds-off loop with no way to stop it short
of noticing and clicking "off." So in manual mode only, the moment the
backend learns (via `pump_cooldown_remaining_s`) that a cap cutoff just
happened, it cancels the standing "on" command — turning the pump back on
after that always takes a fresh `POST /api/relay`, never an automatic
resumption. **Auto mode is unaffected**: its decision engine already
re-evaluates the pump from live soil moisture every cycle, so there's no
stale command to begin with.

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
(`409`), the same way `/api/relay` rejects a manual fan/ac/pump command
outside manual mode.

There's no offline-specific logic for the light beyond what every other
physical relay already gets: it holds its last-commanded state if the
network drops, same as fan. Unlike fan, though, its schedule keeps
computing correctly in the background even while offline — it just can't
reach the ESP32 to apply a change until connectivity returns.

## Exhaust: its own duty-cycle schedule, never sensor-driven

The exhaust fan has its own ESP32 relay too, and follows the exact same
"own schedule, independent of mode" pattern as the light — but the
schedule *shape* is different. Rather than one on/off window per day, it's
a repeating **duty cycle**: on for `run_minutes`, then off for the rest of
every `interval_minutes` window, cycling continuously (`exhaust_schedule.
is_exhaust_on()`). Both `run_minutes` and `interval_minutes` are 1-60,
picked from dashboard dropdowns, and the API rejects `run_minutes` greater
than `interval_minutes` (`422`) since running longer than the cycle itself
is meaningless.

- **Schedule on**: `is_exhaust_on()` decides, recomputed fresh every
  telemetry cycle - same restart-safety property as the light schedule,
  since it's a pure function of wall-clock time with no stored "next
  toggle" state.
- **Schedule off**: the exhaust is under direct manual control from the
  dashboard (`POST /api/exhaust/manual`) — it just holds whatever it was
  last set to.

Same master-switch pattern as light: a manual command while the schedule
is enabled is rejected with `409`. Crucially, **exhaust is never touched
by `decide_relay_state()`** — no humidity or temperature reading ever
turns it on or off; only its own schedule or a manual dashboard command
does.

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
  is watching. **AC gets no such floor** - not a hardware limitation
  anymore (it has its own IR actuation path now, see above), just not
  wired into this specific failsafe; while offline it holds whatever it
  was last set to, same as fan/pump/light do for everything this floor
  doesn't cover.
- Everything else holds its last-commanded state while offline.
