#pragma once

#include <stdint.h>

// IR code for your AC, captured from the real remote via the ir_capture
// utility (see "Capturing your AC's IR codes" in README.md). Your AC uses
// the COOLIX protocol - one IRremoteESP8266 recognizes natively, so this
// is the decoded code (sendCOOLIX() in ir_ac.cpp), not ~200 raw timing
// values. Still just two fixed states replayed as-is, not decoded into
// individual temperature/mode/fan fields - whatever was set on the real
// remote when you captured ON is what gets replayed every time, matching
// decide_relay_state()'s own on/off-only output.
//
// To recapture (different AC, or a different temperature/mode for ON):
// rerun the ir_capture utility and copy whatever it prints as
// `data = 0x......` for each button. If it ever prints "Protocol:
// UNKNOWN" instead of a recognized name, there's no sendXXX() to call -
// fall back to irsend.sendRaw(rawData, length, kHz) in ir_ac.cpp using
// the raw array the tool always prints alongside the decoded form.

const uint64_t AC_ON_CODE = 0xB23F70;
const uint64_t AC_OFF_CODE = 0xB27BE0;
const uint16_t AC_CODE_BITS = 24;
