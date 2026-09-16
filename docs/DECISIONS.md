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

## Docker / infra

- **Home Assistant service**: official `ghcr.io/home-assistant/home-assistant:stable`
  image, `network_mode: host` for local network device discovery (Google
  Home devices, smart plugs), config persisted to a gitignored
  `./ha_config` volume.
