import assert from "node:assert/strict";
import { test } from "node:test";
import { createSpeechIn, createSpeechOut } from "../../web/js/speech.js";

class FakeUtterance {
  constructor(text) { this.text = text; }
}

class FakeSpeechSynthesis {
  constructor() {
    this.spoken = [];
    this.current = null;
    this.speaking = false;
    this.cancelCount = 0;
  }
  getVoices() { return []; }
  speak(utterance) {
    this.spoken.push(utterance.text);
    this.current = utterance;
    this.speaking = true;
  }
  finishCurrent() {
    const utterance = this.current;
    this.current = null;
    this.speaking = false;
    utterance?.onend?.();
  }
  cancel() {
    this.cancelCount += 1;
    this.current = null;
    this.speaking = false;
  }
}

function speechOutHarness(options = {}) {
  const synth = new FakeSpeechSynthesis();
  globalThis.window = { speechSynthesis: synth, setTimeout, clearTimeout };
  globalThis.SpeechSynthesisUtterance = FakeUtterance;
  const output = createSpeechOut({ earphonesMode: true, ...options });
  return { synth, output };
}

test("stable mixed cue and answer is forced once within 1.5 seconds", async () => {
  globalThis.window = globalThis;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { userAgent: "Chrome" },
  });

  class FakeRecognition {
    constructor() { FakeRecognition.lastInstance = this; }
    start() {}
    abort() {}
  }

  globalThis.webkitSpeechRecognition = FakeRecognition;
  const finals = [];
  const speech = createSpeechIn({
    forceFinalAfterMs: 1200,
    onFinal: (text, forced) => finals.push({ text, forced }),
  });
  speech.start();
  const native = FakeRecognition.lastInstance;
  const interim = (text) => ({
    resultIndex: 0,
    results: [{ 0: { transcript: text }, isFinal: false }],
  });

  native.onresult(interim("Hold the phone steadily"));
  await new Promise((resolve) => setTimeout(resolve, 500));
  native.onresult(interim("Hold the phone steadily yes, I'm from India"));
  const stableAt = performance.now();
  await new Promise((resolve) => setTimeout(resolve, 1300));

  assert.deepEqual(finals, [
    { text: "Hold the phone steadily yes, I'm from India", forced: true },
  ]);
  assert.ok(performance.now() - stableAt < 1500);
  native.onresult(interim("Hold the phone steadily yes, I'm from India"));
  await new Promise((resolve) => setTimeout(resolve, 1300));
  assert.equal(finals.length, 1);
  native.onresult({
    resultIndex: 0,
    results: [{ 0: { transcript: "Hold the phone steadily yes, I'm from India" }, isFinal: true }],
  });
  assert.equal(finals.length, 1);
  speech.stop();
});

test("capture cue waits for the current sentence and then plays", () => {
  const { synth, output } = speechOutHarness();
  output.speak("First sentence. Second sentence.");
  assert.equal(output.speakCue("Move more slowly.", 10, "TOO_FAST"), true);
  assert.deepEqual(synth.spoken, ["First sentence."]);

  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["First sentence.", "Move more slowly."]);
  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["First sentence.", "Move more slowly.", "Second sentence."]);
  output.cancel();
});

test("duplicate cue type is not queued twice", () => {
  const { synth, output } = speechOutHarness();
  output.speak("Current sentence.");
  assert.equal(output.speakCue("First cue.", 10, "TOO_FAST"), true);
  assert.equal(output.speakCue("Duplicate cue.", 10, "TOO_FAST"), false);
  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["Current sentence.", "First cue."]);
  output.cancel();
});

test("interim noise and a one-word final do not cancel speech", () => {
  const { synth, output } = speechOutHarness();
  class FakeRecognition {
    constructor() { FakeRecognition.lastInstance = this; }
    start() {}
    abort() {}
  }
  globalThis.webkitSpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = FakeRecognition;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { userAgent: "Chrome" },
  });
  const input = createSpeechIn({
    forceFinalAfterMs: 5000,
    onInterim: () => {},
    onFinal: (text) => output.requestBargeIn(text),
  });
  output.speak("Please move slowly.");
  input.start();
  const recognition = FakeRecognition.lastInstance;
  recognition.onresult({
    resultIndex: 0,
    results: [{ 0: { transcript: "shaking noise" }, isFinal: false }],
  });
  assert.equal(synth.cancelCount, 0);
  recognition.onresult({
    resultIndex: 0,
    results: [{ 0: { transcript: "yes" }, isFinal: true }],
  });
  assert.equal(synth.cancelCount, 0);
  assert.equal(synth.current.text, "Please move slowly.");
  input.stop();
  output.cancel();
});

test("two-word final lets the current sentence finish and drops remaining sentences", () => {
  const { synth, output } = speechOutHarness();
  output.speak("First sentence. Second sentence.");
  assert.equal(output.requestBargeIn("can you see it"), true);
  assert.equal(synth.cancelCount, 0);
  output.speak("Yes, I can see it.");

  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["First sentence.", "Yes, I can see it."]);
  output.cancel();
});

test("stale queued cue is dropped after four seconds", () => {
  let clock = 100;
  const { synth, output } = speechOutHarness({ now: () => clock, cueMaxAgeMs: 4000 });
  output.speak("Current sentence.");
  output.speakCue("Old cue.", 10, "TOO_FAST");
  clock += 4001;

  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["Current sentence."]);
  assert.equal(output.isSpeaking(), false);
  output.cancel();
});

test("queued cue is dropped when its condition clears", () => {
  let condition = true;
  const { synth, output } = speechOutHarness();
  output.speak("Current sentence.");
  output.speakCue("Old condition.", 10, "TOO_FAST", () => condition);
  condition = false;

  synth.finishCurrent();
  assert.deepEqual(synth.spoken, ["Current sentence."]);
  output.cancel();
});
