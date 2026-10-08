#pragma once

// Drives the AC via IR, replaying raw codes captured from the real remote
// (see ir_codes.h) rather than using a protocol-aware library - works with
// any AC brand regardless of its actual IR protocol, at the cost of only
// ever reproducing the exact on/off state that was captured (no
// temperature/mode control), which matches decide_relay_state()'s own
// binary ac output exactly.
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
