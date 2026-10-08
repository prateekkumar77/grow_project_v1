#pragma once

#include <stdint.h>

// Raw IR timing codes captured from your actual AC remote - these are
// PLACEHOLDERS (a short, meaningless blip) that will not control any real
// air conditioner. See "Capturing your AC's IR codes" in README.md: build
// and flash the `ir_capture` PlatformIO environment (`pio run -e
// ir_capture -t upload`, not the main firmware), point your real remote
// at the module's IR receiver, press ON then OFF, and paste each captured
// array below in place of the placeholder - keep the `_LEN` lines as-is,
// they compute themselves from whatever array you paste in.
//
// Captured once per remote, not per AC setting: most AC remotes send a
// complete state (power + temperature + mode + fan speed) on every button
// press rather than a simple toggle, so whatever temperature/mode was
// active on the real remote when you captured "on" is what gets replayed
// every time - matching decide_relay_state()'s own on/off-only output, no
// IR protocol knowledge required.
//
// (No PROGMEM here - unlike AVR Arduinos, the ESP32 has a unified address
// space, so a plain `const` array at file scope already lives in flash.)

const uint16_t AC_ON_RAW_CODE[] = {9000, 4500, 560, 560, 560, 1690, 560, 560};
const uint16_t AC_OFF_RAW_CODE[] = {9000, 4500, 560, 1690, 560, 560, 560, 560};
const uint16_t AC_ON_RAW_CODE_LEN = sizeof(AC_ON_RAW_CODE) / sizeof(AC_ON_RAW_CODE[0]);
const uint16_t AC_OFF_RAW_CODE_LEN = sizeof(AC_OFF_RAW_CODE) / sizeof(AC_OFF_RAW_CODE[0]);

// Standard IR carrier frequency - correct for the vast majority of
// consumer IR remotes, including this module. The capture tool's output
// prints the actual frequency it detected; change this only if that
// differs from 38.
const uint16_t AC_RAW_FREQUENCY_KHZ = 38;
