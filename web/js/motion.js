export function createMotionSampler(onMotion) {
  let latest = { gyro_dps: null, gravity: null, alpha: null, beta: null, gamma: null };
  let running = false;

  function updateMotion(event) {
    const rotation = event.rotationRate;
    if (rotation) {
      const rates = [rotation.alpha, rotation.beta, rotation.gamma];
      if (rates.every(Number.isFinite)) {
        latest.gyro_dps = Math.hypot(...rates);
      }
    }
    const acceleration = event.accelerationIncludingGravity;
    if (acceleration && [acceleration.x, acceleration.y, acceleration.z].every(Number.isFinite)) {
      latest.gravity = [acceleration.x, acceleration.y, acceleration.z];
    }
    onMotion(latest);
  }

  function updateOrientation(event) {
    latest.alpha = Number.isFinite(event.alpha) ? event.alpha : null;
    latest.beta = Number.isFinite(event.beta) ? event.beta : null;
    latest.gamma = Number.isFinite(event.gamma) ? event.gamma : null;
    onMotion(latest);
  }

  return {
    async start() {
      if (running) return;
      running = true;
      const permissionRequests = [];
      if (typeof window.DeviceMotionEvent?.requestPermission === "function") {
        try { permissionRequests.push(window.DeviceMotionEvent.requestPermission()); } catch { /* sensor stays unknown */ }
      }
      if (typeof window.DeviceOrientationEvent?.requestPermission === "function") {
        try { permissionRequests.push(window.DeviceOrientationEvent.requestPermission()); } catch { /* sensor stays unknown */ }
      }
      // Capture still works with null motion values when a sensor permission is unavailable.
      await Promise.allSettled(permissionRequests);
      window.addEventListener("devicemotion", updateMotion);
      window.addEventListener("deviceorientation", updateOrientation);
    },
    snapshot() {
      return { ...latest, gravity: latest.gravity ? [...latest.gravity] : null };
    },
    stop() {
      running = false;
      window.removeEventListener("devicemotion", updateMotion);
      window.removeEventListener("deviceorientation", updateOrientation);
    },
  };
}
