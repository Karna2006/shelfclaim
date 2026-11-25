export async function openCamera(video) {
  const preferred = {
    audio: false,
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
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
      },
    });
  }

  video.srcObject = stream;
  await video.play();
  const track = stream.getVideoTracks()[0];
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
