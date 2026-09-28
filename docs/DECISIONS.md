# Decisions

Judgment calls made where the build brief left an exact value or mechanism
unspecified. Simplest reasonable option in each case, recorded here instead
of silently decided.

## Decision engine

- **`decide_relay_state` signature**: `decide_relay_state(reading,
  previous_state)`, where `Reading` carries only the instantaneous
  `temp_c`/`humidity`/`soil_moisture` - no history, no baseline. The
  function stays pure/I/O-free and every threshold it compares against is
  a fixed grow-profile constant (see below).
- **Temperature switched from a rolling-baseline rise to absolute
  grow-profile thresholds**: the original design measured temperature as
  a rise above a rolling average (`baseline_temp_c`, computed by the
  caller from the last `BASELINE_WINDOW_MINUTES` of history) rather than
  an absolute value - "a tent that's steadily warm isn't a rise; a sudden
  climb is." That was replaced with plain absolute thresholds
  (`TEMP_FAN_THRESHOLD_C`, `TEMP_AC_THRESHOLD_C`), matching how humidity
  already worked (`HUMIDITY_HIGH_THRESHOLD`/`HUMIDITY_LOW_THRESHOLD` were
  never baseline-relative to begin with - `baseline_humidity` was
  computed but silently unused in `decide_relay_state`, dead from the
  start). This removes `main.py`'s `_compute_baseline()`/
  `BASELINE_WINDOW_MINUTES` entirely and makes every decision-engine
  threshold plain, env-configurable, and directly comparable across the
  whole grow profile - no more "why does temperature need history but
  humidity doesn't" asymmetry, and no DB read on every telemetry cycle
  just to decide relay state.
  - **Added `TEMP_LOW_THRESHOLD_C`**: the baseline-relative design never
    had a "too cold" case for temperature (only humidity did). Since the
    switch to absolute values makes this trivial to add symmetrically -
    at or below `TEMP_LOW_THRESHOLD_C`, turn AC off and fan on, mirroring
    the low-humidity rule's exact reasoning (pull in comparatively warmer
    room air instead of cooling a tent that's already too cold).
  - **Kept the two-tier fan/AC ladder rather than collapsing to a single
    high/low pair like humidity**: humidity has one high threshold (→
    AC) and one low threshold (→ AC off + fan). Temperature keeps its
    existing moderate/severe two-step ladder (fan alone, then AC) instead
    of matching humidity's shape exactly, since fan-before-AC for a
    moderate temperature rise was working, intentional behavior from the
    original brief - the baseline-to-absolute switch is only about how
    the threshold is computed, not about removing an escalation step
    nothing asked to remove.
  - **Placeholder values** (`TEMP_FAN_THRESHOLD_C=26.0`,
    `TEMP_AC_THRESHOLD_C=28.0`, `TEMP_LOW_THRESHOLD_C=18.0`): chosen to
    roughly match the old baseline-relative defaults assuming a ~24°C
    ambient (baseline+2/+3 → 26/28), but these are absolute now and need
    the same "tune against your actual tent" treatment as every other
    grow-profile value (`SOIL_ADC_DRY`/`WET`, `EMERGENCY_TEMP_C`, etc.).
- **Manual mode gating** happens in the caller, not inside
  `decide_relay_state`: when `mode == "manual"`, `main.py` never calls the
  function at all and just reuses the last dashboard-commanded state. This
  matches the brief's wording ("this function is not consulted") literally.
- **Soil moisture hysteresis**: added a `SOIL_MOISTURE_HYSTERESIS` band
  (default 5 points) so the pump doesn't rapidly toggle on/off right at the
  threshold. Below the threshold → on; above threshold + hysteresis → off;
  in between → hold. Not specified in the brief, but "avoid re-issuing
  true every cycle" implied some form of stable on/off state rather than a
  bare `<` comparison.
- **Humidity/temperature rule interaction**: both the humidity and
  temperature blocks can independently set `ac`/`fan`; they're applied in
  sequence (humidity first, then temperature) so either one turning AC on
  is sufficient, and neither block turns off what the other just turned on
  within the same call (e.g. a temperature-driven "hold" doesn't undo a
  humidity-driven AC-on in the same reading).
- **Exhaust is deliberately excluded from this function entirely**: an
  earlier revision added exhaust as a fourth output here, escalating
  alongside AC on the same humidity/temperature triggers. That was
  reverted - exhaust is now driven only by its own run/interval duty-cycle
  schedule (`exhaust_schedule.is_exhaust_on()`, see "Exhaust schedule"
  below), the same "own schedule, never a sensor" treatment light already
  gets. No humidity or temperature reading turns exhaust on or off.

## Pump safety (firmware)

