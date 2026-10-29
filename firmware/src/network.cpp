#include "network.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"

bool network_try_connect() {
  if (WiFi.status() == WL_CONNECTED) return true;

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - start < WIFI_CONNECT_ATTEMPT_TIMEOUT_MS) {
    delay(100);
  }
  return WiFi.status() == WL_CONNECTED;
}

bool network_post_telemetry(const Reading& reading, const RelayState& actual,
                             bool acActual, float pumpCooldownRemainingS,
                             uint32_t pumpLastRunId,
                             String& outMode, RelayState& outCommanded,
                             bool& outAcCommanded, uint32_t& outPumpRunId,
                             uint16_t& outPumpRunSeconds) {
  if (WiFi.status() != WL_CONNECTED) return false;

  StaticJsonDocument<384> req;
  req["temp_c"] = reading.temp_c;
  req["humidity"] = reading.humidity;
  req["soil_moisture"] = reading.soil_moisture;
  req["pump_cooldown_remaining_s"] = pumpCooldownRemainingS;
  req["pump_last_run_id"] = pumpLastRunId;
  JsonObject relayState = req.createNestedObject("relay_state");
  relayState["fan"] = actual.fan;
  relayState["exhaust"] = actual.exhaust;
  relayState["pump"] = actual.pump;
  relayState["light"] = actual.light;
  relayState["ac"] = acActual;

  String body;
  serializeJson(req, body);

  HTTPClient http;
  String url = String("http://") + BACKEND_HOST + ":" + BACKEND_PORT + BACKEND_TELEMETRY_PATH;
  if (!http.begin(url)) return false;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");

  int status = http.POST(body);
  if (status != 200) {
    http.end();
    return false;
  }

  String responseBody = http.getString();
  http.end();

  StaticJsonDocument<384> res;
  DeserializationError err = deserializeJson(res, responseBody);
  if (err) return false;

  if (!res.containsKey("mode") || !res.containsKey("relay_state")) return false;

  outMode = res["mode"].as<String>();
  JsonObject cmd = res["relay_state"];
  outCommanded.fan = cmd["fan"] | false;
  outCommanded.exhaust = cmd["exhaust"] | false;
  outCommanded.light = cmd["light"] | false;
  outAcCommanded = cmd["ac"] | false;

  // Optional, present only while the backend has an unacknowledged run.
  JsonObject pumpRun = res["pump_run"];
  outPumpRunId = pumpRun.isNull() ? 0 : (uint32_t)(pumpRun["id"] | 0UL);
  outPumpRunSeconds = pumpRun.isNull() ? 0 : (uint16_t)(pumpRun["seconds"] | 0);

  return true;
}
