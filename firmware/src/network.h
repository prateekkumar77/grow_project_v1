#pragma once

#include <Arduino.h>

#include "relays.h"
#include "sensors.h"

// Non-blocking-ish WiFi connect attempt (blocks up to
// WIFI_CONNECT_ATTEMPT_TIMEOUT_MS). Returns true if connected.
bool network_try_connect();

// POSTs a telemetry payload built from `reading` + `actual` to the backend,
// plus `acActual` (AC is IR-driven, not a relay, so it isn't part of
// RelayState - see ir_ac.h) and `pumpCooldownRemainingS` (0 if the pump
// isn't in its post-cap cooldown) so the dashboard can show "cooldown"
// instead of a generic, indefinitely-stuck "pending" while the firmware is
// refusing a pump run, and `pumpLastRunId` (the id of the last pump run
// request this firmware acted on) so the backend knows when to stop
// re-sending a request. On success, fills `outMode`, `outCommanded`,
// `outAcCommanded`, and `outPumpRunId`/`outPumpRunSeconds` (0 = no pump run
// requested) from the backend's response and returns true. On any failure
// (no connection, timeout, bad response, non-200 status), returns false and
// leaves the out-params untouched. outCommanded.pump is never set - the
// pump only runs via run requests.
bool network_post_telemetry(const Reading& reading, const RelayState& actual,
                             bool acActual, float pumpCooldownRemainingS,
                             uint32_t pumpLastRunId,
                             String& outMode, RelayState& outCommanded,
                             bool& outAcCommanded, uint32_t& outPumpRunId,
                             uint16_t& outPumpRunSeconds);
