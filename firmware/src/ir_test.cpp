// One-time utility, NOT part of the production firmware - built only by
// the `ir_test` PlatformIO environment (see platformio.ini). Sends the
// captured AC ON/OFF codes (ir_codes.h) alternately every 5 seconds, so
// you can confirm the IR transmitter is wired correctly and the AC
// actually responds before trusting the real firmware/dashboard to
// drive it. Point the module's IRout LED at the AC's receiver window
// and watch/listen for it switching on and off every 5s.
//
// Flash it:
//   pio run -e ir_test -t upload
// Once confirmed, reflash the production firmware:
//   pio run -e esp32dev -t upload
#include <Arduino.h>
#include <IRsend.h>

#include "config.h"
#include "ir_codes.h"

static IRsend irsend(IR_SEND_PIN);
static bool on = false;

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(500);
  irsend.begin();
  Serial.println("ir_test ready - sending AC ON/OFF every 5s. Ctrl+C to stop monitoring.");
}

void loop() {
  on = !on;
  irsend.sendCOOLIX(on ? AC_ON_CODE : AC_OFF_CODE, AC_CODE_BITS);
  Serial.println(on ? "Sent ON" : "Sent OFF");
  delay(5000);
}
