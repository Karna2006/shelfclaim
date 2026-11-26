import { openCamera } from "./camera.js";
import { createLiveSocket } from "./live.js";
import { createMotionSampler } from "./motion.js";
import { createSpeechIn, createSpeechOut } from "./speech.js";
import { createCaptureSocket } from "./ws.js";
import { createUi } from "./ui.js";
import { createDebugLog } from "./debug.js";

const ui = createUi();
const video = document.querySelector("#preview");
const canvas = document.querySelector("#capture-canvas");
const typedFallback = document.querySelector("#typed-fallback");
const typedMessage = document.querySelector("#typed-message");
const interruptButton = document.querySelector("#interrupt-button");
const retryMicButton = document.querySelector("#retry-mic");
const logEvent = createDebugLog(document.querySelector("#debug-events"));
let camera = null;
let motion = null;
let captureSocket = null;
let liveSocket = null;
let speechIn = null;
let speechOut = null;
let active = false;
let captureStartedAt = 0;
let lastFrameAt = 0;
let lastLiveFrameAt = 0;
let frameTimer = null;
let motionTimer = null;
let recordingTimer = null;
let wakeLock = null;
let options = null;
let pendingUserTexts = [];
let pendingSpeechEvents = [];
let speechActivityTimer = null;

async function requestWakeLock() {
  if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try { wakeLock = await navigator.wakeLock.request("screen"); } catch { wakeLock = null; }
}
async function releaseWakeLock() {
  if (wakeLock) await wakeLock.release();
  wakeLock = null;
}

function setupSpeech() {
  speechIn = createSpeechIn({
    onFinal: (text) => { sendSpeechActivity(false); sendUserText(text); },
    onInterim: () => sendSpeechActivity(true),
    onUnsupported: (reason) => {
      typedFallback.hidden = false;
      ui.showVoiceGuidance(true);
      logEvent("speech", `unsupported: ${reason}`);
    },
    onBlocked: () => {
      ui.showMicBlocked(true);
      typedFallback.hidden = false;
      logEvent("speech", "microphone blocked by recognition service");
    },
    onStatus: (state) => ui.setMicStatus(state),
    onEvent: (name, detail) => {
      logEvent("speech", `${name}: ${detail}`);
      if (/^(onstart|onend|onerror|start error|restart|forced-final|unsupported browser)$/i.test(name)) {
        if (liveSocket) liveSocket.sendSpeechEvent(name, detail, sweepTimeMs());
        else pendingSpeechEvents.push({ name, detail });
      }
    },
  });
  speechOut = createSpeechOut({
    pauseInput: () => speechIn?.pause(),
    resumeInput: () => { if (active) speechIn?.resume(); },
    onSpeakingChange: (speaking) => { interruptButton.hidden = !speaking; },
  });
  if (speechIn.supported) {
    typedFallback.hidden = true;
    ui.showVoiceGuidance(false);
  }
}

function sendUserText(text) {
  if (!liveSocket) {
    pendingUserTexts.push(text);
    logEvent("live ws", "queued final text; socket not created yet");
    return;
  }
  liveSocket.sendFinalText(text, sweepTimeMs());
}

function sendSpeechActivity(speaking) {
  liveSocket?.sendSpeechActivity(speaking);
  clearTimeout(speechActivityTimer);
  if (speaking) speechActivityTimer = window.setTimeout(() => liveSocket?.sendSpeechActivity(false), 1200);
}

async function requestMicAndListen() {
  const getUserMedia = navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices);
  if (!getUserMedia) {
    ui.setMicStatus("unsupported");
    typedFallback.hidden = false;
    ui.showVoiceGuidance(true);
    logEvent("speech", "microphone API unavailable");
    return false;
  }
  let permissionStream;
  try {
    logEvent("speech", "requesting microphone permission");
    permissionStream = await getUserMedia({ audio: true });
    permissionStream.getAudioTracks().forEach((track) => track.stop());
    logEvent("speech", "microphone permission granted; temporary tracks stopped");
    ui.showMicBlocked(false);
    if (speechIn?.supported) speechIn.start();
    return true;
  } catch (error) {
    permissionStream?.getTracks().forEach((track) => track.stop());
    const name = error?.name || "unknown";
    logEvent("speech", `microphone permission error: ${name}`);
    if (name === "NotAllowedError" || name === "SecurityError") {
      ui.setMicStatus("blocked");
      ui.showMicBlocked(true);
    } else {
      ui.setMicStatus(`error:${name}`);
    }
    typedFallback.hidden = false;
    return false;
  }
}

