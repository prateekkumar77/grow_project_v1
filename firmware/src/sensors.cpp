#include "sensors.h"

#include <Arduino.h>
#include <DHT.h>

#include "config.h"

static DHT dht(DHT_PIN, DHT_TYPE);

void sensors_begin() {
  dht.begin();
  analogReadResolution(12);  // ESP32 ADC: 0-4095
}

static float soil_raw_to_percent(int raw) {
  // SOIL_ADC_DRY (0%) .. SOIL_ADC_WET (100%), clamped.
  float pct = (float)(SOIL_ADC_DRY - raw) * 100.0f / (float)(SOIL_ADC_DRY - SOIL_ADC_WET);
  if (pct < 0.0f) pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  return pct;
}

Reading sensors_read() {
  Reading r;
  r.humidity = dht.readHumidity();
  r.temp_c = dht.readTemperature();
  r.dht_valid = !(isnan(r.humidity) || isnan(r.temp_c));

  int raw = analogRead(SOIL_MOISTURE_PIN);
  r.soil_moisture = soil_raw_to_percent(raw);

  return r;
}
