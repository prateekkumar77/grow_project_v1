#pragma once

// Drives the AC via IR using IRremoteESP8266's structured COOLIX protocol
// state (IRCoolixAC, see ir_ac.cpp) - not a captured raw code replay. The
// target temperature (AC_TARGET_TEMP_C in config.h) is a firmware
// constant, changeable without ever touching the physical remote again.
// Still just a binary on/off like decide_relay_state()'s own `ac` output -
// every "on" command targets the same fixed temperature/mode/fan, there's
// no per-request temperature control.
class IrAcController {
 public:
  void begin();

  // Only actually transmits when `on` differs from the last applied
  // state - unlike a relay pin, re-sending the same IR code is not a
  // harmless no-op: many AC remotes send a full state packet every press,
  // and spamming it every ~20s telemetry cycle would be wasteful at best.
  void applyCommand(bool on);

  bool getState() const { return _on; }

 private:
  bool _on = false;
};
