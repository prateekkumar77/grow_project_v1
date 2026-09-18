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
#define RELAY_AC_PIN 26  // leave unwired if the AC is a Home Assistant/Google Home device instead
#define RELAY_PUMP_PIN 27
#define RELAY_ACTIVE_LOW true  // most cheap relay boards trigger LOW = energized

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
//
// NOTE: if your AC is controlled via Home Assistant/Google Home instead of
// RELAY_AC_PIN (see backend HA_AC_ENTITY in .env), this floor forcing "ac"
// on here has no physical effect - that relay channel is unwired. The fan
// is then the only local backstop against an offline network; the AC has
// none.
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
