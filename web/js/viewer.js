const sweepId = document.documentElement.dataset.sweepId;
const connection = document.querySelector("#connection");
const frame = document.querySelector("#live-frame");
const emptyFrame = document.querySelector("#frame-empty");
const qcPill = document.querySelector("#qc-pill");
const cardsSeen = document.querySelector("#cards-seen");
const captions = document.querySelector("#captions");
const speakToggle = document.querySelector("#speak-toggle");
const inventoryPlaceholder = document.querySelector("#inventory-placeholder");
const inventoryContent = document.querySelector("#inventory-content");
const bookRows = document.querySelector("#book-rows");
const itemsList = document.querySelector("#items-list");
const pipelineLabel = document.querySelector("#pipeline-label");
const pipelineProgress = document.querySelector("#pipeline-progress");
const reportLink = document.querySelector("#report-link");
const speakQueue = [];
let speaking = false;

document.querySelector("#sweep-label").textContent = sweepId || "No sweep selected";

function caption(speaker, text, shouldSpeak = false) {
  if (!text) return;
  const row = document.createElement("li");
  row.dataset.speaker = speaker;
  const label = document.createElement("span");
  label.className = "speaker";
  label.textContent = speaker === "user" ? "You said" : speaker === "cue" ? "Capture cue" : "Agent";
  row.append(label, document.createTextNode(text));
  captions.append(row);
  captions.scrollTop = captions.scrollHeight;
  if (shouldSpeak && speakToggle.checked) enqueueSpeech(text);
}

function enqueueSpeech(text) {
  speakQueue.push(text);
  if (!speaking) speakNext();
}

function speakNext() {
  const text = speakQueue.shift();
  if (!text || !window.speechSynthesis) return;
  speaking = true;
  const utterance = new SpeechSynthesisUtterance(text);
  const voices = speechSynthesis.getVoices();
  utterance.voice = voices.find((voice) => /^en-IN$/i.test(voice.lang))
    || voices.find((voice) => /^en-GB$/i.test(voice.lang))
    || null;
  utterance.lang = utterance.voice?.lang || "en-IN";
  utterance.onend = utterance.onerror = () => { speaking = false; speakNext(); };
  speechSynthesis.speak(utterance);
}

function renderFrame(message) {
  frame.src = `data:image/jpeg;base64,${message.jpeg}`;
  frame.hidden = false;
  frame.style.display = "block";
  emptyFrame.hidden = true;
}

function renderQc(message) {
  const verdict = String(message.verdict || "unknown").replaceAll("_", " ").toUpperCase();
  const blur = Number.isFinite(message.blur) ? Math.round(message.blur) : "—";
  const speed = Number.isFinite(message.speed_dps) ? Math.round(message.speed_dps) : "—";
  qcPill.textContent = `${verdict} · blur ${blur} · ${speed} dps`;
  qcPill.dataset.state = message.verdict === "ok" ? "ok"
    : ["fast", "blurry"].includes(message.verdict) ? "error" : "warn";
  const ids = [...new Set(message.cards_seen || message.markers || [])].sort((a, b) => a - b);
  cardsSeen.textContent = ids.length ? `Cards seen: ${ids.join(", ")}` : "Cards seen: none";
}

function renderInventory(message) {
  inventoryPlaceholder.hidden = true;
  inventoryContent.hidden = false;
  bookRows.replaceChildren();
  itemsList.replaceChildren();
  for (const row of message.rows || []) {
    const item = document.createElement("li");
    item.textContent = `${row.row}: ${row.count ?? "—"} books`;
    bookRows.append(item);
  }
  for (const row of message.items || []) {
    const item = document.createElement("li");
    item.textContent = row.description ? `${row.category}: ${row.description}` : row.category;
    itemsList.append(item);
  }
}

function renderProgress(message) {
  const total = Number(message.total) || 10;
  const current = Number(message.current) || 0;
  pipelineProgress.max = total;
  pipelineProgress.value = current;
  pipelineLabel.textContent = `${message.stage || "Pipeline"} · ${message.state || "working"} (${current}/${total})`;
}

function showReport(url) {
  if (!url) return;
  reportLink.href = url;
  reportLink.hidden = false;
  pipelineLabel.textContent = "Report ready";
  pipelineProgress.value = pipelineProgress.max;
}

function handle(message, fromSnapshot = false) {
  if (message.type === "snapshot") {
    if (message.frame) renderFrame(message.frame);
    if (message.qc) renderQc(message.qc);
    if (message.inventory) renderInventory(message.inventory);
    (message.captions || []).forEach((row) => caption(row.speaker, row.text));
    if (message.progress) renderProgress(message.progress);
    if (message.report_url) showReport(message.report_url);
    return;
  }
  if (message.type === "frame") renderFrame(message);
  if (message.type === "qc") renderQc(message);
  if (message.type === "caption") caption(message.speaker, message.text, !fromSnapshot);
  if (message.type === "inventory") renderInventory(message);
  if (message.type === "pipeline_progress") renderProgress(message);
  if (message.type === "packet_ready") showReport(message.report_url);
}

if (!sweepId) {
  connection.textContent = "No sweep yet";
  connection.dataset.state = "disconnected";
} else {
  const endpoint = new URL(`/ws/viewer/${encodeURIComponent(sweepId)}`, location.href);
  endpoint.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(endpoint);
  socket.onopen = () => { connection.textContent = "Connected"; connection.dataset.state = "connected"; };
  socket.onclose = () => { connection.textContent = "Disconnected"; connection.dataset.state = "disconnected"; };
  socket.onerror = () => { connection.textContent = "Viewer connection error"; connection.dataset.state = "disconnected"; };
  socket.onmessage = ({ data }) => {
    try { handle(JSON.parse(data)); } catch { /* Ignore malformed viewer events. */ }
  };
}

speakToggle.addEventListener("change", () => {
  if (!speakToggle.checked) {
    speakQueue.length = 0;
    speechSynthesis?.cancel();
    speaking = false;
  }
});
