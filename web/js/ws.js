export function createCaptureSocket(sweepId, config, callbacks = {}) {
  const endpoint = new URL("/ws/capture", window.location.href);
  endpoint.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  endpoint.searchParams.set("sweep_id", sweepId);

  let socket = null;
  let disposed = false;
  let retryTimer = null;
  let retryAttempt = 0;
  let nextSequence = 0;
  const pending = [];

  function connect() {
    if (disposed) return;
    callbacks.onConnection?.("connecting");
    callbacks.onDebug?.("connecting");
    socket = new WebSocket(endpoint);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      retryAttempt = 0;
      callbacks.onConnection?.("connected");
      callbacks.onDebug?.("connected");
      flush();
    };
    socket.onmessage = ({ data }) => {
      let message;
      try { message = JSON.parse(data); } catch { return; }
      if (message.type === "error") callbacks.onDebug?.("received error");
      if (message.type === "qc") callbacks.onQc?.(message);
      if (message.type === "ack") {
        const index = pending.findIndex((frame) => frame.seq === message.seq);
        if (index >= 0) pending.splice(index, 1);
        flush();
      }
      if (message.type === "error") callbacks.onMessage?.(message.message);
    };
    socket.onerror = () => { callbacks.onConnection?.("disconnected"); callbacks.onDebug?.("error"); };
    socket.onclose = () => {
      pending.forEach((frame) => { frame.sent = false; });
      callbacks.onConnection?.("disconnected");
      callbacks.onDebug?.("closed; reconnect scheduled");
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (disposed || retryTimer !== null) return;
    const delay = Math.min(config.reconnect_max_ms, config.reconnect_initial_ms * (2 ** retryAttempt));
    retryAttempt += 1;
    retryTimer = window.setTimeout(() => {
      retryTimer = null;
      connect();
    }, delay);
  }

  function flush() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    let inFlight = pending.filter((frame) => frame.sent).length;
    for (const frame of pending) {
      if (inFlight >= config.max_inflight_frames) break;
      if (frame.sent) continue;
      socket.send(frame.packet);
      frame.sent = true;
      inFlight += 1;
    }
  }

  connect();
  return {
    async enqueueFrame(blob, metadata) {
      const seq = nextSequence++;
      const header = {
        seq,
        t_ms: metadata.t_ms,
        w: metadata.w,
        h: metadata.h,
        motion: metadata.motion,
      };
      const headerBytes = new TextEncoder().encode(JSON.stringify(header));
      const jpegBytes = new Uint8Array(await blob.arrayBuffer());
      const packet = new Uint8Array(4 + headerBytes.byteLength + jpegBytes.byteLength);
      // DataView's false flag writes the unsigned header length in network byte order.
      new DataView(packet.buffer).setUint32(0, headerBytes.byteLength, false);
      packet.set(headerBytes, 4);
      packet.set(jpegBytes, 4 + headerBytes.byteLength);
      pending.push({ seq, packet, sent: false });
      while (pending.length > config.max_buffered_frames) {
        const dropped = pending.shift();
        callbacks.onMessage?.(`Dropped unsent frame ${dropped.seq}; the capture buffer is full.`);
      }
      flush();
      return seq;
    },
    sendMotion(sample, tMs) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: "motion_only",
          t_ms: tMs,
          gyro_dps: sample.gyro_dps,
          gravity: sample.gravity,
        }));
      }
    },
    close() {
      disposed = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      retryTimer = null;
      socket?.close();
    },
  };
}
