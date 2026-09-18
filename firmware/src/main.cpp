#include <Arduino.h>
#include <WiFi.h>

#include "config.h"
#include "network.h"
#include "relays.h"
#include "sensors.h"

static RelayController relays;

static unsigned long lastWifiAttemptMs = 0;
static unsigned long wifiBackoffMs = WIFI_BACKOFF_MIN_MS;
static unsigned long lastTelemetryMs = 0;
static bool haveTelemetrySchedule = false;

static float lastTempC = NAN;

void setup() {
  Serial.begin(SERIAL_BAUD);
  sensors_begin();
  relays.begin();
  network_try_connect();
}

// Drives the WiFi (re)connection state machine with exponential backoff.
// Returns true if a fresh connection was just established this call.
static bool serviceWifi() {
  if (WiFi.status() == WL_CONNECTED) return false;

  unsigned long now = millis();
  if (now - lastWifiAttemptMs < wifiBackoffMs) return false;

  lastWifiAttemptMs = now;
  if (network_try_connect()) {
    wifiBackoffMs = WIFI_BACKOFF_MIN_MS;
    return true;
  }

  wifiBackoffMs = min(wifiBackoffMs * WIFI_BACKOFF_STEP_MULT, WIFI_BACKOFF_MAX_MS);
  return false;
}

static void runTelemetryCycle() {
  Reading reading = sensors_read();
  if (reading.dht_valid) {
    lastTempC = reading.temp_c;
  }

  RelayState actual = relays.getState();
  String mode;
  RelayState commanded;

  bool ok = network_post_telemetry(reading, actual, mode, commanded);
  if (ok) {
    relays.applyCommand(commanded.fan, commanded.ac, commanded.pump, commanded.light);
  } else {
    // The instant a telemetry POST fails: kill the pump, unconditionally.
    relays.forcePumpOff();
  }
}

void loop() {
  // Safety logic must run every iteration, independent of the telemetry
  // cadence and independent of network state.
  relays.tick(lastTempC, WiFi.status() == WL_CONNECTED);

  bool justReconnected = serviceWifi();

  bool connected = WiFi.status() == WL_CONNECTED;
  bool cycleDue = !haveTelemetrySchedule ||
                  (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL_MS);

  // The instant connectivity returns, report immediately rather than
  // waiting out the rest of the current interval.
  if (connected && (justReconnected || cycleDue)) {
    lastTelemetryMs = millis();
    haveTelemetrySchedule = true;
    runTelemetryCycle();
  }

  delay(50);
}
