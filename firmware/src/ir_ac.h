#pragma once

#include <stdint.h>

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
  // Each transmission is repeated once by tick() AC_IR_RESEND_DELAY_MS
  // later, as a backup in case the AC missed the first one.
  void applyCommand(bool on);

  // Call every loop() iteration - sends the pending backup once its delay
  // has passed. Non-blocking.
  void tick();

  bool getState() const { return _on; }

 private:
  void transmit(bool on);

  bool _on = false;
  bool _resendPending = false;
  uint32_t _sentAtMs = 0;
};
