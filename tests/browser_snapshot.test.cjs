const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../browser_extension/production/service-worker.js"), "utf8");
const turn = () => new Promise(resolve => setImmediate(resolve));

async function runtime() {
  const sent = [];
  let windowId = 1;
  let query = async () => [{ id: 1, url: "https://github.com/" }];
  const event = () => ({ addListener() {} });
  const native = { postMessage: message => sent.push(message), onMessage: event(), onDisconnect: event() };
  const chrome = {
    storage: { local: { get: async () => ({}), set: async () => {} } },
    runtime: { connectNative: () => native, getManifest: () => ({ version: "test" }) },
    windows: { getLastFocused: async () => ({ id: windowId, focused: true }), onFocusChanged: event() },
    tabs: { query: options => query(options), onActivated: event(), onUpdated: event() },
    webNavigation: { onCommitted: event() }
  };
  const context = vm.createContext({ chrome, navigator: { userAgent: "Chrome" },
    crypto: { randomUUID: () => "test-id" }, URL, setTimeout });
  vm.runInContext(source, context);
  await turn();
  return { context, sent, setWindow: id => { windowId = id; }, setQuery: value => { query = value; } };
}

test("late old-window samples cannot overwrite a newer snapshot", async () => {
  const app = await runtime();
  let release;
  app.setQuery(() => new Promise(resolve => { release = resolve; }));
  const old = app.context.sendSnapshot();
  await turn();
  app.setWindow(2);
  app.setQuery(async () => [{ id: 2, url: "https://github.com/" }]);
  await app.context.sendSnapshot();
  release([{ id: 1, url: "https://youtube.com/" }]);
  await old;
  const snapshots = app.sent.filter(m => m.type === "browser_context_snapshot");
  assert.equal(snapshots.length, 1);
  assert.equal(snapshots[0].payload.domain, "github.com");
  assert.equal(snapshots[0].payload.windowId, 2);
});

test("a newer tab event preserves the outstanding request correlation", async () => {
  const app = await runtime();
  let release;
  app.setQuery(() => new Promise(resolve => { release = resolve; }));
  const old = app.context.sendSnapshot({ snapshotRequestId: "request-3", foregroundEpoch: 3 });
  await turn();
  app.setQuery(async () => [{ id: 2, url: "https://github.com/" }]);
  await app.context.sendSnapshot();
  release([{ id: 1, url: "https://youtube.com/" }]);
  await old;
  const snapshots = app.sent.filter(m => m.type === "browser_context_snapshot");
  assert.equal(snapshots.length, 1);
  assert.equal(snapshots[0].payload.snapshotRequestId, "request-3");
  assert.equal(snapshots[0].payload.foregroundEpoch, 3);
});

test("internal pages report an empty domain while preserving real window focus", async () => {
  const app = await runtime();
  app.setQuery(async () => [{ id: 1, url: "chrome://settings/" }]);
  await app.context.sendSnapshot();
  const snapshot = app.sent.find(m => m.type === "browser_context_snapshot");
  assert.equal(snapshot.payload.domain, null);
  assert.equal(snapshot.payload.windowFocused, true);
});
