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
                             String& outMode, RelayState& outCommanded) {
  if (WiFi.status() != WL_CONNECTED) return false;

  StaticJsonDocument<256> req;
  req["temp_c"] = reading.temp_c;
  req["humidity"] = reading.humidity;
  req["soil_moisture"] = reading.soil_moisture;
  JsonObject relayState = req.createNestedObject("relay_state");
  relayState["fan"] = actual.fan;
  relayState["ac"] = actual.ac;
  relayState["pump"] = actual.pump;
  relayState["light"] = actual.light;

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

  StaticJsonDocument<256> res;
  DeserializationError err = deserializeJson(res, responseBody);
  if (err) return false;

  if (!res.containsKey("mode") || !res.containsKey("relay_state")) return false;

  outMode = res["mode"].as<String>();
  JsonObject cmd = res["relay_state"];
  outCommanded.fan = cmd["fan"] | false;
  outCommanded.ac = cmd["ac"] | false;
  outCommanded.pump = cmd["pump"] | false;
  outCommanded.light = cmd["light"] | false;

  return true;
}