async function startSweep() {
  pendingUserTexts = [];
  pendingSpeechEvents = [];
  ui.startButton.disabled = true;
  ui.setMessage("Requesting camera and motion access…");
  try {
    setupSpeech();
    await requestMicAndListen();
    motion = createMotionSampler((sample) => ui.renderMotion(sample.gyro_dps));
    const motionPermission = motion.start();
    camera = await openCamera(video);
    await motionPermission;
    const width = camera.settings.width ?? video.videoWidth;
    const height = camera.settings.height ?? video.videoHeight;
    const response = await fetch("/api/sweeps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: `${navigator.userAgent} / ${width}x${height}` }),
    });
    if (!response.ok) throw new Error(`Sweep creation failed (${response.status})`);
    const sweep = await response.json();
    options = { ...sweep.capture, hires_fps: sweep.hires_fps };
    speechIn?.setForceFinalAfter?.(sweep.interim_force_final_ms ?? 8000);
    speechOut?.setBargeInMode(sweep.barge_in_mode === true);
    options.live_frame_max_side = sweep.live_frame_max_side;
    options.live_frame_quality = sweep.live_frame_quality;
    ui.setSpeedLimit(options.speed_max_dps);
    ui.setMotionGateLimit(options.frame_gyro_max_dps);
    ui.setSpeedSustainSeconds(options.speed_sustain_s);
    ui.resetCards();
    captureSocket = createCaptureSocket(sweep.sweep_id, options, {
      onConnection: (state) => ui.setConnection(state),
      onQc: (qc) => ui.renderQc(qc),
      onMessage: (text) => ui.setMessage(text),
      onDebug: (event) => logEvent("capture ws", event),
    });
    liveSocket = createLiveSocket(sweep.sweep_id, {
      onConnection: (state) => ui.setAgentConnection(state),
      onMessage: handleAgentMessage,
      onDebug: (event) => logEvent("live ws", event),
    });
    pendingSpeechEvents.splice(0).forEach(({ name, detail }) => {
      liveSocket.sendSpeechEvent(name, detail, sweepTimeMs());
    });
    captureStartedAt = performance.now();
    lastFrameAt = captureStartedAt - options.frame_min_interval_ms;
    lastLiveFrameAt = captureStartedAt - 1000;
    pendingUserTexts.splice(0).forEach((text) => liveSocket.sendFinalText(text, sweepTimeMs()));
    active = true;
    ui.setMessage(`Sweep ${sweep.sweep_id}: capturing ${width}×${height}. Move slowly along each shelf.`);
    recordingTimer = ui.setRecording(Date.now());
    await requestWakeLock();
    scheduleFrame();
    motionTimer = window.setInterval(() => {
      if (active) captureSocket?.sendMotion(motion.snapshot(), Math.round(performance.now() - captureStartedAt));
    }, 1000 / options.motion_sample_hz);
  } catch (error) {
    await stopSweep();
    ui.setMessage(error instanceof Error ? error.message : "Could not start the sweep.");
    ui.startButton.disabled = false;
  }
}

function handleAgentMessage(message) {
  if (message.type === "agent_text") speechOut?.speak(message.text);
  if (message.type === "cue") speechOut?.speakCue(message.text, message.priority ?? 10);
  if (message.type === "user_text_accepted") speechOut?.cancel();
  if (message.type === "inventory") ui.renderInventory(message);
  if (message.type === "packet_ready") ui.showReportLink(message.report_url);
  if (message.type === "control" && message.action === "stop_capture") stopSweep();
  if (message.type === "error") ui.setMessage(message.message);
}

function scheduleFrame() {
  if (active) frameTimer = window.setTimeout(captureFrame, 1000 / options.hires_fps);
}
function sweepTimeMs() {
  return Math.max(0, Math.round(performance.now() - captureStartedAt));
}
async function captureFrame() {
  if (!active) return;
  const now = performance.now();
  const sample = motion.snapshot();
  const elapsed = now - lastFrameAt;
  const movingTooFast = sample.gyro_dps !== null && sample.gyro_dps > options.frame_gyro_max_dps;
  if (elapsed >= options.frame_min_interval_ms && !movingTooFast) {
    try {
      const blob = await camera.captureJpeg(canvas, options.jpeg_quality);
      captureSocket?.enqueueFrame(blob, {
        t_ms: Math.round(performance.now() - captureStartedAt),
        w: canvas.width,
        h: canvas.height,
        motion: sample,
      });
      lastFrameAt = performance.now();
      if (lastFrameAt - lastLiveFrameAt >= 1000) {
        const agentFrame = await camera.captureLiveJpeg(options.live_frame_max_side, options.live_frame_quality);
        await liveSocket?.sendFrame(agentFrame, sweepTimeMs());
        lastLiveFrameAt = performance.now();
      }
    } catch (error) {
      ui.setMessage(error instanceof Error ? error.message : "Frame capture failed.");
    }
  }
  scheduleFrame();
}

async function stopSweep() {
  active = false;
  if (frameTimer !== null) window.clearTimeout(frameTimer);
  if (motionTimer !== null) window.clearInterval(motionTimer);
  if (recordingTimer !== null) window.clearInterval(recordingTimer);
  clearTimeout(speechActivityTimer);
  frameTimer = motionTimer = recordingTimer = null;
  speechIn?.stop();
  speechOut?.cancel();
  pendingUserTexts = [];
  liveSocket?.close();
  liveSocket = null;
  captureSocket?.close();
  captureSocket = null;
  motion?.stop();
  motion = null;
  camera?.stop();
  camera = null;
  await releaseWakeLock();
  ui.setRecording(null);
}

typedFallback.addEventListener("submit", (event) => {
  event.preventDefault();
  sendUserText(typedMessage.value);
  typedMessage.value = "";
});
interruptButton.addEventListener("click", () => speechOut?.cancel());
retryMicButton.addEventListener("click", async () => {
  if (!speechIn) setupSpeech();
  await requestMicAndListen();
});
ui.startButton.addEventListener("click", startSweep);
ui.stopButton.addEventListener("click", async () => {
  await stopSweep();
  ui.setMessage("Capture stopped. Frames are saved in the sweep folder.");
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && active) requestWakeLock();
  if (document.visibilityState !== "visible") releaseWakeLock();
});
