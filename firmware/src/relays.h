#pragma once

#include <stdint.h>

struct RelayState {
  bool fan;
  bool exhaust;
  bool pump;
  bool light;
};

// Owns the four physical relays and enforces the ONLY logic that is allowed
// to run locally: safety limits that must hold even with a dead backend,
// and timing pump runs (the backend asks for "run N seconds" once; the
// ESP32 polls only every ~20s, so it can't time a 3s run itself).
// Everything else (what the relays *should* be doing environmentally, and
// the light/exhaust schedules) is decided by the backend and merely
// applied here via applyCommand().
class RelayController {
 public:
  void begin();

  // Apply a backend- or dashboard-commanded state. fan/exhaust/light apply
  // unconditionally; there is no local logic for them beyond the emergency
  // temperature floor in tick(). The pump isn't part of this - it only
  // runs via startPumpRun().
  void applyCommand(bool fan, bool exhaust, bool light);

  // Run the pump for `seconds` (clamped to MAX_PUMP_RUN_SECONDS), then
  // tick() switches it off on its own - no backend round-trip needed.
  // Refused (pump stays off) while the post-cap cooldown is active.
  void startPumpRun(uint16_t seconds);

  // Must be called frequently (every loop iteration). Enforces, in order:
  //   0. Ending a timed pump run (startPumpRun) once its time is up.
  //   1. Pump max-run cutoff + cooldown arming.
  //   2. Emergency temperature floor while offline.
  // `lastTempC` is the most recent sensor reading (NAN if none yet).
  void tick(float lastTempC, bool wifiConnected);

  // Called the instant a telemetry POST fails. Unconditionally kills the
  // pump regardless of cap/cooldown state.
  void forcePumpOff();

  RelayState getState() const { return {_fan, _exhaust, _pump, _light}; }

  // Seconds left before a commanded pump-on will be honored again, or 0 if
  // no cooldown is active. Reported to the backend so the dashboard can
  // show "cooldown" instead of an indefinitely-stuck generic "pending"
  // while a commanded pump-on is being silently refused.
  float pumpCooldownRemainingSeconds() const;

 private:
  void setFan(bool on);
  void setExhaust(bool on);
  void setPump(bool on);
  void setLight(bool on);
  void writePin(int pin, bool on);

  bool _fan = false;
  bool _exhaust = false;
  bool _pump = false;
  bool _light = false;

  unsigned long _pumpOnSinceMs = 0;      // 0 = pump not currently timed as "on"
  unsigned long _pumpRunMs = 0;          // requested length of the current run; 0 = none
  unsigned long _pumpCooldownUntilMs = 0;  // millis() timestamp; 0 = no cooldown active
};
