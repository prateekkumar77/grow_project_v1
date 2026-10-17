#include "ir_ac.h"

#include <Arduino.h>
#include <ir_Coolix.h>

#include "config.h"

static IRCoolixAC ac(IR_SEND_PIN);

void IrAcController::begin() {
  ac.begin();
}

void IrAcController::applyCommand(bool on) {
  if (on == _on) return;
  transmit(on);
  _on = on;
  // Re-armed on every new command, so if the state flips again inside the
  // window the pending backup is for the new state, never a stale one.
  _resendPending = true;
  _sentAtMs = millis();
}

void IrAcController::tick() {
  if (!_resendPending) return;
  if (millis() - _sentAtMs < AC_IR_RESEND_DELAY_MS) return;
  transmit(_on);
  _resendPending = false;
}

void IrAcController::transmit(bool on) {
  // Set a fully-known state on every send, not just when turning on -
  // avoids depending on whatever the object's state happened to be from
  // a previous call (or its freshly-constructed default, on the very
  // first call).
  ac.setMode(kCoolixCool);
  ac.setFan(kCoolixFanMax);
  ac.setTemp(AC_TARGET_TEMP_C);
  ac.setPower(on);
  ac.send();
}
