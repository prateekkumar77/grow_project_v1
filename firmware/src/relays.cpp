#include "relays.h"

#include <Arduino.h>
#include <math.h>

#include "config.h"

void RelayController::writePin(int pin, bool on) {
  bool level = RELAY_ACTIVE_LOW ? !on : on;
  digitalWrite(pin, level ? HIGH : LOW);
}

void RelayController::begin() {
  pinMode(RELAY_FAN_PIN, OUTPUT);
  pinMode(RELAY_EXHAUST_PIN, OUTPUT);
  pinMode(RELAY_PUMP_PIN, OUTPUT);
  pinMode(RELAY_LIGHT_PIN, OUTPUT);
  setFan(false);
  setExhaust(false);
  setPump(false);
  setLight(false);
}

void RelayController::setFan(bool on) {
  _fan = on;
  writePin(RELAY_FAN_PIN, on);
}

void RelayController::setExhaust(bool on) {
  _exhaust = on;
  writePin(RELAY_EXHAUST_PIN, on);
}

void RelayController::setPump(bool on) {
  _pump = on;
  writePin(RELAY_PUMP_PIN, on);
}

void RelayController::setLight(bool on) {
  _light = on;
  writePin(RELAY_LIGHT_PIN, on);
}

void RelayController::applyCommand(bool fan, bool exhaust, bool light) {
  setFan(fan);
  setExhaust(exhaust);
  setLight(light);
}

void RelayController::startPumpRun(uint16_t seconds) {
  if (seconds == 0) return;
  // Refuse if we're still in a cap-triggered cooldown - stay off silently.
  if (millis() < _pumpCooldownUntilMs) return;
  unsigned long runSeconds = seconds > MAX_PUMP_RUN_SECONDS ? MAX_PUMP_RUN_SECONDS : seconds;
  setPump(true);
  _pumpOnSinceMs = millis();
  _pumpRunMs = runSeconds * 1000UL;
}

void RelayController::tick(float lastTempC, bool wifiConnected) {
  // 0. Normal end of a timed pump run - checked before the cap so a run of
  // exactly MAX_PUMP_RUN_SECONDS ends normally without arming the cooldown.
  if (_pump && _pumpOnSinceMs != 0 && _pumpRunMs != 0 &&
      millis() - _pumpOnSinceMs >= _pumpRunMs) {
    setPump(false);
    _pumpOnSinceMs = 0;
    _pumpRunMs = 0;
  }

  // 1. Pump max-run cutoff - always enforced, regardless of mode or network.
  if (_pump && _pumpOnSinceMs != 0) {
    unsigned long elapsedMs = millis() - _pumpOnSinceMs;
    if (elapsedMs >= MAX_PUMP_RUN_SECONDS * 1000UL) {
      setPump(false);
      _pumpOnSinceMs = 0;
      _pumpRunMs = 0;
      _pumpCooldownUntilMs = millis() + PUMP_COOLDOWN_SECONDS * 1000UL;
    }
  }

  // 2. Emergency temperature floor - only matters while we have no backend
  // to make a real decision. This never turns things back OFF; it's a
  // one-way floor, not real control.
  if (!wifiConnected && !isnan(lastTempC) && lastTempC >= EMERGENCY_TEMP_C) {
    setFan(true);
    setExhaust(true);
  }
}

void RelayController::forcePumpOff() {
  setPump(false);
  _pumpOnSinceMs = 0;
  _pumpRunMs = 0;
}

float RelayController::pumpCooldownRemainingSeconds() const {
  if (millis() >= _pumpCooldownUntilMs) return 0.0f;
  return (_pumpCooldownUntilMs - millis()) / 1000.0f;
}
