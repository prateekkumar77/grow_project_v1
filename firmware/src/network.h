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
// refusing a commanded pump-on. On success, fills `outMode`, `outCommanded`,
// and `outAcCommanded` from the backend's response and returns true. On any
// failure (no connection, timeout, bad response, non-200 status), returns
// false and leaves the out-params untouched.
bool network_post_telemetry(const Reading& reading, const RelayState& actual,
                             bool acActual, float pumpCooldownRemainingS,
                             String& outMode, RelayState& outCommanded,
                             bool& outAcCommanded);