- **Cooldown trigger**: `PUMP_COOLDOWN_SECONDS` only arms when the pump is
  forced off *by the cap itself* (30s of continuous running), not on every
  ordinary commanded-off. Rationale: the brief's stated concern is a
  backend that "keeps sending pump: true every cycle" trying to re-trigger
  right after a cap cutoff — a legitimate off/on cycle from the decision
  engine (e.g. soil moisture briefly crossing the hysteresis band) isn't
  the scenario being guarded against.
- **POST failure == "WiFi disconnected"**: the brief's safety section is
  titled "WiFi disconnected" but the actual trigger it specifies is "the
  instant a telemetry POST fails." Implemented literally — any failed POST
  (backend down, timeout, bad response) forces the pump off, not just a
  detected WiFi-layer disconnect. This is a strictly safer interpretation.
- **Emergency temperature floor is one-way**: while offline, hitting
  `EMERGENCY_TEMP_C` forces fan+exhaust on but never turns them back off
  once temperature drops — described in the brief as "a floor, not real
  control," so auto-recovery would be overstepping local logic.
- **Relay wiring**: assumed active-low relay modules (`RELAY_ACTIVE_LOW =
  true` in `config.h`), the common case for inexpensive boards. Flip the
  constant if the hardware is active-high.
- **Soil sensor calibration** (`SOIL_ADC_DRY` / `SOIL_ADC_WET`): placeholder
  values; every capacitive/resistive soil sensor needs per-unit calibration
  in air vs. water, so these are documented as needing a real calibration
  pass rather than guessed at. `sensors_read()` now also fills
  `Reading.soil_raw` and `main.cpp` prints it to Serial every telemetry
  cycle (`soil raw=<n> -> <pct>%`) - there was previously no way to see the
  raw ADC value at all, only the (potentially wrong) computed percentage,
  making calibration a guessing game.
- **Pump cooldown is reported, not just enforced.** The cap/cooldown above
  is silent by design at the protocol level - `RelayController::
  applyCommand()` just declines to turn the pump on and reports it as off,
  with no error, no flag, nothing distinguishing "refused due to cooldown"
  from "the backend didn't actually ask for it." From the dashboard's
  side, that's indistinguishable from the ordinary commanded/reported lag
  every other relay has for a few seconds each telemetry cycle - except
  it can persist for up to 90 seconds (30s run + 60s cooldown) instead of
  resolving next cycle, which reads as the UI being stuck. Rather than
  inferring "probably a cooldown" from timing on the backend (fragile -
  nothing distinguishes a slow network hiccup from an active cooldown),
  the firmware now reports the real number:
  `RelayController::pumpCooldownRemainingSeconds()`, sent as
  `pump_cooldown_remaining_s` in the telemetry payload, stored in
  `AppState.pump_cooldown_remaining_s`, and returned on `GET /api/status`.
  The dashboard shows "cooldown ~Xs" instead of generic "pending" for the
  pump specifically only while that value is nonzero - every other relay's
  "pending" behavior is unchanged.
- **New field defaults to 0.0** (`TelemetryIn.pump_cooldown_remaining_s`),
  so firmware from before this change still validates - not a breaking
  wire-format change, just an addition.
- **Not a live countdown.** The number is exactly what the firmware
  measured at its last telemetry post (~every `TELEMETRY_INTERVAL_MS`,
  20s), not interpolated client-side between polls - consistent with
  every other "reported" value on this dashboard already only refreshing
  on that same cadence. Adding client-side ticking for just this one field
  would be a level of polish nothing else here has.

## Backend

- **Runtime state storage**: mode, commanded/reported relay state, and
  `last_seen` live in an in-process `AppState` object guarded by a
  `threading.Lock`, not in the database. Simpler than adding a
  single-row settings table, and acceptable because a backend restart
  defaulting back to `auto` mode is the safe direction anyway. Only
  historical readings are persisted (SQLite, source of truth for the Excel
  export).
- **Extra `POST /api/export` endpoint**: the brief's endpoint table lists
  five routes but separately requires the Excel export be "available as a
  manual trigger." Added a sixth endpoint rather than overload one of the
  five, since a manual export doesn't fit the semantics of any of them.
- **History endpoint params**: `limit` (default 100, max 1000) plus
  optional `since`/`until` timestamps, ordered newest-first. Not specified
  exactly in the brief beyond "query params for range/limit."
- **Alert temperature is separate from the firmware's emergency floor**:
  `ALERT_TEMP_C` (backend, default 32°C) is intentionally lower than and
  independent of `EMERGENCY_TEMP_C` (firmware, default 35°C, offline-only
  physical cutoff) — one is an early-warning response while the network
  is up, the other is a last-resort floor for when it isn't.
