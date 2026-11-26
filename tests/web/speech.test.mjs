import assert from "node:assert/strict";
import { test } from "node:test";
import { createSpeechIn } from "../../web/js/speech.js";

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
