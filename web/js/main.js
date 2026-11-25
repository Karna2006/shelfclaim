import { openCamera } from "./camera.js";
import { createMotionSampler } from "./motion.js";
import { createCaptureSocket } from "./ws.js";
import { createUi } from "./ui.js";

const ui = createUi();
const video = document.querySelector("#preview");
const canvas = document.querySelector("#capture-canvas");
let camera = null;
let motion = null;
let socket = null;
let active = false;
let captureStartedAt = 0;
let lastFrameAt = 0;
let frameTimer = null;
let motionTimer = null;
let recordingTimer = null;
let wakeLock = null;
let options = null;

async function requestWakeLock() {
  if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try { wakeLock = await navigator.wakeLock.request("screen"); } catch { wakeLock = null; }
}

async function releaseWakeLock() {
  if (wakeLock) await wakeLock.release();
  wakeLock = null;
}

async function startSweep() {
  ui.startButton.disabled = true;
  ui.setMessage("Requesting camera and motion access…");
  try {
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
    ui.setSpeedLimit(options.speed_max_dps);
    ui.setMotionGateLimit(options.frame_gyro_max_dps);
    ui.setSpeedSustainSeconds(options.speed_sustain_s);
    ui.resetCards();
    socket = createCaptureSocket(sweep.sweep_id, options, {
      onConnection: (state) => ui.setConnection(state),
      onQc: (qc) => ui.renderQc(qc),
      onMessage: (text) => ui.setMessage(text),
    });
    captureStartedAt = performance.now();
    lastFrameAt = captureStartedAt - options.frame_min_interval_ms;
    active = true;
    ui.setMessage(`Sweep ${sweep.sweep_id}: capturing ${width}×${height}. Move slowly along each shelf.`);
    recordingTimer = ui.setRecording(Date.now());
    await requestWakeLock();
    scheduleFrame();
    motionTimer = window.setInterval(() => {
      if (active) {
        socket.sendMotion(motion.snapshot(), Math.round(performance.now() - captureStartedAt));
      }
    }, 1000 / options.motion_sample_hz);
  } catch (error) {
    await stopSweep();
    ui.setMessage(error instanceof Error ? error.message : "Could not start the sweep.");
    ui.startButton.disabled = false;
  }
}

function scheduleFrame() {
  if (!active) return;
  frameTimer = window.setTimeout(captureFrame, 1000 / options.hires_fps);
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
      socket.enqueueFrame(blob, {
        t_ms: Math.round(performance.now() - captureStartedAt),
        w: canvas.width,
        h: canvas.height,
        motion: sample,
      });
      lastFrameAt = performance.now();
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
  frameTimer = motionTimer = recordingTimer = null;
  socket?.close();
  socket = null;
  motion?.stop();
  motion = null;
  camera?.stop();
  camera = null;
  await releaseWakeLock();
  ui.setRecording(null);
}

ui.startButton.addEventListener("click", startSweep);
ui.stopButton.addEventListener("click", async () => {
  await stopSweep();
  ui.setMessage("Capture stopped. Frames are saved in the sweep folder.");
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && active) requestWakeLock();
  if (document.visibilityState !== "visible") releaseWakeLock();
});
