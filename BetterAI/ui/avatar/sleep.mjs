// Sleep only arranges her body. It never changes Aria's microphone or conversation state.
export function resting(state, focus = 'off') {
  return (state === 'sleeping' || state === 'companion') && focus === 'off';
}

export function sleepAction({ asleep, busy, seated, perched, canPerch, sinceRest, sinceDoze }) {
  if (!asleep || busy) return null;
  if (!seated && !perched) return canPerch ? { perch: true } : { sit: true };
  if (sinceRest > 12 && sinceDoze > 45) return { gesture: 'doze' };
  return null;
}

// Finish getting up even if the next awake state is idle (a closed microphone).
export function wakeAction({ waking, seated, perched, jumping }) {
  if (!waking) return null;
  if (perched && !jumping) return { hopDown: true };
  if (seated) return { stand: true };
  return null;
}

// Music and newly raised windows may catch her attention after school, never during quiet sleep.
export function sleepAllowsActivity(state) {
  return state !== 'sleeping';
}
