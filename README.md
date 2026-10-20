# PodPop

An iPhone-style AirPods popup for Windows. When your AirPods connect, or you
open the case nearby, a card slides up from the bottom of the screen with
battery levels for each bud and the case. It lives in the notification area
with a live battery tooltip.

## Features
- Popup on **connect** and on **case open**. Click the tray icon to show it any time.
- Left, right and case battery, charging state, and **in-ear** detection.
- Artwork for each model: AirPods 1/2, 3/4, Pro, Pro 2 and Max, plus Beats.
- Light and dark mode that follow Windows.
- **Low-battery notifications** at 20% and 10%, once per threshold.
- Tray menu: toggle each trigger, start with Windows, open the logs.
- Single instance: launching it again just shows the popup.
- **Connect button**: pulls the AirPods over to this PC (for example from your
  iPhone) with one click. Optionally connects automatically when the case opens.
- **Stuck-audio fix**: Windows sometimes shows AirPods as connected but plays
  nothing after you walk out of range and back. PodPop notices that you left
  while wearing them and re-opens the audio link once you're back. It never
  connects on its own, so it won't take the AirPods from your phone. There's
  also a manual *Reconnect audio* item in the tray menu.
- **Ear detection**: take an AirPod out and your music or video pauses; put
  it back and it resumes, using Windows' media sessions (it never starts
  playback that wasn't paused by PodPop).

## How it works
AirPods continuously broadcast a Bluetooth LE "Proximity Pairing" advert,
the same one an iPhone reads. Its battery and status fields are
unencrypted, so PodPop listens with Windows' own BLE stack (via
[bleak](https://github.com/hbldh/bleak)) and decodes them. Connect and
disconnect events come from a WinRT `DeviceWatcher`.

```
 BLE adverts ──► ble.py ──► protocol.py ──► state.Tracker ──┐
   (thread)       decode     (pure)        merge, pick       ├─► presenter ──► popup / tray
 WinRT watcher ─► connection.py ────────────────────────────┘     (pure)        (Qt)
```

| Module | Role |
|---|---|
| `protocol.py` | Decodes the advert bytes. Pure and unit-tested against real packets. |
| `catalog.py` | Model IDs, names and product family (picks the artwork). |
| `state.py` | Merges adverts from both pods, tracks freshness, filters strangers' AirPods by signal strength, and detects the case opening. |
| `alerts.py` | Low-battery thresholds with re-arming. |
| `presenter.py` | Turns state into what the UI shows. |
| `ble.py` / `connection.py` | Windows services on background threads, with retry and watchdog. |
| `audio_connect.py` | Connect, disconnect and "is audio active" for a paired headset (Windows audio COM APIs). |
| `doctor.py` | Decides when a stuck link needs a reconnect after you were out of range. Pure and tested. |
| `ui/` | Popup card, vector artwork, tray icon. |
| `app.py` | Wires everything together on the Qt thread. |

## Limits (what AirPods don't broadcast)
- Battery comes in **10% steps**. Exact 1% values and noise-control modes need
  Apple's private L2CAP protocol, which Windows doesn't expose to apps.
- The case battery is only known while a bud sits in it.
- Someone else's AirPods of the same model nearby can interfere. Raise
  `min_rssi` in settings (for example to `-65`) if that happens.

## Run from source
```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\pythonw -m podpop          # tray app
.\.venv\Scripts\python -m podpop --sniff   # print decoded adverts live
.\.venv\Scripts\python -m podpop --demo pro --theme light   # popup with sample data
.\.venv\Scripts\python -m pytest
```

## Build a standalone exe
```powershell
.\scripts\build.ps1      # -> dist\PodPop.exe
```

## Settings
`%APPDATA%\PodPop\settings.json`: popup triggers and duration, which monitor
it opens on, low-battery thresholds, `min_rssi`, and the device-name pattern.
Logs are in `%LOCALAPPDATA%\PodPop\logs`.

## Roadmap
- [x] Auto play/pause media when a bud is taken out.
- [ ] Settings window (duration, position, thresholds) instead of editing JSON.
- [ ] Per-color artwork (the color byte is decoded).
- [ ] Global hotkey to show the popup.

## Credits
Protocol layout cross-checked against
[AirPodsDesktop](https://github.com/SpriteOvO/AirPodsDesktop) (GPL-3.0; no
code copied), OpenPods, and furiousMAC's Continuity research.
