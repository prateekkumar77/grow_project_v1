#include "ir_ac.h"

#include <IRsend.h>

#include "config.h"
#include "ir_codes.h"

static IRsend irsend(IR_SEND_PIN);

void IrAcController::begin() {
  irsend.begin();
}

void IrAcController::applyCommand(bool on) {
  if (on == _on) return;
  irsend.sendCOOLIX(on ? AC_ON_CODE : AC_OFF_CODE, AC_CODE_BITS);
  _on = on;
}
