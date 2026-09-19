# Decisions

Judgment calls made where the build brief left an exact value or mechanism
unspecified. Simplest reasonable option in each case, recorded here instead
of silently decided.

## Decision engine

- **`decide_relay_state` signature**: the brief gives it as
  `decide_relay_state(reading, previous_state)` with no baseline parameter,
  but "a temperature rise of 2–3°C above the recent baseline" requires
  history the function can't fetch itself (it must stay pure/I/O-free). The
  `Reading` dataclass passed in therefore carries `baseline_temp_c` and
  `baseline_humidity` fields alongside the instantaneous sensor values —
  computed by the caller (`main.py`, as a rolling average over
  `BASELINE_WINDOW_MINUTES`, default 30) and handed in. The function itself
  still does no I/O.
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
  `EMERGENCY_TEMP_C` forces fan+AC on but never turns them back off once
  temperature drops — described in the brief as "a floor, not real
  control," so auto-recovery would be overstepping local logic.
- **Relay wiring**: assumed active-low relay modules (`RELAY_ACTIVE_LOW =
  true` in `config.h`), the common case for inexpensive boards. Flip the
  constant if the hardware is active-high.
- **Soil sensor calibration** (`SOIL_ADC_DRY` / `SOIL_ADC_WET`): placeholder
  values; every capacitive/resistive soil sensor needs per-unit calibration
  in air vs. water, so these are documented as needing a real calibration
  pass rather than guessed at.

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
  `ALERT_TEMP_C` (backend, default 32°C, drives the Home Assistant
  notification) is intentionally lower than and independent of
  `EMERGENCY_TEMP_C` (firmware, default 35°C, offline-only physical
  cutoff) — one is an early warning while the network is up, the other is
  a last-resort floor for when it isn't.
- **HA alert debounce state**: kept as an in-memory dict keyed by alert
  type, not persisted. A backend restart resetting the debounce window is
  an acceptable cost for a home-automation notification feature.
- **`tts.speak` payload**: the brief flags that this API's field names have
  changed across Home Assistant versions and asks that the exact payload be
  confirmed via Developer Tools → Actions before hardcoding it. Since that
  requires a live HA instance this build doesn't have, `ha_client.speak()`
  ships with the current (2024+) `media_player_entity_id` + `cache` shape
  and a comment calling out that it needs to be verified against the
  user's actual HA version before relying on it.
- **AC as a Home-Assistant-only device (no ESP32 relay)**: for a real
  deployment where the AC is itself a Google Home device rather than
  something wired into the relay board, added `ha_client.set_ac()` /
  `HA_AC_ENTITY` / `HA_AC_DOMAIN` and had the backend push AC state to HA
  directly instead of via the ESP32. Specific choices:
  - **Configurable domain** (`HA_AC_DOMAIN`, default `switch`): an AC on a
    smart plug is a `switch.*` entity; a native smart AC/mini-split is
    usually `climate.*`. Rather than guess which one a given user has,
    the domain (and thus which HA service gets called) is an env var.
  - **Backgrounded, not synchronous**: `/api/telemetry` now schedules the
    HA push via FastAPI `BackgroundTasks` instead of calling it inline.
    Before this change, a slow Home Assistant call could add up to
    `HA_REQUEST_TIMEOUT_SECONDS` (default 5s) of latency to the
    `/api/telemetry` response — uncomfortably close to the firmware's own
    ~5s HTTP timeout, risking a telemetry POST timing out on the ESP32
    side purely because HA was slow, which would then trip the firmware's
    "POST failed → force pump off" safety path for an unrelated reason.
    Applied the same backgrounding to the existing alert dispatch for
    consistency.
  - **`/api/relay` pushes AC changes immediately**: fan/pump manual
    commands rely on the ESP32 polling `commanded_relay_state` on its next
    cycle, but there's no ESP32 relay for AC to poll into. Without an
    immediate push, a manual AC toggle from the dashboard would silently
    do nothing until the next telemetry cycle (up to
    `TELEMETRY_INTERVAL_MS`, default 20s) coincidentally re-synced it.
  - **`/api/status` reports HA-confirmed state, not the ESP32's**: the
    ESP32 still receives and could report back an `ac` value from its
    (now unwired) relay pin, but that value means nothing physically.
    `get_status()` substitutes `AppState.last_ha_ac_state` — the last
    state actually confirmed applied via a successful HA call — so the
    dashboard's pending indicator compares against reality instead of a
    disconnected GPIO pin.
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
  Added a scheduler job (`_check_ha_connection`, default every 30s) that
  calls `ha_client.check_connection()` (`GET {HA_URL}/api/`, HA's own
  base health endpoint - works without any entity configured) and caches
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
  own `light` field on `RelayState`, entirely separate from fan/ac/pump.
  It is never passed to `decide_relay_state()` and is not gated by the
  environmental `mode` at all - the requirement was explicit that light
  "will not be affected by auto mode." A new relay channel was chosen
  over repurposing the AC's now-unused pin (AC moved to Home Assistant
  control, see above) to keep the two features independent: reconnecting
  a physical AC relay later shouldn't have any bearing on the light relay.
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
  manual fan/ac/pump command outside manual mode - one consistent pattern
  for "who owns this relay right now" across the whole app, rather than
  inventing a second one for light.
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
  how "reported" is treated as ground truth everywhere else (e.g. the
  AC's HA-confirmed state in `/api/status`).
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

## History charts

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
- **AC moved out of the relay grid into its own "home assistant" panel**:
  previously AC sat alongside fan/pump as a third tile in the `.relays`
  grid, which implied it's the same kind of thing - a local ESP32 relay.
  It isn't: AC has no physical relay and depends entirely on Home
  Assistant being reachable (see "AC: no physical relay" above), so it
  now gets a visually separate panel, distinguishing it the same way the
  light panel is separated (its own section, its own explanatory caption)
  rather than blending into a grid of otherwise-identical tiles.
  `.relays` dropped from 3 columns to 2 (fan, pump) accordingly, and the
  AC/light "single control + pending indicator" row markup was
  generalized from light-specific classes (`.light-btn`, `.light-row`,
  ...) to shared ones (`.control-btn`, `.control-row`, ...) since both
  panels now need the identical layout - kept the light-specific
  behavior (schedule gating) in JS, not duplicated in CSS.
- **AC's "on" accent is teal, not the green/amber used elsewhere**: every
  other "on" state (fan, pump, light) uses green or amber, so AC needed
  its own color to read as visually distinct at a glance - reusing teal
  (already in the palette for the humidity readout) both avoids
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