- **No Home Assistant notification channel - forces fan+AC on directly
  instead**: the original design spoke a TTS alert via a Google Home
  speaker (`ha_client.speak()`/`send_alert()`, debounced via
  `HA_ALERT_DEBOUNCE_SECONDS`) and toggled a separate alert-side-effect
  switch (`HA_SWITCH_ENTITY`) when `ALERT_TEMP_C` was crossed. With no
  media/speaker device actually connected, that notification was pure
  dead weight - removed entirely (`speak()`, `send_alert()`,
  `toggle_switch()`, `toggle_grow_tent_switch()`, and their config all
  deleted from `ha_client.py`/`.env.example`). Crossing `ALERT_TEMP_C` now
  directly forces `fan` and `ac` on in `post_telemetry()`, overriding
  whatever auto/manual mode or the decision engine just decided for this
  cycle - a real cooling response instead of a notification nobody could
  hear. Applied inline (not backgrounded) so fan's forced state reaches
  the ESP32 in the *same* telemetry response rather than waiting for the
  next poll; AC still goes through the existing `_sync_ac_to_ha`
  background push like any other AC state change.
  - **Not one-way, unlike the firmware's `EMERGENCY_TEMP_C` floor**: this
    check re-runs every cycle against the live reading, so once
    temperature drops back below `ALERT_TEMP_C` it simply stops
    re-forcing fan/AC on - whatever auto/manual mode or the decision
    engine decides from that point on takes back over. It doesn't
    proactively turn them back off either, since that's not this
    feature's job - decide_relay_state()'s own temperature rules already
    never turn fan/AC off on a temperature drop (only humidity's low
    branch does), so nothing about this change alters that existing
    behavior.
- **AC as a Home-Assistant-only device (no ESP32 relay)**: for a real
  deployment where the AC is itself a Google Home device rather than
  something wired into the relay board, added `ha_client.set_ac()` /
  `HA_AC_ENTITY` / `HA_AC_DOMAIN` and had the backend push AC state to HA
  directly instead of via the ESP32. Specific choices:
  - **Configurable domain** (`HA_AC_DOMAIN`, default `switch`): an AC on a
    smart plug is a `switch.*` entity; a native smart AC/mini-split is
    usually `climate.*`. Rather than guess which one a given user has,
    the domain (and thus which HA service gets called) is an env var.
  - **Backgrounded, not synchronous**: `/api/telemetry` schedules the HA
    push via FastAPI `BackgroundTasks` instead of calling it inline. A
    slow Home Assistant call could otherwise add up to
    `HA_REQUEST_TIMEOUT_SECONDS` (default 5s) of latency to the
    `/api/telemetry` response — uncomfortably close to the firmware's own
    ~5s HTTP timeout, risking a telemetry POST timing out on the ESP32
    side purely because HA was slow, which would then trip the firmware's
    "POST failed → force pump off" safety path for an unrelated reason.
  - **`/api/relay` pushes AC changes immediately**: fan/pump manual
    commands rely on the ESP32 polling `commanded_relay_state` on its next
    cycle, but there's no ESP32 relay for AC to poll into. Without an
    immediate push, a manual AC toggle from the dashboard would silently
    do nothing until the next telemetry cycle (up to
    `TELEMETRY_INTERVAL_MS`, default 20s) coincidentally re-synced it.
  - **`/api/status` reports HA-confirmed state, not the ESP32's**: the
    ESP32 has no `ac` relay pin to report a real value for at all.
    `get_status()` substitutes `AppState.last_ha_ac_state` — the last
    state actually confirmed applied via a successful HA call — so the
    dashboard's pending indicator compares against reality instead of a
    field the ESP32 never meaningfully populates.
  - **Retry semantics**: `_sync_ac_to_ha` only marks a state "confirmed"
    on a successful HA call, so a failed push (HA temporarily down) gets
    retried on the next telemetry cycle rather than silently drifting out
    of sync.
  - **Trade-off, called out in `docs/automation-logic.md`**: the AC loses
    the firmware's offline emergency-temperature floor, since that floor
    can only drive a physical relay. This is inherent to the AC being an
    HA-only device, not something this change could route around -
    documented rather than silently accepted.
- **HA reachability is a background poll, not an inline check**: `GET
  /api/status` is polled every 5s by the dashboard, and `/api/telemetry`
  has the ESP32 waiting on its response with a firmware-side timeout of
  its own - neither can afford to block on a live call to Home Assistant.
  A scheduler job (`_check_ha_connection`, default every 30s) calls
  `ha_client.check_connection()` (`GET {HA_URL}/api/`, HA's own base
  health endpoint - works without any entity configured) and caches
  `reachable`/`checked_at` on `AppState`; both read endpoints just return
  the cached value. Trade-off: the indicator can lag reality by up to the
  poll interval - accepted since immediate accuracy would mean either
  blocking a request on HA's response time or making a second HA call to
  the wrong latency budget entirely; a 30s-stale "unreachable" badge is a
  fine cost for never stalling the dashboard or the ESP32.
- **`GET /api/`, not a call against `HA_AC_ENTITY`**: the health check
  hits Home Assistant's own root API endpoint rather than trying to read
  the configured AC entity's state. This means "Home Assistant reachable"
  is checked independently of whether AC-specific entities are even
  configured yet, and doesn't touch `HA_AC_ENTITY` should it be wrong -
  the two concerns (is HA up vs. is the AC entity ID correct) stay
  separate, matching how the request explicitly asked for a connectivity
  indicator, not an AC-entity health check.

