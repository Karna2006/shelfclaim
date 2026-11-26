export function createSpeechIn({ onFinal, onUnsupported, onBlocked = () => {}, onInterim = () => {}, onStatus = () => {}, onEvent = () => {}, forceFinalAfterMs = 1200 }) {
  if (/SamsungBrowser/i.test(navigator.userAgent)) {
    onUnsupported?.("samsung-internet");
    onStatus("unsupported");
    onEvent("unsupported browser", "Samsung Internet");
    return { supported: false, reason: "samsung-internet", start() {}, pause() {}, resume() {}, stop() {} };
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    onUnsupported?.("speech-recognition-unavailable");
    onStatus("unsupported");
    onEvent("unsupported browser", "SpeechRecognition unavailable");
    return { supported: false, reason: "speech-recognition-unavailable", start() {}, pause() {}, resume() {}, stop() {} };
  }
  const recognition = new Recognition();
  recognition.lang = "en-IN";
  recognition.continuous = true;
  recognition.interimResults = true;
  let wanted = false;
  let paused = false;
  let lastErrorCode = "";
  let restartTimer = null;
  let forceFinalTimer = null;
  let interimText = "";
  let lastForcedText = "";
  let lastForcedAt = 0;
  function clearInterim() {
    clearTimeout(forceFinalTimer);
    forceFinalTimer = null;
    interimText = "";
  }
  function scheduleForceFinal(text) {
    if (!text) return;
    if (text === lastForcedText && Date.now() - lastForcedAt < 5000) return;
    if (text === interimText && forceFinalTimer) return;
    interimText = text;
    clearTimeout(forceFinalTimer);
    forceFinalTimer = window.setTimeout(() => {
      forceFinalTimer = null;
      const forced = interimText.trim();
      interimText = "";
      if (!forced) return;
      lastForcedText = forced;
      lastForcedAt = Date.now();
      onEvent("forced-final", `interim stable for ${forceFinalAfterMs}ms`);
      onFinal(forced, true);
    }, forceFinalAfterMs);
  }
  const startNative = () => {
    if (!wanted || paused) return;
    try { recognition.start(); } catch (error) {
      if (error.name !== "InvalidStateError") {
        onStatus(`error:${error.name || "start-failed"}`);
        onEvent("start error", error.name || "unknown");
      }
    }
  };
  recognition.onstart = () => {
    lastErrorCode = "";
    if (!paused) onStatus("listening");
    onEvent("onstart", "recognition started");
  };
  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const text = result[0]?.transcript?.trim();
      if (!text) continue;
      if (result.isFinal) {
        clearInterim();
        if (text === lastForcedText && Date.now() - lastForcedAt < 5000) {
          onEvent("late-final-ignored", text);
          continue;
        }
        onEvent("final", text);
        onFinal(text, false);
      } else {
        onEvent("interim", text);
        onInterim(text);
        scheduleForceFinal(text);
      }
    }
  };
  const scheduleRestart = () => {
    if (!wanted || paused) return;
    clearTimeout(restartTimer);
    restartTimer = window.setTimeout(() => {
      onEvent("restart", "automatic recognition restart");
      startNative();
    }, 150);
  };
  recognition.onend = () => {
    onEvent("onend", paused ? "paused" : "recognition ended");
    if (paused) onStatus("paused (agent speaking)");
    else if (wanted) onStatus(`error:${lastErrorCode || "ended"}`);
    scheduleRestart();
  };
  recognition.onerror = (event) => {
    onEvent("onerror", event.error || "unknown");
    if (event.error === "not-allowed") {
      wanted = false;
      onStatus("blocked");
      onBlocked();
      return;
    }
    if (event.error !== "aborted") {
      lastErrorCode = event.error || "unknown";
      onStatus(`error:${lastErrorCode}`);
    }
    scheduleRestart();
  };
  return {
    supported: true,
    start() { wanted = true; paused = false; onEvent("start requested", "SpeechRecognition.start()"); startNative(); },
    pause() { paused = true; clearTimeout(restartTimer); onStatus("paused (agent speaking)"); onEvent("paused", "agent speaking"); try { recognition.abort(); } catch {} },
    resume() { if (!wanted) return; paused = false; onEvent("resume requested", "speech ended"); startNative(); },
    setForceFinalAfter(ms) { forceFinalAfterMs = Math.max(100, ms); },
    stop() { wanted = false; paused = true; clearTimeout(restartTimer); clearInterim(); onEvent("stopped", "sweep ended"); try { recognition.abort(); } catch {} },
  };
}

export function createSpeechOut({ onSpeakingChange = () => {}, pauseInput = () => {}, resumeInput = () => {}, earphonesMode = true } = {}) {
  const synth = window.speechSynthesis;
  const queue = [];
  let active = false;
  let current = null;
  let serial = 0;
  let resumeTimer = null;
  function voices() { return synth?.getVoices?.() ?? []; }
  function chooseVoice() {
    const available = voices();
    return available.find((voice) => /^en-IN$/i.test(voice.lang))
      ?? available.find((voice) => /^en-GB$/i.test(voice.lang))
      ?? available.find((voice) => /^en/i.test(voice.lang))
      ?? null;
  }
  function pump() {
    if (!synth) {
      queue.length = 0;
      onSpeakingChange(false, current?.kind ?? null);
      return;
    }
    if (active || queue.length === 0) {
      if (!active && queue.length === 0) {
        onSpeakingChange(false, null);
        clearTimeout(resumeTimer);
        resumeTimer = window.setTimeout(() => {
          if (!earphonesMode && !active && queue.length === 0) resumeInput();
        }, 300);
      }
      return;
    }
    queue.sort((a, b) => b.priority - a.priority || a.order - b.order);
    const item = queue.shift();
    active = true;
    current = item;
    const token = ++serial;
    if (!earphonesMode) pauseInput();
    onSpeakingChange(true, item.kind);
    const utterance = new SpeechSynthesisUtterance(item.text);
    utterance.voice = chooseVoice();
    utterance.lang = utterance.voice?.lang || "en-IN";
    const finish = () => {
      if (token !== serial) return;
      active = false;
      current = null;
      onSpeakingChange(false, item.kind);
      pump();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    synth.speak(utterance);
  }
  function enqueue(text, priority = 0, kind = "cue") {
    if (!text?.trim()) return;
    clearTimeout(resumeTimer);
    const item = { text: text.trim(), priority, kind, order: Date.now() };
    if (kind === "cue" && active && current?.kind === "agent") return;
    if (kind === "cue" && active && current?.kind === "cue" && priority > current.priority) {
      active = false;
      current = null;
      serial += 1;
      synth.cancel();
    }
    queue.push(item);
    pump();
  }
  return {
    setEarphonesMode(enabled) { earphonesMode = Boolean(enabled); },
    speak(text) {
      for (let index = queue.length - 1; index >= 0; index -= 1) {
        if (queue[index].kind === "cue") queue.splice(index, 1);
      }
      if (active && current?.kind === "cue") {
        active = false;
        current = null;
        serial += 1;
        synth?.cancel();
      }
      enqueue(text, 0, "agent");
    },
    speakCue(text, priority = 10) { enqueue(text, priority, "cue"); },
    cancel() {
      queue.length = 0;
      clearTimeout(resumeTimer);
      const kind = current?.kind ?? null;
      serial += 1;
      active = false;
      current = null;
      synth?.cancel();
      onSpeakingChange(false, kind);
      resumeInput();
    },
    isSpeaking() { return active || Boolean(synth?.speaking); },
  };
}
