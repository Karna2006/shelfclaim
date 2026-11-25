export async function openCamera(video) {
  const preferred = {
    audio: false,
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      frameRate: { ideal: 30 },
    },
  };
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(preferred);
  } catch (error) {
    if (!new Set(["OverconstrainedError", "NotFoundError"]).has(error.name)) throw error;
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
      },
    });
  }

  const track = stream.getVideoTracks()[0];
  await requestContinuousCameraControls(track);
  video.srcObject = stream;
  await video.play();
  return {
    stream,
    settings: track.getSettings(),
    async captureJpeg(canvas, quality) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
      return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("JPEG capture failed"))), "image/jpeg", quality);
      });
    },
    stop() {
      stream.getTracks().forEach((trackToStop) => trackToStop.stop());
      video.srcObject = null;
    },
  };
}

async function requestContinuousCameraControls(track) {
  if (typeof track.getCapabilities !== "function") {
    console.info("Camera track does not expose capabilities; keeping automatic defaults.");
    return;
  }

  let capabilities;
  try {
    capabilities = track.getCapabilities();
  } catch (error) {
    console.warn("Could not read camera capabilities; keeping automatic defaults.", error);
    return;
  }
  console.info("Camera track capabilities:", capabilities);

  const advanced = [];
  if (capabilities.focusMode?.includes("continuous")) {
    advanced.push({ focusMode: "continuous" });
  }
  if (capabilities.exposureMode?.includes("continuous")) {
    advanced.push({ exposureMode: "continuous" });
  }
  if (!advanced.length || typeof track.applyConstraints !== "function") return;

  try {
    await track.applyConstraints({ advanced });
    console.info("Requested continuous camera focus and exposure where supported.");
  } catch (error) {
    console.warn("Camera did not accept continuous focus/exposure constraints.", error);
  }
}
