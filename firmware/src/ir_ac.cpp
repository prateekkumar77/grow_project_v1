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
  if (on) {
    irsend.sendRaw(AC_ON_RAW_CODE, AC_ON_RAW_CODE_LEN, AC_RAW_FREQUENCY_KHZ);
  } else {
    irsend.sendRaw(AC_OFF_RAW_CODE, AC_OFF_RAW_CODE_LEN, AC_RAW_FREQUENCY_KHZ);
  }
  _on = on;
}
