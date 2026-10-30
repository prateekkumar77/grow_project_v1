# Automation logic

How the system decides what each output does. The backend makes every
decision. The ESP32 reports readings and actual states, applies the
commanded state it gets back, and runs only the safety logic listed at
the end.

| Output | Driven by |
|---|---|
| Fan, AC | decision engine (auto mode) or dashboard (manual mode) |
| Light | its own schedule or manual switch, whatever the mode |
| Exhaust | its own schedule; with the schedule off, it follows the AC (auto mode) or the manual switch (manual mode) |
| Pump | manual timed runs or its own interval schedule, whatever the mode |

All thresholds below are grow-profile values, edited live in the
dashboard's profile tab. Defaults are shown in brackets.

## Sensors

- **Temperature and humidity** come from the DHT22.
- **Soil moisture** comes from the analog probe, scaled to 0-100%. It is
  shown and recorded only; it controls nothing.

## Auto mode: fan and AC

`decide_relay_state()` in `backend/decision_engine.py` compares each
reading directly with the thresholds, with no averaging or history:

- **Humidity at or above `HUMIDITY_HIGH_THRESHOLD`** (65%): AC on.
- **Humidity at or below `HUMIDITY_LOW_THRESHOLD`** (40%): AC off, fan on,
  to pull in the room's more humid air.
- **Temperature at or above `TEMP_AC_THRESHOLD_C`** (28°C): AC on. This is
  checked before the fan threshold, so the higher threshold wins.
- **Temperature at or above `TEMP_FAN_THRESHOLD_C`** (26°C): fan on.
- **Temperature at or below `TEMP_LOW_THRESHOLD_C`** (18°C): AC off, fan
  on, to pull in warmer room air.

**High-temperature override:** at or above `ALERT_TEMP_C` (32°C), fan and
AC are forced on in any mode, and a Telegram alert is sent. Normal control
resumes once the temperature drops back below it.

## Manual mode

Fan and AC hold whatever was last set with `POST /api/relay`, and the
decision engine is skipped. After `AUTO_REVERT_MINUTES` (30) with no
dashboard activity, the system switches back to auto. `POST /api/relay`
outside manual mode returns `409`.

## Schedule timezone

The light, exhaust and pump schedules use the profile's
`schedule_timezone` (an IANA name such as `Asia/Kolkata`; default `UTC`).
Each schedule is worked out from the current time on every telemetry
cycle, with no stored timer, so it is correct right after a restart.

## Light

- **Schedule on:** the light is on from `on_time` to `off_time` (HH:MM).
  If `off_time` is earlier than `on_time`, the window runs past midnight
  (18:00 → 06:00 is on overnight). Equal times are rejected (`422`).
- **Schedule off:** it holds what `POST /api/light/manual` last set. That
  call returns `409` while the schedule is on.

## Exhaust

- **Schedule on:** it runs `run_minutes` out of every `interval_minutes`
  (each 1-60), counted from local midnight. `run_minutes` greater than
  `interval_minutes` is rejected (`422`).
- **Schedule off, auto mode:** it follows the final commanded AC state,
  including the high-temperature override.
- **Schedule off, manual mode:** it holds what `POST /api/exhaust/manual`
  last set. That call returns `409` in the other two cases.

## Pump

- **Manual:** `POST /api/pump/run` with 1-30 seconds requests one run. It
  returns `409` while the schedule is on.
- **Schedule:** one run of `run_seconds` (1-30) every `interval_hours` (1,
  2, 3, 4, 6, 8, 12 or 24), in slots counted from local midnight, so 12h
  means 00:00 and 12:00. Turning the schedule on, changing the interval,
  or changing the timezone counts the current slot as already done, so
  the pump never runs straight away.

The ESP32 checks in only every ~20s, so it times each run itself:

1. While a run is pending, every telemetry reply includes
   `pump_run: {id, seconds}`.
2. The firmware runs the pump for `seconds` the first time it sees a new
   `id`, then reports it back as `pump_last_run_id`.
3. Once that id comes back, the backend stops sending the request, so
   repeated replies never cause a second run.
4. Ids start from the current Unix time, so a backend restart can't reuse
   one.
5. A request not picked up within `PUMP_RUN_REQUEST_TTL_SECONDS` (300) is
   dropped and logged, so an offline ESP32 never waters late.

`relay_state.pump` in the reply is always false and ignored. The pump's
reported state still shows when it's running.

## AC (infrared)

The AC has no relay. The ESP32 sends it COOLIX commands
(`firmware/src/ir_ac.cpp`): on at `AC_TARGET_TEMP_C` (20°C) with high fan,
or off.

- A command is sent only when the commanded state changes, because
  resending an IR state isn't harmless the way a relay pin is.
- The same command is sent once more `AC_IR_RESEND_DELAY_MS` (30s) later
  in case the AC missed it.
- IR gives no feedback, so the AC's "reported" state means "what the
  ESP32 last sent", not a confirmed state.
- **AC power check:** `AC_POWER_CHECK_DELAY_SECONDS` (60) after a change,
  the backend reads the Home Assistant plug's power. If it reads ≥
  `AC_OFF_MAX_POWER_W` (200) when the AC should be off, or <
  `AC_ON_MIN_POWER_W` (30) when it should be on, a "check AC" Telegram
  alert is sent. The check is skipped when there is no power reading.

## Home Assistant

Optional and never part of the control loop. Background jobs check
whether it is reachable (every `HA_HEALTH_CHECK_INTERVAL_SECONDS`) and
read the plug's current, voltage and power (every
`HA_POWER_POLL_INTERVAL_SECONDS`). `/api/status` returns the cached
values, so Home Assistant never slows a request.

## Firmware-only safety

These rules run on the ESP32 regardless of mode or backend:

- **Pump timing:** each requested run is timed locally, clamped to
  `MAX_PUMP_RUN_SECONDS`, and finishes even if WiFi drops partway.
- **Pump cap:** after `MAX_PUMP_RUN_SECONDS` (30s) of continuous running
  the pump is forced off and refused for `PUMP_COOLDOWN_SECONDS` (60s). A
  normal timed run ending doesn't start a cooldown. The remaining
  cooldown is reported as `pump_cooldown_remaining_s` and shown on the
  pump panel.
- **Failed telemetry POST:** the pump is forced off immediately.
- **Offline above `EMERGENCY_TEMP_C`** (35°C): fan and exhaust are forced
  on and stay on until the backend is reachable again.
- Everything else, including the AC, holds its last commanded state while
  offline.
