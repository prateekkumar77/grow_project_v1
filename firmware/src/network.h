#pragma once

#include "relays.h"
#include "sensors.h"

// Non-blocking-ish WiFi connect attempt (blocks up to
// WIFI_CONNECT_ATTEMPT_TIMEOUT_MS). Returns true if connected.
bool network_try_connect();

// POSTs a telemetry payload built from `reading` + `actual` to the backend.
// On success, fills `outMode` and `outCommanded` from the backend's response
// and returns true. On any failure (no connection, timeout, bad response,
// non-200 status), returns false and leaves the out-params untouched.
bool network_post_telemetry(const Reading& reading, const RelayState& actual,
                             String& outMode, RelayState& outCommanded);