## Light schedule

- **A fourth, independent ESP32 relay, not folded into the auto/manual
  relays**: the light gets its own `RELAY_LIGHT_PIN` (firmware) and its
  own `light` field on `RelayState`, entirely separate from
  fan/ac/pump. It is never passed to `decide_relay_state()` and is not
  gated by the environmental `mode` at all - the requirement was explicit
  that light "will not be affected by auto mode." A dedicated relay
  channel keeps the light fully independent of the other outputs, which
  are all decided together by the same function.
- **Schedule anchored to UTC midnight, not to when it was enabled**: the
  brief describes a duration ("18 on / 6 off"), not a specific start
  time, so `is_light_on(now_utc, on_hours)` is a pure function of the
  current wall-clock time - light on hours `[0, on_hours)` UTC, off for
  the rest of the day, every day. This was chosen over a rolling window
  from whenever the schedule was switched on because a fixed daily anchor
  is reproducible across backend restarts with no stored "next toggle"
  state, and gives the plant a consistent photoperiod start time day to
  day, which is closer to how a real light timer behaves. Trade-off: the
  cycle boundary is always at 00:00 UTC, not local midnight - acceptable
  since the rest of the backend already standardizes on UTC
  (`datetime.utcnow()` throughout) with no timezone configuration
  anywhere else.
