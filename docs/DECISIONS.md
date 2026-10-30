# Decisions

Why things are built the way they are. This states the current reasoning
only; the behaviour itself is in [automation-logic.md](automation-logic.md).

## Control split

- **The backend decides; the ESP32 only applies.** Rules are easier to
  change, test and see from the dashboard. The only logic on the ESP32 is
  safety that must work without a network.
- **`decide_relay_state()` is pure.** Every threshold comes from its
  `profile` argument, with no history or rolling baseline, so the same
  reading always gives the same decision and it can be unit-tested
  directly.
- **Light, exhaust and pump sit outside the decision engine.** They are
  timed jobs, not reactions to readings. The only crossover is the exhaust
  following the AC in auto mode (`exhaust_follows_ac()`), so the tent
  ventilates while the AC runs. Because it is set after the
  `ALERT_TEMP_C` override, it also follows a forced-on AC.
- **Soil moisture controls nothing.** Watering is deliberately manual or
  on a fixed schedule; the probe reading is for information only.

## Schedules

- **No stored timers.** Every schedule is a pure function of the current
  time (`is_light_on()`, `is_exhaust_on()`, `pump_schedule.slot_start()`),
  so it is correct right after a restart.
- **One `schedule_timezone` for all three schedules.** They describe the
  same grower's day. It lives on the grow profile, so it reuses that
  table's save, validation and migration code. `GET /api/timezones`
  serves the list the validator accepts, so the dropdown can't offer an
  invalid zone. `tzdata` is pinned because slim images may not ship zone
  data.
- **Only the schedules use local time.** Stored timestamps, charts, the
  grow-day counter and the min/max reset stay UTC, so stored data never
  depends on a setting.
- **Light on/off times, not hours per day.** Growers think in "lights on at
  18:00". Equal times are rejected because they could mean always on or
  always off.
- **Pump intervals all divide 24,** so slots line up with local midnight
  every day. Turning the schedule on, or changing the interval or
  timezone, counts the current slot as done, so a settings change never
  waters immediately.
- **Schedules start disabled and aren't persisted.** A fresh deploy or a
  restart never actuates anything on an unreviewed default.

## Pump

- **The firmware times each run.** Runs last seconds, but the ESP32 checks
  in only every ~20s.
- **Each run is a one-time request with an acknowledgement.** The
  `pump_run` id repeats in each reply until the ESP32 echoes it back in
  `pump_last_run_id`, so a lost reply can't drop a run and a repeated one
  can't double it. Ids start from the Unix time, so a backend restart
  can't reuse one.
- **Requests expire after `PUMP_RUN_REQUEST_TTL_SECONDS`.** An ESP32 that
  comes back after a long outage shouldn't water at a random time.
- **The 30s cap and 60s cooldown stay as a backstop.** A normal run end
  doesn't arm the cooldown; only a run that hit the cap does.
- **Any failed telemetry POST stops the pump,** not just a detected WiFi
  drop.

## AC

- **IR from the ESP32, not Home Assistant.** It goes through the same
  telemetry loop as the relays, with no second system that can be down.
- **Structured COOLIX state (`IRCoolixAC`), not replayed raw codes.**
  Temperature, mode and fan are firmware constants, so retargeting needs a
  reflash, not the remote.
- **Send only on a change, plus one backup resend 30s later.** Resending
  an IR state isn't harmless the way a relay pin is, and IR can't confirm
  receipt. The resend is non-blocking (`IrAcController::tick()`) and
  cancelled by any newer command.
- **The AC power check uses the smart plug as the missing feedback.** The
  60s delay covers the 30s resend. Only one check is queued per change
  (a newer change replaces it), and none on the first telemetry after a
  restart, because there is no known previous state then.
- **The offline emergency floor doesn't include the AC.** Fan and exhaust
  are enough for a last-resort cutoff, and the floor only ever turns
  things on.

## Alerts

- **The `ALERT_TEMP_C` override is separate from its Telegram message.**
  The override re-applies every cycle. The message is rate-limited by
  `should_send_temp_alert()`: once on crossing, then at most every
  `ALERT_NOTIFY_COOLDOWN_MINUTES`. `ALERT_TEMP_C` (32°C) sits below the
  firmware's offline-only `EMERGENCY_TEMP_C` (35°C).
- **The decision logic is pure functions in `alerting.py`.** The HTTP
  sending is in `telegram_client.py`, so the timing rules are testable
  without mocks.
- **"All alerts" hooks into `ActivityLog.on_record`.** It works from
  scheduler jobs that have no request context, and sends on a daemon
  thread so Telegram never delays a request.
- **"All" mode needs no cooldown.** Relay entries are only logged on real
  transitions. Entries that already have their own main alert (in
  `MAIN_ALERT_ACTIVITY_PREFIXES`) are skipped, so nothing is sent twice.
- **Missing Telegram config logs a warning and skips the message.** The
  cooling response never depends on Telegram.

## Grow profile

- **The profile is persisted, unlike other runtime state.** It is a
  singleton `GrowProfileRow` (id=1). `.env` is only the default before the
  first save, and no row is written until someone saves.
- **New columns are added at startup with `_ensure_grow_profile_column()`.**
  `create_all()` never alters existing tables, and `PRAGMA table_info`
  makes the step a no-op once done. Dropped fields (the soil thresholds)
  keep their columns with defaults, so old databases still accept
  inserts.
- **Validation rejects nonsensical orderings with `422`**: humidity low <
  high, temp low < fan ≤ AC, and alert ≥ AC.
- **One activity entry per save** lists every changed field as old → new,
  so a save can't flood the 20-entry feed.
- **Firmware-only settings stay out of the profile.**
  `EMERGENCY_TEMP_C`, the soil calibration and the pump cap can't be
  pushed to the ESP32, so editing them in the dashboard would silently do
  nothing.

## Backend

- **Runtime state lives in an in-process `AppState` behind a lock.** A
  restart safely returns to auto mode with schedules off.
- **Home Assistant is polled in the background and cached.** A slow HA
  never delays `/api/status`. Each power entity is fetched separately, so
  one bad entity blanks only its own value.
- **The activity log has two tiers:** a 20-entry in-memory feed and an
  unbounded `activity_log` table, written through a hook so
  `activity_log.py` has no DB dependency. Every entry records an actor:
  the username, or `auto`.
- **Charts are aggregated server-side** (`chart_data.bucket_by_step()`).
  A day is ~4,300 rows. Empty buckets render as gaps, never zero.

## Auth

- **HTTP Basic Auth in one middleware** covers every route, including the
  static files, using only the standard library.
- **Users are listed in `DASHBOARD_USERS` in `.env`,** the same trust
  model as the other secrets. A missing or invalid value rejects every
  request; there is no default login.
- **Viewers get `403` on any method other than GET, HEAD or OPTIONS,**
  enforced server-side. The disabled controls in the UI are only a
  courtesy.
- **`/api/telemetry` is unauthenticated,** because the firmware sends no
  credentials.

## Frontend

- **One HTML file, no build step.** It is edited and reloaded directly.
- **CDN libraries (Chart.js, Lucide, Motion, Google Fonts)** are loaded
  defensively, so a blocked CDN degrades only its own feature, never
  polling or controls.
- **Min/max badges live only in the browser** (`localStorage`), reset at
  UTC midnight, and are per device by design.
- **Two banners:** "backend unreachable" and "sensor offline" are
  different problems with different fixes.
- **The UI is sized for phones:** a sticky header, 44px touch targets, and
  `prefers-reduced-motion` respected.

## Infra

- **Home Assistant runs from the official image with host networking,**
  for device discovery. Its config is a gitignored volume.
