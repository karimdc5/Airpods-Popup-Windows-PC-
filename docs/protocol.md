# How PodPop reads your AirPods

iPhones show AirPods battery the moment you open the case, without connecting
to anything. They don't need to: the AirPods keep **shouting their status over
Bluetooth Low Energy**, several times a second, to anyone listening. PodPop
listens the same way. This page explains the message byte by byte, and the
real-world quirks that took the most work.

## The message

Every BLE device can broadcast small "advertisement" packets. Apple's devices
use one field, *manufacturer data*, tagged with Apple's company ID `0x004C`.
Inside it are different Continuity messages: Handoff, AirDrop, Find My…
AirPods send type **`0x07`, "Proximity Pairing"**.

Here's a real packet from an AirPods Pro 2 (USB-C), captured with
`python -m podpop --sniff`. The left bud was charging in the closed case, and
the right bud was in an ear.

```
07  19  01  24 20  73  6a  97  3a  00  05 cf 84 8b 3a 48 0a a9 f2 b7 …
│   │   │   │      │   │   │   │   │   └─ encrypted (ignored)
│   │   │   │      │   │   │   │   └─ color
│   │   │   │      │   │   │   └─ lid
│   │   │   │      │   │   └─ power / charging
│   │   │   │      │   └─ pod batteries
│   │   │   │      └─ status
│   │   │   └─ model ID
│   │   └─ prefix
│   └─ length
└─ type
```

| Byte | Value | Meaning |
|---|---|---|
| 0 | `07` | Message type: Proximity Pairing |
| 1 | `19` | Length of the rest: 25 bytes |
| 2 | `01` | Prefix, always `01` in captures |
| 3–4 | `24 20` | **Model ID**, little-endian: `0x2024` = AirPods Pro 2 (USB-C) |
| 5 | `73` | **Status flags** (see below) |
| 6 | `6a` | **Pod batteries**: low nibble `a` = 10 → 100% for the bud that sent it; high nibble `6` → 60% for the other bud |
| 7 | `97` | **Power**: low nibble `7` → case at 70%; high nibble = charging flags |
| 8 | `3a` | **Lid**: bit `0x08` set → lid closed |
| 9 | `00` | **Color** of the device |
| 10+ | … | Encrypted. Only Apple devices with the right keys can read it. |

### Status flags (byte 5)

| Bit | Meaning |
|---|---|
| `0x02` | The broadcasting bud is in an ear |
| `0x04` | Both buds are in the case |
| `0x08` | The *other* bud is in an ear |
| `0x20` | The broadcasting bud is the **left** one (otherwise right) |
| `0x40` | The broadcasting bud is in the case |

`0x73` = `0x40 + 0x20 + 0x10 + 0x02 + 0x01`: the **left** bud, **in the case**.
`0x10` and `0x01` have no known meaning yet.

### Power flags (high nibble of byte 7)

| Bit | Meaning |
|---|---|
| `0x1` | Broadcasting bud is charging |
| `0x2` | Other bud is charging |
| `0x4` | Case is charging |

`0x9` here = `0x1` + an unknown `0x8`: the left bud (the one broadcasting) is
charging.

**Battery nibbles** go from 0 to 10, meaning 0–100% in 10% steps. `0xF` means
"I don't know", for example when the other bud is out of range or no bud is in
the case to report on it. That's why AirPods battery is only ever accurate to
10%: the exact value travels in the encrypted part.

So this one packet says: *AirPods Pro 2, left 100% and charging, right 60%,
case 70%, lid closed.*

## The hard parts

Decoding the bytes was the easy half. Turning the stream into a popup you can
trust needed more care. All of this lives in
[`state.py`](../src/podpop/state.py) and is unit-tested.

**Each bud speaks for itself.** Left and right broadcast separately and each
knows its own status best. PodPop merges both streams, swapping
"this bud"/"other bud" into left/right using the `0x20` flag.

**A bud in the case lies about the other one.** While sitting in the case, a
bud reports the other bud as "not in ear" even when you're wearing it. PodPop
only trusts in-ear data about the other bud when it comes from a bud that's
out of the case. A charging bud also often keeps its own in-ear bit set.

**The addresses keep changing.** For privacy, AirPods rotate their Bluetooth
address every few minutes, so you can't just remember "my AirPods' address".
PodPop groups adverts by model and signal strength instead.

**Your neighbour has AirPods too.** On a train or in an office, several
devices of the same model may be in range. PodPop ignores weak signals
(below −75 dBm by default, adjustable), follows the strongest device with
hysteresis so the popup doesn't flicker between two, and drops packets far
weaker than the device it's tracking.

**A closed case goes quiet.** With the lid closed the buds mostly stop
broadcasting, so you rarely see a clean "closed → open" pair. PodPop treats an
"open" packet after 15 seconds of silence from the case as the lid being
opened. That's what makes the popup appear the moment you open it.

**The scanner can stop silently.** Windows' BLE watcher sometimes stops after
sleep or a radio toggle. A watchdog restarts it after two minutes without any
Apple packets.

## Connecting, not just listening

Reading the battery needs no connection at all. Connecting the AirPods to the
PC (the Connect button, auto-connect and hand-off) goes the other way, through
the Windows audio driver's Bluetooth connect/disconnect requests in
[`audio_connect.py`](../src/podpop/audio_connect.py). Windows exposes no
simple "connect this headset" API, so PodPop asks the audio driver directly.

## Try it yourself

```powershell
.\.venv\Scripts\python -m podpop --sniff
```

This prints every decoded packet live. Open and close the case, take a bud
out, and watch the flags change.

## Credits

The layout matches community research:
[AirPodsDesktop](https://github.com/SpriteOvO/AirPodsDesktop),
[OpenPods](https://github.com/adolfintel/OpenPods), and furiousMAC's
[Continuity](https://github.com/furiousMAC/continuity) protocol docs. PodPop's
decoder was checked against real AirPods Pro 2 (USB-C) packets; see
[`tests/test_protocol.py`](../tests/test_protocol.py).
