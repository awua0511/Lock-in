async function refresh() {
  const state = await chrome.runtime.sendMessage({ type: "get_state" });
  document.querySelector("#status").textContent = state.status || "unknown";
  document.querySelector("#browser").textContent = state.browser || "—";
  document.querySelector("#identity").textContent = state.clientInstanceId || "—";
  document.querySelector("#event").textContent = state.lastEvent
    ? JSON.stringify(state.lastEvent)
    : "—";
  document.querySelector("#history").textContent = state.eventHistory?.length
    ? state.eventHistory.map((event) => JSON.stringify(event)).join("\n")
    : "—";
}

for (const button of document.querySelectorAll("button[data-command]")) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await chrome.runtime.sendMessage({ type: button.dataset.command });
      await new Promise((resolve) => setTimeout(resolve, 250));
      await refresh();
    } finally {
      button.disabled = false;
    }
  });
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "state_changed") refresh();
});

refresh();
