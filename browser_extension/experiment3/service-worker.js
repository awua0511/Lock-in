const HOST_NAME = "com.lockin.experiment3";
const PROTOCOL_VERSION = 1;
const RESPONSE_TIMEOUT_MS = 2000;
const MAX_RECONNECT_MS = 10000;

let port = null;
let reconnectAttempt = 0;
let reconnectTimer = null;
let clientInstanceId = null;
let nextSequence = 1;
let pending = new Map();
let status = "starting";
let lastEvent = null;
let eventHistory = [];

function browserKind() {
  return navigator.userAgent.includes("Edg/") ? "edge" : "chrome";
}

async function initializeIdentity() {
  const stored = await chrome.storage.local.get(["clientInstanceId", "nextSequence"]);
  clientInstanceId = stored.clientInstanceId || crypto.randomUUID();
  nextSequence = Number.isInteger(stored.nextSequence) ? stored.nextSequence : 1;
  await chrome.storage.local.set({ clientInstanceId, nextSequence });
}

function record(event, detail = {}) {
  lastEvent = { event, at: new Date().toISOString(), ...detail };
  eventHistory.push(lastEvent);
  eventHistory = eventHistory.slice(-20);
  chrome.storage.local.set({ experiment3LastEvent: lastEvent, experiment3EventHistory: eventHistory });
  chrome.runtime.sendMessage({ type: "state_changed" }).catch(() => {});
}

function envelope(type, sequence, payload = {}) {
  return {
    protocolVersion: PROTOCOL_VERSION,
    messageId: crypto.randomUUID(),
    type,
    clientInstanceId,
    browser: browserKind(),
    sequence,
    payload
  };
}

function send(message, timeoutMs = RESPONSE_TIMEOUT_MS) {
  if (!port) {
    throw new Error("Native Messaging is not connected");
  }
  port.postMessage(message);
  const timeout = setTimeout(() => {
    pending.delete(message.messageId);
    record("timeout", { messageId: message.messageId, sequence: message.sequence });
  }, timeoutMs);
  pending.set(message.messageId, timeout);
  record("sent", { type: message.type, sequence: message.sequence });
}

async function allocateSequence() {
  const value = nextSequence;
  nextSequence += 1;
  await chrome.storage.local.set({ nextSequence });
  return value;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(250 * (2 ** reconnectAttempt), MAX_RECONNECT_MS);
  reconnectAttempt += 1;
  status = "reconnecting";
  record("reconnect_scheduled", { delayMs: delay });
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function connect() {
  if (port) return;
  status = "connecting";
  record("connecting", { browser: browserKind() });
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (error) {
    port = null;
    record("connect_failed", { error: String(error) });
    scheduleReconnect();
    return;
  }

  port.onMessage.addListener((message) => {
    const timeout = pending.get(message.replyTo);
    if (timeout) {
      clearTimeout(timeout);
      pending.delete(message.replyTo);
    }
    if (message.type === "hello_ack" && message.status === "accepted") {
      status = "connected";
      reconnectAttempt = 0;
    }
    record("received", {
      type: message.type,
      status: message.status,
      sequence: message.sequence,
      replyTo: message.replyTo
    });
  });

  port.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message || "Native Host disconnected";
    port = null;
    status = "disconnected";
    for (const timeout of pending.values()) clearTimeout(timeout);
    pending.clear();
    record("disconnected", { error });
    scheduleReconnect();
  });

  send(envelope("hello", 0, { extensionVersion: chrome.runtime.getManifest().version }));
}

async function sendPing(payload = {}, timeoutMs = RESPONSE_TIMEOUT_MS) {
  const sequence = await allocateSequence();
  send(envelope("ping", sequence, payload), timeoutMs);
  return sequence;
}

async function runDuplicateTest() {
  const sequence = await allocateSequence();
  send(envelope("ping", sequence, { echo: "duplicate-first" }));
  send(envelope("ping", sequence, { echo: "duplicate-second" }));
}

async function runOutOfOrderTest() {
  const sequence = await allocateSequence();
  send(envelope("ping", sequence, { echo: "ordered-new" }));
  const older = Math.max(0, sequence - 1);
  send(envelope("ping", older, { echo: "ordered-old" }));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.type === "get_state") {
      sendResponse({ status, clientInstanceId, browser: browserKind(), lastEvent, eventHistory });
    } else if (message.type === "ping") {
      await sendPing({ echo: "popup" });
      sendResponse({ ok: true });
    } else if (message.type === "timeout_test") {
      await sendPing({ echo: "timeout", testDelayMs: 3000 }, 1000);
      sendResponse({ ok: true });
    } else if (message.type === "duplicate_test") {
      await runDuplicateTest();
      sendResponse({ ok: true });
    } else if (message.type === "out_of_order_test") {
      await runOutOfOrderTest();
      sendResponse({ ok: true });
    } else if (message.type === "reconnect") {
      if (port) port.disconnect();
      sendResponse({ ok: true });
    } else if (message.type === "host_crash_test") {
      send(envelope("test_host_crash", 0));
      sendResponse({ ok: true });
    }
  })().catch((error) => sendResponse({ ok: false, error: String(error) }));
  return true;
});

chrome.storage.local.get(["experiment3EventHistory"]).then((stored) => {
  eventHistory = Array.isArray(stored.experiment3EventHistory)
    ? stored.experiment3EventHistory.slice(-20)
    : [];
  return initializeIdentity();
}).then(connect);
