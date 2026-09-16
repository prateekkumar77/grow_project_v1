#pragma once

struct Reading {
  float temp_c;
  float humidity;
  float soil_moisture;  // percent, 0-100
  bool dht_valid;        // false if the DHT22 read failed this cycle
};

void sensors_begin();
Reading sensors_read();
