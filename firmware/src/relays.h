#pragma once

struct RelayState {
  bool fan;
  bool ac;
  bool pump;
};

// Owns the three physical relays and enforces the ONLY logic that is allowed
// to run locally: safety limits that must hold even with a dead backend.
// Everything else (what the relays *should* be doing environmentally) is
// decided by the backend and merely applied here via applyCommand().
class RelayController {
 public:
  void begin();

  // Apply a backend- or dashboard-commanded state. Subject to the pump
  // cap/cooldown safety check below - a commanded pump-on can be refused.
  void applyCommand(bool fan, bool ac, bool pump);

  // Must be called frequently (every loop iteration). Enforces, in order:
  //   1. Pump max-run cutoff + cooldown arming.
  //   2. Emergency temperature floor while offline.
  // `lastTempC` is the most recent sensor reading (NAN if none yet).
  void tick(float lastTempC, bool wifiConnected);

  // Called the instant a telemetry POST fails. Unconditionally kills the
  // pump regardless of cap/cooldown state.
  void forcePumpOff();

  RelayState getState() const { return {_fan, _ac, _pump}; }

 private:
  void setFan(bool on);
  void setAc(bool on);
  void setPump(bool on);
  void writePin(int pin, bool on);

  bool _fan = false;
  bool _ac = false;
  bool _pump = false;

  unsigned long _pumpOnSinceMs = 0;      // 0 = pump not currently timed as "on"
  unsigned long _pumpCooldownUntilMs = 0;  // millis() timestamp; 0 = no cooldown active
};
