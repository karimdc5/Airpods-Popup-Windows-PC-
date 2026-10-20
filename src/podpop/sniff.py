"""Console diagnostics: print every decoded AirPods advert (``podpop --sniff``)."""

from __future__ import annotations

import sys
import time

from .ble import Advert, BleListener
from .catalog import lookup
from .protocol import Battery


def run(min_rssi: int) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    last_payload: dict[str, bytes] = {}

    def on_advert(advert: Advert) -> None:
        if advert.rssi < min_rssi or last_payload.get(advert.address) == advert.payload:
            return
        last_payload[advert.address] = advert.payload
        r = advert.report
        lid = "?" if r.lid_open is None else "open" if r.lid_open else "closed"
        print(
            f"{time.strftime('%H:%M:%S')}  {advert.address[-8:]}  {advert.rssi:4d} dBm  "
            f"{lookup(r.model_id).name:<22}  L {_fmt(r.left, r.left_in_ear)}  R {_fmt(r.right, r.right_in_ear)}  "
            f"case {_fmt(r.case)}  lid {lid:<6}  from {r.broadcaster.value:<5}  "
            f"raw {advert.payload[:10].hex(' ')}",
            flush=True,
        )

    listener = BleListener(on_advert, lambda state, detail: print(f"[scanner {state.value}] {detail}", flush=True))
    print(f"Listening for AirPods adverts stronger than {min_rssi} dBm (Ctrl+C to stop)…", flush=True)
    listener.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    return 0


def _fmt(battery: Battery, in_ear: bool = False) -> str:
    if battery.level is None:
        return "  —   "
    return f"{battery.level:3d}%{'⚡' if battery.charging else ' '}{'👂' if in_ear else ' '}"
