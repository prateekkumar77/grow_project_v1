#include "ir_ac.h"

#include <ir_Coolix.h>

#include "config.h"

static IRCoolixAC ac(IR_SEND_PIN);

void IrAcController::begin() {
  ac.begin();
}

void IrAcController::applyCommand(bool on) {
  if (on == _on) return;
  // Set a fully-known state on every call, not just when turning on -
  // avoids depending on whatever the object's state happened to be from
  // a previous call (or its freshly-constructed default, on the very
  // first call).
  ac.setMode(kCoolixCool);
  ac.setFan(kCoolixFanAuto);
  ac.setTemp(AC_TARGET_TEMP_C);
  ac.setPower(on);
  ac.send();
  _on = on;
}
