# Decisions

Judgment calls made where the build brief left a value or mechanism
unspecified. States the current rationale only — not a changelog of what
was tried before landing here.

## Decision engine

- `decide_relay_state(reading, previous_state, profile)` is pure and
  stateless: every threshold comes from the `profile` argument, an
  absolute grow-profile value (no rolling baseline or history lookup).
  Same reading, same profile, same decision, always. The profile itself
  is `main.py`'s problem (see "Grow profile editor" below) - the function
  never reads `.env` or the database directly.
- Temperature is a two-step ladder (fan alone, then AC) mirroring
  humidity's high/low split; `TEMP_LOW_THRESHOLD_C` mirrors humidity's
  low-branch reasoning (pull in warmer room air instead of cooling a tent
  that's already too cold).
- Soil moisture uses a hysteresis band (`SOIL_MOISTURE_LOW_THRESHOLD` +
  `SOIL_MOISTURE_HYSTERESIS`) so the pump doesn't chatter at the boundary.
- Manual mode bypasses this function entirely — `main.py` just reuses the
  last dashboard-commanded state.
- Exhaust is never part of this function — it's driven only by its own
  schedule (see below), never by a sensor reading.

## Pump safety (firmware)

- `PUMP_COOLDOWN_SECONDS` only arms after a cap-triggered cutoff (30s
  continuous run), not on an ordinary commanded-off — it guards against
  the backend re-sending "pump on" right after a cutoff, not a legitimate
  off/on from the decision engine's own hysteresis.
- Any failed telemetry POST force-kills the pump immediately, not just a
  detected WiFi-layer disconnect.
- The offline emergency-temperature floor (`EMERGENCY_TEMP_C`) is one-way
  — forces fan+exhaust on, never back off. A last-resort cutoff, not real
  control.
- `RELAY_ACTIVE_LOW` assumes active-low relay modules (the common case);
  flip it for active-high hardware.
- `SOIL_ADC_DRY`/`SOIL_ADC_WET` are placeholders — every capacitive soil
  sensor needs per-unit calibration in air vs. water. `main.cpp` prints
  the raw ADC value to Serial every cycle so that calibration doesn't
  require guessing.
- The firmware reports `pump_cooldown_remaining_s` in telemetry so the
  dashboard can show "cooldown ~Xs" instead of a stuck-looking generic
  "pending" while a commanded pump-on is being silently refused.
- In manual mode, the backend cancels a standing pump-on command the
  moment it learns a cap cutoff happened, so the pump never auto-restarts
  once the cooldown clears — a fresh `POST /api/relay` is required. Auto
  mode is unaffected: its decision engine re-evaluates the pump from
  live soil moisture every cycle regardless.

## Backend

- Runtime state (mode, commanded/reported relay state, `last_seen`) lives
  in an in-process `AppState` guarded by a lock, not the database — a
  restart safely defaults back to `auto` mode.
- `ALERT_TEMP_C` (backend, default 32°C) forces fan+AC on directly as an
  early-warning response, independent of and lower than the firmware's
  offline-only `EMERGENCY_TEMP_C` (default 35°C). No notification channel
  exists — no speaker/media device is connected, so this is a direct
  cooling response, not an alert.
- AC has no physical relay — it's a Google Home device pushed via Home
  Assistant (`ha_client.set_ac()`, `HA_AC_ENTITY`/`HA_AC_DOMAIN`),
  backgrounded so a slow HA call never delays `/api/telemetry`'s response
  to the ESP32. `/api/status` reports the last HA-confirmed state, since
  the ESP32 has no relay pin for AC to report a real value. HA
  reachability is polled on its own background schedule
  (`HA_HEALTH_CHECK_INTERVAL_SECONDS`), never inline with a request.
- `GET /api/history` takes `limit` (default 100, max 1000) plus optional
  `since`/`until`, newest-first.

## Grow profile editor

- Every decision-engine threshold, plus `ALERT_TEMP_C` and the cosmetic
  `GROW_PROFILE_NAME`/`TENT_SIZE_M2` fields, are one editable "grow
  profile" (`GrowProfileIn`/`GrowProfileOut` in `models.py`), live-editable
  from the dashboard's **profile** tab (admin-only, like every other
  mutating route) - not a code or `.env` change.
