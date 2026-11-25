const verdictText = {
  ok: "SHARP",
  blurry: "BLURRY",
  glare: "GLARE",
  dark: "DARK",
  bright: "BRIGHT",
  fast: "TOO FAST",
};

export function createUi() {
  const connection = document.querySelector("#connection");
  const timer = document.querySelector("#timer");
  const qcPill = document.querySelector("#qc-pill");
  const speedValue = document.querySelector("#speed-value");
  const speedTrack = document.querySelector(".speed-track");
  const speedFill = document.querySelector("#speed-fill");
  const cardsSeen = document.querySelector("#cards-seen");
  const message = document.querySelector("#message");
  const startButton = document.querySelector("#start-button");
  const stopButton = document.querySelector("#stop-button");
  const markerIds = new Set();
  let speedLimit = 60;
  let motionGateLimit = 120;
  let speedSustainMs = 1000;
  let fastSince = null;
  let lastQc = null;
  let fastOverride = false;

  function displaySpeed(speed) {
    if (speed === null || speed === undefined || !Number.isFinite(speed)) {
      speedValue.textContent = "—";
      speedFill.style.width = "0%";
      speedTrack.setAttribute("aria-valuenow", "0");
      return;
    }
    speedValue.textContent = `${Math.round(speed)}°/s`;
    const percent = Math.min(100, speed / speedLimit * 100);
    speedFill.style.width = `${percent}%`;
    speedTrack.setAttribute("aria-valuenow", `${Math.round(speed)}`);
    speedFill.dataset.state = speed > 120 ? "error" : speed > speedLimit ? "warn" : "ok";
  }

  return {
    startButton,
    stopButton,
    setSpeedLimit(limit) { speedLimit = limit; speedTrack.setAttribute("aria-valuemax", `${limit}`); },
    setMotionGateLimit(limit) { motionGateLimit = limit; },
    setSpeedSustainSeconds(seconds) { speedSustainMs = seconds * 1000; },
    setConnection(state) {
      connection.textContent = state === "connected" ? "Connected" : state === "connecting" ? "Connecting" : "Offline";
      connection.dataset.state = state;
    },
    setMessage(value) { message.textContent = value; },
    resetCards() {
      markerIds.clear();
      cardsSeen.textContent = "Cards seen: none";
    },
    setRecording(startedAt) {
      startButton.disabled = startedAt !== null;
      stopButton.disabled = startedAt === null;
      if (startedAt === null) {
        timer.textContent = "00:00";
        qcPill.textContent = "Waiting for camera";
        qcPill.dataset.state = "";
        return;
      }
      const updateTimer = () => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
      };
      updateTimer();
      return window.setInterval(updateTimer, 1000);
    },
    renderSpeed(speed) { displaySpeed(speed); },
    renderMotion(speed) {
      displaySpeed(speed);
      if (speed === null || speed <= speedLimit) {
        fastSince = null;
        if (fastOverride) {
          fastOverride = false;
          if (lastQc) this.renderQc(lastQc);
        }
        return;
      }
      if (fastSince === null) fastSince = performance.now();
      if (!fastOverride && performance.now() - fastSince >= speedSustainMs) {
        fastOverride = true;
        qcPill.textContent = verdictText.fast;
        qcPill.dataset.state = "error";
      }
      if (speed > motionGateLimit) speedFill.dataset.state = "error";
    },
    renderQc(qc) {
      lastQc = qc;
      if (fastOverride) return;
      qcPill.textContent = verdictText[qc.verdict] ?? "QC";
      qcPill.dataset.state = qc.verdict === "ok" ? "ok" : qc.verdict === "fast" || qc.verdict === "blurry" ? "error" : "warn";
      displaySpeed(qc.speed_dps);
      (qc.markers ?? []).forEach((id) => markerIds.add(id));
      cardsSeen.textContent = markerIds.size ? `Cards seen: ${[...markerIds].sort((a, b) => a - b).join(", ")}` : "Cards seen: none";
    },
  };
}
