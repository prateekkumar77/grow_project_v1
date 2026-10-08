// One-time utility, NOT part of the production firmware - built only by
// the `ir_capture` PlatformIO environment (see platformio.ini's
// build_src_filter, which excludes this file from the main esp32dev
// build and excludes everything else from this one), flashed separately
// from the main firmware. Reads raw IR codes off your actual AC remote
// for pasting into firmware/include/ir_codes.h. See "Capturing your AC's
// IR codes" in README.md for the full walkthrough.
//
// Wire the IR module's IRin pin to GPIO 32 (matching this project's
// IR_RECV_PIN wiring notes in config.h/README), build and flash just
// this environment:
//   pio run -e ir_capture -t upload && pio device monitor
// then point your real AC remote at the module and press a button. Each
// press prints a human-readable summary and a ready-to-paste raw array -
// copy the array body into AC_ON_RAW_CODE or AC_OFF_RAW_CODE in
// ir_codes.h, once for each button.
#include <Arduino.h>
#include <IRrecv.h>
#include <IRutils.h>

// Passed directly into the constructor below rather than named constants -
// IRrecv.h already declares its own globals named kTimeoutMs and the like
// for its default constructor arguments, and this file doesn't need named
// constants badly enough to risk colliding with whatever else it defines.
IRrecv irrecv(/*recvpin=*/32, /*bufsize=*/1024, /*timeout=*/50, /*save_buffer=*/true);
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
