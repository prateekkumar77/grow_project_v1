#pragma once

// ---------------------------------------------------------------------------
// WiFi
// ---------------------------------------------------------------------------
#define WIFI_SSID "your-ssid"
#define WIFI_PASSWORD "your-password"

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------
#define BACKEND_HOST "192.168.1.100"
#define BACKEND_PORT 8000
#define BACKEND_TELEMETRY_PATH "/api/telemetry"
#define HTTP_TIMEOUT_MS 5000UL

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------
#define TELEMETRY_INTERVAL_MS 20000UL  // how often we read sensors + report

// ---------------------------------------------------------------------------
// Pins
// ---------------------------------------------------------------------------
#define DHT_PIN 4
#define DHT_TYPE DHT22
#define SOIL_MOISTURE_PIN 34  // ADC1 channel, analog-capable pin

#define RELAY_FAN_PIN 25
#define RELAY_EXHAUST_PIN 26
#define RELAY_PUMP_PIN 27
#define RELAY_LIGHT_PIN 33  // grow light - runs on its own backend-side schedule, no local logic
#define RELAY_ACTIVE_LOW true  // most cheap relay boards trigger LOW = energized

// AC - not a relay, an IR transmitter (Adafruit 38KHz IR Transceiver,
// product 5990), driven via IRremoteESP8266's structured COOLIX protocol
// state (see ir_ac.cpp) rather than a captured raw code. See "Capturing
// your AC's IR codes" in README.md for how COOLIX was identified as this
// deployment's protocol in the first place.
#define IR_SEND_PIN 14

// Target temperature the AC is commanded to when turned on - a firmware
// constant (not baked into a captured IR code), via IRremoteESP8266's
// structured COOLIX state API. Change this and reflash to retarget - no
// physical remote needed.
#define AC_TARGET_TEMP_C 20

// The AC sometimes misses an IR signal, so every on/off command is sent
// once more this long after the first send, as a backup.
#define AC_IR_RESEND_DELAY_MS 30000UL

// ---------------------------------------------------------------------------
// Soil moisture calibration
// Raw ADC reading with the sensor in dry air vs. fully in water.
// Recalibrate these two values for your specific sensor/soil.
// ---------------------------------------------------------------------------
#define SOIL_ADC_DRY 3000
#define SOIL_ADC_WET 1200

// ---------------------------------------------------------------------------
// Safety limits (the only local decision-making; always enforced)
// ---------------------------------------------------------------------------
#define MAX_PUMP_RUN_SECONDS 30UL
#define PUMP_COOLDOWN_SECONDS 60UL

// Floor-level emergency temperature cutoff used ONLY while offline.
// 35.0C is a starting guess for a small enclosed tent - sanity-check this
// against your actual tent/strain heat tolerance before relying on it.
#define EMERGENCY_TEMP_C 35.0f

// ---------------------------------------------------------------------------
// WiFi reconnect backoff
// ---------------------------------------------------------------------------
#define WIFI_BACKOFF_MIN_MS 5000UL
#define WIFI_BACKOFF_MAX_MS 60000UL
#define WIFI_BACKOFF_STEP_MULT 2UL
#define WIFI_CONNECT_ATTEMPT_TIMEOUT_MS 8000UL

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 115200