- Firmware-only safety settings (`EMERGENCY_TEMP_C`, `SOIL_ADC_DRY`/`WET`,
  `MAX_PUMP_RUN_SECONDS`, `PUMP_COOLDOWN_SECONDS`) are deliberately **not**
  part of this profile - there is no runtime channel for the backend to
  push config to the ESP32 at all (telemetry responses only ever carry
  relay commands), so editing them would silently do nothing. Light/
  exhaust schedule values aren't part of it either - they're already
  editable via their own dedicated panels, not a decision-engine threshold.
- Persists to the database (`GrowProfileRow`, a singleton row fixed at
  `id=1`) rather than living in-memory like every other runtime setting -
  this one was deliberately asked to survive a restart, unlike mode or the
  light/exhaust schedules, which reset to their `.env` default on purpose.
  `.env` is read only as the very first boot's default, before any save
  has ever happened; once `GrowProfileRow` exists, `.env` is never
  consulted again for this value.
- On startup, a missing `GrowProfileRow` leaves `AppState.grow_profile` at
  its `.env`-derived default *without writing a row* - a DB row should
  only ever be created by an explicit `POST /api/profile`, mirroring the
  "no surprise actuation on a fresh deploy" rationale already used for the
  light/exhaust schedules.
- `GrowProfileIn`'s `@model_validator` enforces the same threshold
  orderings the UI implies (humidity low < high, temp low < fan &le; ac,
  alert &ge; temp-ac) so a nonsensical profile is rejected with `422`
  rather than silently producing an always-on or always-off relay.
- One consolidated `"grow profile updated: field old->new, ..."`
  activity-log entry per save, not one per changed field like light/
  exhaust schedule changes - up to 10 fields can change in a single save,
  which would otherwise flood the 20-entry live feed. Listing every
  changed field's old->new value in that one entry keeps it inspectable
  without diffing two `GET /api/profile` responses by hand. Nothing is
  logged for a save that doesn't actually change any value.

## Light schedule

- Own ESP32 relay, own field on `RelayState` — never touched by
  `decide_relay_state()` or auto/manual mode.
- The schedule is a pure function of wall-clock time anchored to 00:00
  UTC (on for `on_hours`, off for the rest of the day) — no stored "next
  toggle" state, so it's correct immediately after a restart.
- The schedule toggle is the master switch: a manual command is rejected
  with `409` while it's on. Starts disabled by default so a fresh deploy
  never actuates on an unreviewed default photoperiod.
- No auto-revert for manual light control — the schedule toggle itself is
  the intended control, not a temporary override.

## Exhaust schedule

- Same "own relay, own schedule, master-switch" pattern as light, but a
  repeating run/interval duty cycle instead of an `on_hours` window.
  `run_minutes` can't exceed `interval_minutes` (`422`).
- Never touched by `decide_relay_state()` or any sensor reading — its own
  schedule or a manual command only.

## Activity log

- Two tiers: a 20-entry in-memory ring buffer for the live dashboard feed
  (resets on restart, like the rest of `AppState`), and an unbounded
  `activity_log` DB table for the complete history, written via a hook so
  `activity_log.py` itself stays free of any DB dependency.
- Only actual on/off transitions are logged, never every telemetry cycle
  regardless of whether anything changed.
- Every entry carries an actor: the dashboard username for a manual
  action, or `"auto"` for anything the decision engine or a schedule did
  on its own.
- The export button mirrors the existing readings export exactly (own
  endpoint, same admin-only enforcement) — no scheduled background export,
  since the log is reviewed occasionally rather than needing an hourly
  fresh copy on disk.

## History charts

- Aggregation happens server-side in Python (`chart_data.bucket_by_step()`),
  not SQL or client-side — a day is ~4,300 rows, a week ~30,000, too much
  to ship raw and average in JS.
- A bucket with no readings renders as a genuine gap, never `0` or
  interpolated.
