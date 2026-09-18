# Experiment 3: Complete Browser Communication Chain

This experiment validates one bidirectional path and nothing else:

```text
Chrome / Edge extension
  → Native Messaging Host (browser framing)
  → per-user Windows Named Pipe
  → single-instance tray-process prototype
  → pong acknowledgement over the same route
```

It does not contain schedules, allowlists, prompts, SQLite, activity tracking, or any other product logic.

## Components

- `browser_extension/experiment3`: unpacked Manifest V3 extension shared by Chrome and Edge.
- `lock-in-native-host`: stateless, browser-launched stdio-to-Pipe relay.
- `lock-in-communication-tray`: single-instance Pipe server with no visible UI.
- `lock-in-register-native-host`: per-user Chrome/Edge manifest registration.
- `lock-in-communication-harness`: subprocess-level automated failure and concurrency checks.

Messages are UTF-8 JSON, limited to 64 KiB, and use protocol version 1. The Native Host assigns a random `connectionId`; the extension cannot choose it. Each browser profile persists a random `clientInstanceId` and monotonically increasing sequence in `chrome.storage.local`.

## Automated Validation

Refresh the editable installation after pulling or changing the project scripts:

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
```

Run all unit tests:

```powershell
.venv\Scripts\python -m pytest -v
```

Run the real subprocess and Named Pipe harness:

```powershell
.venv\Scripts\lock-in-communication-harness
```

The harness verifies:

- Two Hosts racing to launch an absent tray process reach the same server PID.
- Simulated Chrome and Edge clients connect concurrently.
- Two profiles per browser use independent Pipe connections and identities.
- A killed Host can reconnect without affecting other clients.
- A stopped tray process is relaunched and has a different PID.
- Duplicate and out-of-order sequences receive explicit statuses.
- A caller can time out while the deliberately delayed acknowledgement later arrives.

## Load the Unpacked Extension

The same directory is loaded separately in every browser profile:

```text
C:\Users\ASUS\Documents\ChatGPT\Lock-In\browser_extension\experiment3
```

For Chrome:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select the directory above.
4. Copy the extension ID shown on the extension card.

For Edge:

1. Open `edge://extensions`.
2. Enable **Developer mode** and allow extensions from other stores if requested.
3. Choose **Load unpacked** and select the same directory.
4. Copy the extension ID.

Repeat this in each profile. An unpacked extension loaded from the same path will commonly retain the same ID, but record every distinct ID that appears.

## Register the Native Host

Register all distinct IDs. Repeat either option when a browser shows more than one ID:

```powershell
.venv\Scripts\lock-in-register-native-host `
    --chrome-extension-id YOUR_CHROME_EXTENSION_ID `
    --edge-extension-id YOUR_EDGE_EXTENSION_ID
```

Registration is per Windows user and writes only:

- A Chrome manifest under `%LOCALAPPDATA%\LockIn\NativeMessaging`.
- An Edge manifest in the same directory.
- The corresponding `HKCU\Software\Google\Chrome\NativeMessagingHosts` and `HKCU\Software\Microsoft\Edge\NativeMessagingHosts` keys.

After registration, click **Reload** on every unpacked extension card. Its popup should show `connected` and a unique profile identity.

Remove the experiment registration when needed:

```powershell
.venv\Scripts\lock-in-register-native-host --uninstall
```

## Manual Browser Checklist

### Chrome, Edge, and Profiles

1. Open the popup in Chrome and Edge at the same time.
2. Click **Send ping** in each; both should record `pong / accepted`.
3. Open a second profile in each browser and load the extension.
4. Confirm each profile displays its own `Profile identity` and receives a pong.

### Tray Not Running and Concurrent Startup

Stop the tray prototype:

```powershell
.venv\Scripts\lock-in-communication-tray --shutdown
```

If it prints `not_running`, the required initial condition already exists. Reload the Chrome and Edge extensions close together. Both must reconnect, and only one tray server should survive the startup race.

### Tray Restart

While both browsers show `connected`, run the shutdown command again. The popups should show a disconnect/reconnect sequence and return to `connected` after a new Host starts the tray.

### Host Crash

Click **Crash Host** in a popup. This is an experiment-only failure injection that exits that profile's Host immediately. The extension should report disconnection, use capped reconnect backoff, and return to `connected`. Other profiles must remain connected.

### Extension Reload

Click **Reload** on one extension card. Its persistent profile identity and sequence counter should survive, a new Host connection should be created, and pings should still succeed.

### Duplicate, Out-of-Order, and Timeout

Use the popup buttons:

- **Test duplicate**: recent events must include one `accepted` pong and one `duplicate` pong.
- **Test out of order**: recent events must include an `out_of_order` pong.
- **Test timeout**: recent events must first include `timeout`, followed later by the delayed pong.

The last 20 events remain in extension-local storage so the timeout event is still visible after the late response.

## Logs and Cleanup

The tray prototype writes lifecycle-only logs here:

```text
%LOCALAPPDATA%\LockIn\experiment3-default.log
```

Logs contain process and transport lifecycle information, not browser URLs or page content. Stop the tray after testing with `lock-in-communication-tray --shutdown`. Browser Host processes exit when their extension ports close.

## Acceptance Criteria

The experiment passes when every automated check and every browser checklist item succeeds without orphaning multiple tray processes. A failure must produce a disconnect, timeout, or protocol status; it must not silently reuse a response or hang indefinitely.

The prototype uses a SID-derived Pipe name and the current process's default Windows Pipe security. Explicit production security descriptors, packaged installation paths, code signing, and update behavior remain production work and are not part of this experiment.
