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
  pinMode(RELAY_AC_PIN, OUTPUT);
  pinMode(RELAY_PUMP_PIN, OUTPUT);
  pinMode(RELAY_LIGHT_PIN, OUTPUT);
  setFan(false);
  setAc(false);
  setPump(false);
  setLight(false);
}

void RelayController::setFan(bool on) {
  _fan = on;
  writePin(RELAY_FAN_PIN, on);
}

void RelayController::setAc(bool on) {
  _ac = on;
  writePin(RELAY_AC_PIN, on);
}

void RelayController::setPump(bool on) {
  _pump = on;
  writePin(RELAY_PUMP_PIN, on);
}

void RelayController::setLight(bool on) {
  _light = on;
  writePin(RELAY_LIGHT_PIN, on);
}

void RelayController::applyCommand(bool fan, bool ac, bool pump, bool light) {
  setFan(fan);
  setAc(ac);
  setLight(light);

  if (pump && !_pump) {
    // Turning the pump on: refuse if we're still in a cap-triggered cooldown.
    if (millis() >= _pumpCooldownUntilMs) {
      setPump(true);
      _pumpOnSinceMs = millis();
    }
    // else: stay off, silently refuse. The backend can keep asking; it just
    // won't be honored again until the cooldown expires.
  } else if (!pump && _pump) {
    setPump(false);
    _pumpOnSinceMs = 0;
  }
}

void RelayController::tick(float lastTempC, bool wifiConnected) {
  // 1. Pump max-run cutoff - always enforced, regardless of mode or network.
  if (_pump && _pumpOnSinceMs != 0) {
    unsigned long elapsedMs = millis() - _pumpOnSinceMs;
    if (elapsedMs >= MAX_PUMP_RUN_SECONDS * 1000UL) {
      setPump(false);
      _pumpOnSinceMs = 0;
      _pumpCooldownUntilMs = millis() + PUMP_COOLDOWN_SECONDS * 1000UL;
    }
  }

  // 2. Emergency temperature floor - only matters while we have no backend
  // to make a real decision. This never turns things back OFF; it's a
  // one-way floor, not real control.
  if (!wifiConnected && !isnan(lastTempC) && lastTempC >= EMERGENCY_TEMP_C) {
    setFan(true);
    setAc(true);
  }
}

void RelayController::forcePumpOff() {
  setPump(false);
  _pumpOnSinceMs = 0;
}