- **Schedule disabled by default** (`LIGHT_SCHEDULE_ENABLED_DEFAULT=false`):
  mirrors the same reasoning as `mode` defaulting to `auto` and relays
  defaulting off - a fresh deploy should never start actuating hardware
  based on an unreviewed default (18h on_hours is a reasonable default
  *value*, but silently running with it before a grower has confirmed
  it's right for what's in the tent isn't). The grower opts in once via
  the dashboard's schedule toggle.
- **Master switch, not two independent settings**: `POST
  /api/light/schedule` combines `enabled` and `on_hours` into one call
  rather than having separate endpoints, and `on_hours` is always saved
  even while the schedule is off (so it's ready the instant it's turned
  on). `POST /api/light/manual` is rejected with `409` while the schedule
  is enabled, deliberately mirroring how `/api/relay` already rejects a
  manual fan/ac/pump command outside manual mode - one consistent
  pattern for "who owns this relay right now" across the whole app,
  rather than inventing a second one for light.
- **No auto-revert for manual light control**: unlike the environmental
  `mode`, switching the light's schedule off doesn't time out back to
  schedule-on after inactivity. The brief describes the schedule toggle
  itself as the intended control, not a temporary override, so an
  auto-revert would fight the grower's explicit choice rather than protect
  against forgetting a manual session.
- **Commanded light state recomputed fresh on every read**, not cached
  from the last telemetry cycle: `GET /api/status` and `POST
  /api/telemetry` both call the same `_light_status()` helper against the
  current time, rather than reading a value stored at the last ESP32 poll
  (up to `TELEMETRY_INTERVAL_MS` old). This means the dashboard reflects a
  schedule boundary the instant it's crossed - showing a "pending" state
  until the ESP32's next poll actually applies it - rather than lagging by
  up to one telemetry cycle.
- **`light_state` is a dedicated column, not just JSON**: light on/off was
  already captured inside `reported_relay_state`'s JSON blob on every
  row, but pulled it out to its own top-level `ReadingRow.light_state`
  column (and into `/api/history`'s response and the Excel export)
  so it's directly queryable/filterable/chartable without parsing JSON -
  the same reasoning `temp_c`/`humidity`/`soil_moisture` are columns
  rather than a bundled JSON blob. Populated from the ESP32's *reported*
  state (physical truth) rather than the commanded one, consistent with
  how "reported" is treated as ground truth everywhere else in the app.
  - **Migration note**: `SQLModel.metadata.create_all()` (run on
    startup) only creates tables that don't exist yet - it does not add
    columns to an existing table. Anyone with a `data/grow.db` from
    before this change will get a `500` on the next `/api/telemetry`
    POST (`no such column: readings.light_state`) until they run:
    `ALTER TABLE readings ADD COLUMN light_state BOOLEAN DEFAULT 0;`
    against it (via `sqlite3 data/grow.db` or Python's `sqlite3` module).
    Existing rows backfill to `0`/false, which is honest - the light's
    real historical state for readings taken before this feature existed
    isn't recoverable from data that was never captured. Chose an
    in-place `ALTER TABLE` over a fresh database because deleting
    `data/grow.db` would lose all historical readings, not just the new
    column - too large a cost for a one-column addition when the fix is
    one SQL statement.

## Exhaust schedule

- **Removed from `decide_relay_state()` entirely, given a schedule
  instead**: exhaust briefly went through two other designs first (a
  physical relay escalating alongside AC on humidity/temperature, then a
  physical relay replacing AC's Home-Assistant control outright) before
  landing here: exhaust is never touched by sensor readings, auto/manual
  `mode`, or `decide_relay_state()` at all. It's structurally identical to
  the light - its own relay, its own schedule/manual master switch - just
  with a different schedule *shape* (see next bullet).
- **Run/interval duty cycle, not an on_hours window**: light's schedule
  fits a once-a-day photoperiod; exhaust ventilation calls for a much
  higher-frequency repeating cycle (e.g. "1 minute every 5"), so
  `exhaust_schedule.is_exhaust_on()` takes `run_minutes` and
  `interval_minutes` (both 1-60 via dashboard dropdowns) instead of a
  single `on_hours`. Anchored to 00:00 UTC exactly like the light
  schedule, for the same reason: a pure function of wall-clock time needs
  no stored "next toggle" state and is correct immediately after a
  backend restart.
- **`run_minutes` cannot exceed `interval_minutes`**: unlike light (where
  `off_hours` is always `24 - on_hours`, computed rather than a second
  user input, so no invalid combination is possible), exhaust takes two
  independent user inputs. Running longer than the cycle itself is
  meaningless, so `ExhaustScheduleIn` rejects that combination with a
  `422` via a pydantic model validator rather than silently clamping it.
- **`off_minutes` is a computed response field, not a third input**: same
  reasoning as light's `off_hours` - `interval_minutes - run_minutes` is
  always derivable, so making it a separate settable field would just
  invite it to disagree with the other two.
- **Endpoints and behavior mirror `/api/light/schedule` and
  `/api/light/manual` exactly**: `POST /api/exhaust/schedule` combines
  `enabled` + `run_minutes` + `interval_minutes` into one call (values
  saved even while the schedule is off, so they're ready the instant it's
  turned on); `POST /api/exhaust/manual` is rejected with `409` while the
  schedule is enabled. Reusing the exact same pattern rather than
  inventing a different shape for exhaust keeps "who owns this relay
  right now" consistent across every schedule-driven relay in the app.

## Activity log

- **Two tiers: an in-memory ring buffer for the live feed, a DB table for
  the full history.** `ActivityLog` (capped at 20) still backs the
  dashboard's "recent activity" panel and still resets on restart, same as
  the rest of `AppState`'s volatility (mode, schedule config, etc.) - it
  stays a glanceable "what just happened" view, not an archive. The
  complete, unbounded history now lives separately in the `activity_log`
  DB table (`models.ActivityLogRow`), written via `ActivityLog.on_record` -
  a hook `main.py` sets once, fired for every entry the ring buffer
  records, even ones it later evicts. This keeps `activity_log.py` itself
  free of any DB dependency (same "pure module, DB access only in main.py"
  split as decision_engine.py/light_schedule.py/exhaust_schedule.py)
  while still giving the "export activity log" button something complete
  to export.
- **Log only actual transitions, never every telemetry cycle regardless of
  change.** `RelayActivityTracker` (in `activity_log.py`) keeps the last
  logged value per relay and only records an entry when it differs from
  the new one. Without this, the feed would fill with a repeated "fan on"
  every ~20s telemetry cycle for as long as the fan happened to already be
  on, drowning out anything that actually happened.
- **`RelayActivityTracker` stores plain booleans in a dict, not a
  `RelayState` object.** The first implementation stored the last
  `RelayState` instance directly as the comparison baseline, and had a
  real bug caught during live verification: `main.py`'s `POST /api/relay`
  handler does `setattr(app_state.commanded_relay_state, ...)`, mutating
  that object in place - since the tracker's baseline was the *same
  object* (not a copy), that mutation silently updated the baseline too,
  so the next diff compared the object to itself and never logged
  anything again after the first manual relay command. Switching the
  tracker to hold only independent `bool` values per relay (which can't be
  mutated out from under it) fixes the whole bug class, not just the one
  symptom - a `model_copy()` on write would have also fixed this specific
  case but left the same trap for the next caller that hands the tracker a
  live, mutable object. Covered by
  `test_survives_in_place_mutation_of_the_object_passed_to_update` in
  `test_activity_log.py`, which reproduces the exact scenario.
- **Piggybacks on `GET /api/status` rather than its own endpoint** - one
  more field (`activity`) on the same response the dashboard already polls
  every 5s, consistent with how light/exhaust status work. No separate
  poll loop, no separate loading state in the frontend.
- **Every entry carries an `actor`**: the dashboard username for a manual
  action (`request.state.user.username`, already available from the auth
  middleware on every non-telemetry route) or the literal string `"auto"`
  (`activity_log.AUTO_ACTOR`) for anything `post_telemetry` did on its own
  - the decision engine's fan/ac/pump escalation, or a light/exhaust
  schedule crossing its on/off boundary. `RelayActivityTracker.note()`/
  `.update()` and `ActivityLog.record()` both take `actor` as a required
  argument rather than defaulting it, so a new call site can't forget to
  decide who's responsible. `POST /api/telemetry` is the only route with
  no authenticated user to attribute to, and it's also the only place
  that logs `auto` - every other route always has a `request.state.user`
  by the time its handler runs.
- **Export mirrors the existing readings export exactly**: same pattern
  (`export_activity_log_to_excel(session)` in `excel_export.py`, a `POST`
  endpoint returning the generated file via `FileResponse`, a button next
  to the existing one on the history tab), same admin-only enforcement
  (inherited for free from the existing GET/POST role-check middleware -
  no new authorization code needed). Deliberately no scheduled background
  export for this one (unlike `EXPORT_INTERVAL_MINUTES` for readings) -
  the activity log is small and reviewed occasionally, not something that
  needs a fresh copy on disk every hour.

- **Aggregation happens server-side, in Python, not in SQL or client-side**:
  `backend/chart_data.py`'s `bucket_by_step()` fetches raw rows for the
  requested window and averages them in Python, rather than a SQL
  `GROUP BY` (which would need SQLite-version-specific date-bucketing
  functions and be harder to unit test) or shipping raw rows to the
  browser to average in JS (a day is ~4,300 rows, a week ~30,000, at the
  default telemetry interval - unnecessary payload and client CPU for
  what's fundamentally a small aggregation). A single pure function
  serves both the day view (24h window) and the week view (7-day window,
  6h buckets) by parameterizing the window/step size, rather than two
  separate implementations.
- **A missing bucket is `null`, never `0` or interpolated**: if the ESP32
  was offline for a stretch, that bucket has no readings to average.
  Rendering it as `0` would fabricate a reading that never happened (a
  dropped connection showing as "0°C" is actively misleading); the chart
  renders it as a genuine gap in the line instead - same "don't fabricate
  missing data" principle already used for `reported_relay_state` vs.
  ESP32-unreachable states elsewhere in the app.
- **Week view is 4 points/day (6h buckets), not one average per day**:
  the first pass averaged a full day into a single point, which flattens
  away the entire intraday temperature/humidity swing - a week of
  identical-looking daily averages tells you almost nothing about what
  actually happened. Switched to `bucket_by_step()` with a 6-hour step
  over the 7-day window (the same function the day view uses, just a
  different window/step), which keeps the day-to-day repeating pattern
  visible while still being far coarser than the day view's 30/60min
  buckets - 28 points for a week is still a compact response, not the
  ~1,000-row cap `/api/history` would need for the same range.
- **Dual y-axis (temperature left, humidity+soil right)**: the brief asks
  for one chart with all three series. Overlaying three series with
  incompatible units (°C vs. two independent 0-100% metrics) on a single
  axis would be actively misleading (e.g. a 5-point humidity move and a
  5-degree temperature move would look identical in size, despite
  meaning very different things). A dual axis is defensible here
  specifically because humidity and soil moisture already share a unit
  (%) and can honestly share the right axis - this isn't three arbitrary
  metrics forced onto two axes, it's one metric with its own unit (left)
  and two metrics that are already the same unit (right).
- **Dynamic tick-label decimal precision**: initial version always
  rounded axis labels to whole numbers, which looked broken (four
  gridlines all reading "24") whenever the auto-scaled range was narrow
  - a real scenario for a climate-controlled tent's weekly temperature
  average, not just a synthetic-data artifact. Fixed by using 1 decimal
  place whenever the axis span is under 5 units, since the live
  dashboard's own readouts already show temp/humidity/soil to 1 decimal,
  so this doesn't introduce a new precision convention.
- **Hand-rolled inline SVG, no charting library**: consistent with the
  rest of the dashboard's no-external-dependency stance (see "No external
  font/CDN dependency" below) - a charting library via CDN would be the
  easy path, but would make the dashboard depend on internet access for
  something that's otherwise fully self-hosted on the local network.
  Hover detail is provided via native SVG `<title>` tooltips on each data
  point rather than a custom-built tooltip system, which needs no extra
  JS event wiring and degrades gracefully (still a functional data point,
  just no popup) anywhere `<title>` isn't rendered.
- **Date/week pickers are native `<input type="date">`/`<input
  type="week">`**, not a custom-built calendar widget. `type="week"` in
  particular has inconsistent browser support (notably Firefox desktop
  falls back to a plain text input rather than a calendar UI) - accepted
  as a reasonable trade-off given a custom week-picker would be
  significant extra code for what's a secondary control, and the text
  fallback is still fully functional if typed in `YYYY-Www` format.
- **All chart date/week inputs are UTC, not the browser's local
  timezone**: consistent with the light schedule's own UTC-midnight
  anchor and the rest of the backend's `datetime.utcnow()`-only design -
  introducing local-time handling in just the charts would mean the same
  calendar date could mean two different underlying windows depending on
  where you looked. Labeled explicitly ("UTC day" / "UTC week") in the
  UI so this isn't a silent surprise.

## Database export

- **`POST /api/export` returns the generated `.xlsx` file directly**
  (with a `Content-Disposition: attachment` header), rather than writing
  it to disk and responding with just a row count. The endpoint already
  regenerates the file from scratch on every call (see
  `backend/excel_export.py`'s own docstring), so returning it inline lets
  the dashboard's "download .xlsx" button trigger a real browser download
  with one `fetch` + blob, with no separate "now go fetch the file"
  step or static route needed. The file is still also written to
  `EXPORT_PATH` on disk as before, so the scheduled background export
  (`_run_export`) and manual/API triggers behave identically either way.

## Dashboard authentication / roles

- **HTTP Basic Auth via a custom `@app.middleware("http")` function, not
  FastAPI's `HTTPBasic` security class.** Middleware runs at the ASGI level
  and wraps every request in one place, including the `StaticFiles` mount
  (`/static`) and the `index()` route serving `index.html` - a
  `Depends(...)`-based approach would have needed adding to all 13+
  existing route functions individually and still wouldn't cover the
  static mount without extra wiring. One function, one place to reason
  about, matches how `AUTO_REVERT`/offline-detection are also handled as
  cross-cutting concerns rather than per-route logic.
- **No new dependency** - `base64`/`secrets` (both standard library) are
  enough for Basic Auth decode + constant-time comparison. This matches
  the dashboard's own established stance (single HTML file, no build step,
  no CDN scripts) - the auth mechanism follows the same "reach for what's
  already there before adding a package" bias as the rest of the project,
  rather than pulling in `python-jose`/`passlib`/session middleware for a
  two-role, no-registration-flow system.
- **Users live in `.env` as a JSON array** (`DASHBOARD_USERS`), not a DB
  table - there's no user-management UI, no self-service signup, and the
  set of people who should have dashboard access changes about as often as
  `HA_TOKEN` does. A `.env` entry is one line to add/rotate/remove and
  needs no migration, consistent with every other piece of config in this
  project living in the environment rather than the database.
- **Plaintext passwords in `.env`.** Explicitly accepted, not an oversight
  - it's the same trust model already used for `HA_TOKEN`: whoever can read
  the backend's `.env` already has full control over the tent (HA access,
  DB access, the container itself), so hashing dashboard passwords would
  protect against a threat model (an attacker reading `.env` but not
  anything else in it) that doesn't hold here. `.env` is gitignored and
  never leaves the host, same as always.
- **Fail closed, not fail open.** An empty, unset, or malformed
  `DASHBOARD_USERS` means `auth.DASHBOARD_USERS` parses to `{}`, and
  `authenticate()` rejects every login against an empty user map - there is
  no shipped default admin/admin credential anywhere in code. A typo'd
  single entry is dropped with a logged warning rather than taking down
  every other configured user, but a totally broken/missing config takes
  down the whole dashboard rather than silently granting access.
- **`POST /api/telemetry` is the one unauthenticated route**, carved out by
  path in the middleware before any auth check runs. The ESP32 firmware
  has no notion of credentials and sends no `Authorization` header at all;
  requiring auth there would just break every telemetry post with no way
  for the firmware to satisfy it. Every other route, including the
  dashboard's own static assets, requires valid Basic Auth.
- **The GET/HEAD/OPTIONS vs. everything-else boundary is the entire role
  check** - a viewer can call any read-only endpoint (status, history,
  charts, profile, `/api/me`) but gets a flat `403` from the middleware on
  any other HTTP method, before the request even reaches the route
  handler. This means the boundary is enforced once, centrally, rather
  than needing every mutating endpoint to remember to check
  `request.state.user.role == "admin"` itself - a new `POST` route added
  later is protected automatically just by not being in `PUBLIC_PATHS`,
  with no route-level code required.
- **The dashboard UI's viewer lockdown (disabled buttons, a role badge, a
  `body.viewer-role` CSS rule making every control visually and
  `pointer-events: none`-inert) is a UX courtesy, not the actual
  boundary.** `GET /api/me` tells the frontend which role it's showing
  controls for, but the real enforcement is the 403 above - a viewer
  opening devtools and firing a raw `fetch()` at `/api/relay` still gets
  rejected server-side (verified live: a viewer's direct `POST
  /api/relay` returns `403` even with the button disabled and hidden
  behind `pointer-events: none`).
- **Timing-safe comparison, including for unknown usernames.**
  `auth.authenticate()` always runs `secrets.compare_digest()` against
  *some* password - a real one for a known username, an empty string for
  an unknown one - so a wrong password and a wrong username take
  indistinguishable time. Without this, response timing could leak which
  usernames in `DASHBOARD_USERS` actually exist.
- **No session/expiry mechanism, accepted as part of choosing Basic Auth.**
  There's no session token, cookie, or timer anywhere in `auth.py` or the
  middleware - every request is authenticated independently against
  `DASHBOARD_USERS`, every time. "Staying logged in" is entirely the
  browser's own credential cache for the origin, which this app has no
  visibility into or control over: no server-enforced re-login interval,
  and no logout endpoint could force it either (there's no session to
  invalidate). Rotating a password in `DASHBOARD_USERS` takes effect
  immediately on the next request either way, so it's not a security gap
  the way a stale session token would be - it's a UX tradeoff, made
  consciously to keep this dependency-free rather than add cookie/token
  session handling for a two-role dashboard with no self-service login
  flow.

## Frontend

- **No external font/CDN dependency**: used the system monospace/sans font
  stacks instead of pulling a webfont, so the dashboard renders correctly
  on a local/offline network (the tent controller shouldn't need internet
  access to show a temperature reading).
- **"Backend unreachable" vs. "stale sensor"**: implemented as two visually
  distinct signals — a fetch that throws (network/DNS/connection failure)
  shows a red "backend unreachable" banner and disables nothing else it
  doesn't have to; a fetch that succeeds but returns `offline: true` (stale
  `last_seen`) shows an amber "sensor offline" banner while still using the
  last known reading and keeping mode/relay controls live, since the
  backend itself is fine.
- **Manual mode visual shift**: a persistent top banner strip plus a
  background/border color wash across every panel, rather than just the
  toggle switch changing state, per the brief's requirement that it be
  "visually unmistakable."
- **Dashboard header is data, not a hardcoded string**: the header
  subtitle (what's growing / tent size) is served by a new `GET
  /api/profile` endpoint backed by `GROW_PROFILE_NAME` / `TENT_SIZE_M2` env
  vars, fetched once on page load. Added after the system was
  generalized away from a single hardcoded plant/tent description —
  keeping it server-side (rather than a client-only constant) means one
  `.env` edit updates the label without touching or redeploying the
  static file, and it's fetched separately from `/api/status` since it's
  static for the life of the process and doesn't need to be re-fetched
  every 5s poll.
- **Segmented-toggle CSS is scoped per-component by ID, not by a shared
  class rule**: adding the light schedule toggle (manual | schedule)
  alongside the existing mode toggle (auto | manual) surfaced a real bug -
  a single rule `.segmented[data-mode="manual"] { transform:
  translateX(100%); ... }` was written assuming "manual" is always the
  second button, true for the mode toggle but not for the light toggle,
  where manual is first. That collision visually broke the light toggle
  (thumb landed under the wrong label, with the wrong accent color) the
  first time two differently-ordered segmented controls existed on the
  same page. Fixed by scoping each toggle's "shifted" state to its own
  `#id[data-mode="..."]` selector instead of the shared class. Any future
  segmented control needs its own scoped rule for the same reason - the
  shared `.segmented`/`.segmented-thumb` base styling is fine to reuse,
  the position/color override per state is not.
- **Exhaust got its own panel, structured like the light panel, not a
  tile in `.relays`**: exhaust briefly sat as a plain on/off tile
  alongside fan/pump (`.relays` grew to 3 columns for it), back when it
  was a sensor-driven physical relay like fan/pump. Once it became
  schedule-driven instead, that no longer fit - a bare on/off tile has
  nowhere to put a schedule/manual toggle or the run/interval dropdowns.
  `.relays` reverted to 2 columns (fan, pump), and exhaust got its own
  panel reusing the exact same `.control-btn`/`.control-row`/
  `.schedule-controls` markup the light panel already uses, generalized
  from `.light-schedule-controls` to `.schedule-controls` so both panels
  share one class instead of duplicating near-identical CSS.
  AC keeps its own separate "home assistant" panel throughout all of
  this, unchanged: it's still not the same kind of thing as a local
  relay, and still depends entirely on Home Assistant being reachable, so
  it keeps its own section with the live reachability badge rather than
  blending into either the relay grid or the schedule panels.
- **AC's "on" accent is teal, not the green/amber used elsewhere**: every
  other "on" state (fan, exhaust, pump, light) uses green or amber, so AC
  needed its own color to read as visually distinct at a glance - reusing
  teal (already in the palette for the humidity readout) both avoids
  introducing a new color and loosely signals "this is the
  cooler/external one," consistent with a Home Assistant-mediated
  control rather than a direct relay.
- **HA connection badge reuses the same status-badge component as the
  backend connection indicator**: generalized `#conn-badge`'s CSS from an
  ID-scoped rule to a `.status-badge` class so the new HA badge could
  reuse it exactly (`ok`/`stale`/`unreachable`, plus a new `unknown`
  state for "not checked yet") rather than duplicating pill/dot/pulse
  styling a second time for what is visually the same kind of indicator.

## Docker / infra

- **Home Assistant service**: official `ghcr.io/home-assistant/home-assistant:stable`
  image, `network_mode: host` for local network device discovery (Google
  Home devices, smart plugs), config persisted to a gitignored
  `./ha_config` volume.
