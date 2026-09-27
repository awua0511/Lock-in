const HOST_NAME = "com.lockin.desktop";
const PROTOCOL_VERSION = 1;
const RECONNECT_MAX_MS = 10000;

let port = null;
let clientInstanceId = null;
let sequence = 0;
let reconnectAttempt = 0;
let reconnectTimer = null;

async function initialize() {
  const stored = await chrome.storage.local.get(["clientInstanceId", "nextSequence"]);
  clientInstanceId = stored.clientInstanceId || crypto.randomUUID();
  sequence = Number.isInteger(stored.nextSequence) ? stored.nextSequence : 0;
  await chrome.storage.local.set({ clientInstanceId, nextSequence: sequence });
}

function browserKind() {
  return navigator.userAgent.includes("Edg/") ? "edge" : "chrome";
}

async function nextSequence() {
  const current = sequence;
  sequence += 1;
  await chrome.storage.local.set({ nextSequence: sequence });
  return current;
}

function post(type, seq, payload = {}) {
  if (!port) return;
  port.postMessage({
    protocolVersion: PROTOCOL_VERSION,
    messageId: crypto.randomUUID(),
    type,
    clientInstanceId,
    browser: browserKind(),
    sequence: seq,
    payload
  });
}

async function sendSnapshot(correlation = {}) {
  if (!port) return;
  try {
    const win = await chrome.windows.getLastFocused({ populate: false });
    const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
    const tab = tabs[0];
    const pageUrl = tab?.url ? new URL(tab.url) : null;
    const hostname = pageUrl && ["http:", "https:"].includes(pageUrl.protocol)
      ? pageUrl.hostname
      : null;
    const seq = await nextSequence();
    post("browser_context_snapshot", seq, {
      windowId: Number.isInteger(win.id) ? win.id : -1,
      tabId: Number.isInteger(tab?.id) ? tab.id : -1,
      domain: hostname || null,
      windowFocused: Boolean(win.focused && tab && hostname),
      snapshotRequestId: correlation.snapshotRequestId || null,
      foregroundEpoch: Number.isInteger(correlation.foregroundEpoch)
        ? correlation.foregroundEpoch
        : null
    });
  } catch (_error) {
    // An unavailable or internal page remains unresolved; never reuse a prior host.
    const seq = await nextSequence();
    post("browser_context_snapshot", seq, {
      windowId: -1,
      tabId: -1,
      domain: null,
      windowFocused: false,
      snapshotRequestId: correlation.snapshotRequestId || null,
      foregroundEpoch: Number.isInteger(correlation.foregroundEpoch)
        ? correlation.foregroundEpoch
        : null
    });
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(250 * (2 ** reconnectAttempt), RECONNECT_MAX_MS);
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (_error) {
    scheduleReconnect();
    return;
  }
  post("hello", 0, { extensionVersion: chrome.runtime.getManifest().version });
  port.onMessage.addListener((message) => {
    if (message.type === "hello_ack" && message.status === "accepted") {
      reconnectAttempt = 0;
      sendSnapshot();
    } else if (message.type === "request_snapshot") {
      sendSnapshot(message.payload || {});
    }
  });
  port.onDisconnect.addListener(() => {
    port = null;
    scheduleReconnect();
  });
}

function publishCurrent() {
  sendSnapshot();
}

chrome.tabs.onActivated.addListener(publishCurrent);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.url || changeInfo.status === "complete") publishCurrent();
});
chrome.windows.onFocusChanged.addListener(publishCurrent);
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId === 0) publishCurrent();
});

initialize().then(connect);
