#pragma once

struct Reading {
  float temp_c;
  float humidity;
  float soil_moisture;  // percent, 0-100
  int soil_raw;          // raw ADC value behind soil_moisture - for calibrating SOIL_ADC_DRY/WET
  bool dht_valid;        // false if the DHT22 read failed this cycle
};

void sensors_begin();
Reading sensors_read();
