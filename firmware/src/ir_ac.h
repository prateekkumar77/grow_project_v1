#pragma once

// Drives the AC via IR, replaying the exact ON/OFF codes captured from the
// real remote (see ir_codes.h) - not full temperature/mode control, just
// the two fixed states that were captured, matching decide_relay_state()'s
// own binary ac output exactly. Sent via IRremoteESP8266's native COOLIX
// protocol support (this deployment's AC) rather than raw timing replay,
// since the capture tool recognized it; an AC whose protocol the capture
// tool doesn't recognize would instead replay the raw array it still
// prints alongside the decoded form - see ir_codes.h.
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
