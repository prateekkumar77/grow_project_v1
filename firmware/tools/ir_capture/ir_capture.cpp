// One-time utility, NOT part of the production firmware - this is the
// `ir_capture` PlatformIO environment's only source file (see
// platformio.ini), built and flashed separately from the main esp32dev
// firmware. Reads raw IR codes off your actual AC remote for pasting into
// firmware/include/ir_codes.h. See "Capturing your AC's IR codes" in
// README.md for the full walkthrough.
//
// Wire the IR module's IRin pin to kRecvPin below (matching this
// project's IR_RECV_PIN wiring notes in config.h/README), build and flash
// just this environment:
//   pio run -e ir_capture -t upload && pio device monitor
// then point your real AC remote at the module and press a button. Each
// press prints a human-readable summary and a ready-to-paste raw array -
// copy the array body into AC_ON_RAW_CODE or AC_OFF_RAW_CODE in
// ir_codes.h, once for each button.
#include <Arduino.h>
#include <IRrecv.h>
#include <IRutils.h>

const uint16_t kRecvPin = 32;  // matches the IRin wiring documented in README.md
const uint16_t kCaptureBufferSize = 1024;
const uint8_t kTimeoutMs = 50;

IRrecv irrecv(kRecvPin, kCaptureBufferSize, kTimeoutMs, true);
decode_results results;

void setup() {
  Serial.begin(115200);
  delay(500);
  irrecv.enableIRIn();
  Serial.println("Ready - point your AC remote at the receiver and press a button.");
}

void loop() {
  if (irrecv.decode(&results)) {
    Serial.println(resultToHumanReadableBasic(&results));
    Serial.println(resultToSourceCode(&results));
    Serial.println();
    irrecv.resume();
  }
}
