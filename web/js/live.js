export function createLiveSocket(sweepId, callbacks = {}) {
  const endpoint = new URL(`/ws/live/${encodeURIComponent(sweepId)}`, window.location.href);
  endpoint.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(endpoint);
  const pendingTexts = [];
  function flushTexts() {
    while (socket.readyState === WebSocket.OPEN && pendingTexts.length) {
      socket.send(pendingTexts.shift());
      callbacks.onDebug?.("sent queued user_text");
    }
  }
  socket.onopen = () => {
    callbacks.onConnection?.("connected");
    callbacks.onDebug?.("connected");
    flushTexts();
  };
  socket.onclose = () => { callbacks.onConnection?.("disconnected"); callbacks.onDebug?.("closed"); };
  socket.onerror = () => { callbacks.onConnection?.("disconnected"); callbacks.onDebug?.("error"); };
  socket.onmessage = ({ data }) => {
    try {
      const message = JSON.parse(data);
      callbacks.onDebug?.(`received ${message.type || "unknown"}`);
      callbacks.onMessage?.(message);
    } catch { callbacks.onDebug?.("received malformed message"); }
  };
  return {
    ready: new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error("Agent connection failed")), { once: true });
    }),
    sendFinalText(text, tMs) {
      if (!text.trim()) return;
      const packet = JSON.stringify({ type: "user_text", text: text.trim(), t_ms: tMs });
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(packet);
        callbacks.onDebug?.("sent user_text");
      } else if (socket.readyState === WebSocket.CONNECTING) {
        pendingTexts.push(packet);
        callbacks.onDebug?.("queued user_text; live ws connecting");
      } else {
        callbacks.onDebug?.("dropped user_text; live ws unavailable");
      }
    },
    sendSpeechActivity(speaking) {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "speech_activity", speaking }));
    },
    async sendFrame(blob, tMs) {
      if (socket.readyState !== WebSocket.OPEN || !blob) return;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }
      socket.send(JSON.stringify({ type: "live_frame", data: btoa(binary), t_ms: tMs }));
    },
    close() {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "control", action: "stop" }));
      socket.close();
    },
  };
}
