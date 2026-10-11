// One-time utility, NOT part of the production firmware - built only by
// the `ir_test` PlatformIO environment (see platformio.ini). Sends the
// AC's COOLIX ON (at AC_TARGET_TEMP_C)/OFF states alternately every 5
// seconds using the same IRCoolixAC structured API as the real firmware
// (ir_ac.cpp), so you can confirm the IR transmitter is wired correctly
// and the AC actually responds before trusting the real firmware/
// dashboard to drive it. Point the module's IRout LED at the AC's
// receiver window and watch/listen for it switching on and off every 5s.
//
// Flash it:
//   pio run -e ir_test -t upload
// Once confirmed, reflash the production firmware:
//   pio run -e esp32dev -t upload
#include <Arduino.h>
#include <ir_Coolix.h>

#include "config.h"

static IRCoolixAC ac(IR_SEND_PIN);
static bool on = false;

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);
  ac.begin();
  Serial.println("ir_test ready - sending AC ON/OFF every 5s. Ctrl+C to stop monitoring.");
}

void loop() {
  on = !on;
  ac.setMode(kCoolixCool);
  ac.setFan(kCoolixFanMax);
  ac.setTemp(AC_TARGET_TEMP_C);
  ac.setPower(on);
  ac.send();
  Serial.println(on ? "Sent ON" : "Sent OFF");
  delay(5000);
}