- The week view uses 6-hour buckets (4 points/day), not one average per
  day, so the intraday pattern stays visible.
- Dual y-axis: temperature (°C) on the left, humidity + soil moisture
  (both already %) sharing the right.
- Hand-rolled inline SVG, no charting library — consistent with the
  dashboard's no-external-dependency stance, so it keeps working with no
  internet access. Date/week pickers are native `<input>` types. All
  chart windows are UTC, matching the rest of the backend.

## Dashboard authentication / roles

- HTTP Basic Auth via a custom `@app.middleware("http")` function, not
  FastAPI's `HTTPBasic` dependency — covers every route, including the
  static file mount, in one place instead of per-route wiring.
- No new dependency — `base64`/`secrets` (standard library) are enough.
- Users live in `.env` as a JSON array (`DASHBOARD_USERS`), not a DB
  table, same as every other credential (`HA_TOKEN`) already there.
  Plaintext passwords, same trust model.
- Fails closed: a missing/malformed `DASHBOARD_USERS` rejects every
  request rather than falling back to a default login.
- `POST /api/telemetry` is the only unauthenticated route, since the
  firmware sends no `Authorization` header. Everything else, including
  static assets, requires valid credentials.
- The role check is GET/HEAD/OPTIONS vs. everything else, enforced once
  in the middleware — a viewer gets `403` on any mutating call before it
  reaches the route handler.
- The dashboard's viewer-lockdown UI (disabled buttons, `pointer-events:
  none`) is a courtesy, not the boundary — the `403` above is enforced
  server-side regardless of what the browser shows.
- No session/expiry: Basic Auth is stateless, so "staying logged in" is
  purely the browser's own credential cache for the origin.

## Frontend

- No external font/CDN dependency — the dashboard works with no internet
  access.
- "Backend unreachable" (a failed fetch) and "sensor offline" (`offline:
  true` from a reachable backend) are two visually distinct banners —
  different problems, different signals.
- Manual mode gets a persistent top banner plus a background wash across
  every panel, not just a toggle change, so it's visually unmistakable.
- AC gets its own panel (not a relay tile), with a live HA-reachability
  badge, since it depends on Home Assistant rather than a local relay —
  its "on" accent is teal to stay visually distinct from every other
  relay's green/amber.
- **Sticky header, not a fixed one.** `position: sticky` keeps mode/
  connection status visible while scrolling a long panel list on a phone,
  without the extra complexity a `fixed` header brings (content needing a
  matching top-padding offset, z-index fights). The one wrinkle: the
  manual-mode strip is a separate `position: fixed` full-width banner
  above everything, so the sticky header's `top` offset has to shift to
  `50px` under `body.manual` or the two would overlap - handled with the
  same class the rest of manual mode's visual treatment already toggles.
- **Icon "chips" are pure CSS, no wrapper markup.** An SVG root is
  box-generating like an `<img>`, so `.section-title svg` and `.readout
  .icon` get their padded/rounded background directly - no `<span>`
  wrapper needed around every one of the ~13 icons in the page to get a
  colored badge look.
- **Chart data points get a tap tooltip, not just hover `<title>`.**
  `<title>` never fires on a touchscreen, so a chart's exact values were
  effectively undiscoverable on mobile. Each point already carries a
  `<title>` for desktop mouse users; a second, larger (r=11 vs. the
  visible r=2.5 dot) invisible hit circle sits on top, wired to a small
  fixed-position tooltip shown on `pointerdown` and dismissed by tapping
  anywhere else - large enough to reliably hit with a finger without
  visually enlarging the dot itself.
- **A `--tap: 44px` token, applied as `min-height` across every button,
  select, and toggle** - the standard minimum comfortable touch target
  (Apple/Google guidance), rather than sizing controls for a mouse cursor
  and hoping they're still tappable on a phone.
- **`prefers-reduced-motion` is respected globally** - none of the
  pulse/slide/fade animations carry information, so anyone with that OS
  setting gets them collapsed to instant, no separate opt-out needed per
  component.

## Docker / infra

- Home Assistant runs via the official image with `network_mode: host`
  (for local device discovery), config persisted to a gitignored volume.
