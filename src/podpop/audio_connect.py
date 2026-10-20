"""Connect, disconnect and query the audio link of a paired Bluetooth headset.

Windows has no public "connect this headset" API, but the Bluetooth audio
driver exposes a one-shot property, ``KSPROPERTY_ONESHOT_RECONNECT``, on the
headset's kernel-streaming filter. Querying it makes Windows open the audio
connection, which is what the Connect button in Bluetooth settings does.
The same technique is used by ToothTray.

The audio endpoints of a paired headset exist even while it is connected to
another device (state "unplugged"). But the property only re-opens audio on
an existing Bluetooth link: when the AirPods moved to an iPhone, the PC's
link is gone and the request silently does nothing. So connect() first
*wakes* the link with an uncached SDP service query (Windows has to page the
device to answer it), waits for it to settle, then asks for audio, retrying
a few times.

    endpoint (IMMDevice) -> IDeviceTopology -> connector -> KS filter device
        -> IKsControl.KsProperty(KSPROPSETID_BtAudio, ONESHOT_RECONNECT)

``active_devices()`` reports which headsets currently have a working audio
endpoint. That is the real "connected to this PC" signal: Windows' Bluetooth
``IsConnected`` flag stays true while AirPods keep a background link open
even after the audio has moved to another device.

connect()/disconnect() can block briefly, so run them off the UI thread.
"""

from __future__ import annotations

import ctypes
import logging
import asyncio
import re
import time
from ctypes import HRESULT, POINTER, Structure, byref, c_uint, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD, ULONG
from dataclasses import dataclass
from enum import IntEnum

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, IUnknown

log = logging.getLogger(__name__)

_KSPROPSETID_BT_AUDIO = GUID("{7FA06C40-B8F6-4C7E-8556-E8C33A12E54D}")
_KSPROPERTY_TYPE_GET = 0x1
_DEVICE_STATE_ACTIVE = 0x1
_DEVICE_STATE_UNPLUGGED = 0x8
_E_RENDER, _E_ALL = 0, 2
_RPC_E_CHANGED_MODE = -2147417850
_A2DP_SINK = "0000110b"  # preferred: the stereo profile


class _Op(IntEnum):
    RECONNECT = 0
    DISCONNECT = 1


class ConnectError(RuntimeError):
    pass


class _KSPROPERTY(Structure):
    _fields_ = [("Set", GUID), ("Id", ULONG), ("Flags", ULONG)]


class IKsControl(IUnknown):
    _iid_ = GUID("{28F54685-06FD-11D2-B27A-00A0C9223196}")
    _methods_ = [
        COMMETHOD(
            [], HRESULT, "KsProperty",
            (["in"], POINTER(_KSPROPERTY), "Property"),
            (["in"], ULONG, "PropertyLength"),
            (["in"], c_void_p, "PropertyData"),
            (["in"], ULONG, "DataLength"),
            (["out"], POINTER(ULONG), "BytesReturned"),
        ),
    ]


class IConnector(IUnknown):
    _iid_ = GUID("{9C2C4058-23F5-41DE-877A-DF3AF236A09E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetType", (["out"], POINTER(c_uint), "pType")),
        COMMETHOD([], HRESULT, "GetDataFlow", (["out"], POINTER(c_uint), "pFlow")),
        COMMETHOD([], HRESULT, "ConnectTo", (["in"], c_void_p, "pConnectTo")),
        COMMETHOD([], HRESULT, "Disconnect"),
        COMMETHOD([], HRESULT, "IsConnected", (["out"], POINTER(ctypes.c_int), "pbConnected")),
        COMMETHOD([], HRESULT, "GetConnectedTo", (["out"], POINTER(c_void_p), "ppConTo")),
        COMMETHOD([], HRESULT, "GetConnectorIdConnectedTo", (["out"], POINTER(c_wchar_p), "ppwstrConnectorId")),
        COMMETHOD([], HRESULT, "GetDeviceIdConnectedTo", (["out"], POINTER(c_wchar_p), "ppwstrDeviceId")),
    ]


class IDeviceTopology(IUnknown):
    _iid_ = GUID("{2A07407E-6497-4A18-9787-32F79BD0D98F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetConnectorCount", (["out"], POINTER(c_uint), "pCount")),
        COMMETHOD([], HRESULT, "GetConnector", (["in"], c_uint, "nIndex"), (["out"], POINTER(POINTER(IConnector)), "ppConnector")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD(
            [], HRESULT, "Activate",
            (["in"], POINTER(GUID), "iid"),
            (["in"], DWORD, "dwClsCtx"),
            (["in"], c_void_p, "pActivationParams"),
            (["out"], POINTER(POINTER(IUnknown)), "ppInterface"),
        ),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD, "stgmAccess"), (["out"], POINTER(c_void_p), "ppProperties")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(DWORD), "pdwState")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "pcDevices")),
        COMMETHOD([], HRESULT, "Item", (["in"], c_uint, "nDevice"), (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD(
            [], HRESULT, "EnumAudioEndpoints",
            (["in"], c_uint, "dataFlow"),
            (["in"], DWORD, "dwStateMask"),
            (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices"),
        ),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_uint, "dataFlow"), (["in"], c_uint, "role"), (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
        COMMETHOD([], HRESULT, "GetDevice", (["in"], c_wchar_p, "pwstrId"), (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
    ]


_CLSID_MM_DEVICE_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


@dataclass(frozen=True, slots=True)
class _Filter:
    device_id: str  # the KS filter behind an audio endpoint
    render: bool


_FILTER_MAC = re.compile(r"&([0-9a-f]{12})_", re.IGNORECASE)


def mac_from_device_id(device_id: str) -> str:
    """'Bluetooth#Bluetooth4c:77:cb:9c:5e:36-68:3e:c0:b7:f4:2c' -> '683EC0B7F42C'."""
    match = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})$", device_id)
    if not match:
        raise ConnectError(f"No Bluetooth address in {device_id!r}")
    return match.group(1).replace(":", "").upper()


def active_devices() -> set[str]:
    """Bluetooth addresses (upper-case hex) of headsets with an active audio endpoint."""
    owns_com = _init_com()
    try:
        enumerator = comtypes.CoCreateInstance(_CLSID_MM_DEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        collection = enumerator.EnumAudioEndpoints(_E_ALL, _DEVICE_STATE_ACTIVE)
        macs = set()
        for i in range(collection.GetCount()):
            try:
                filter_id = _connected_filter_id(collection.Item(i))
            except (OSError, comtypes.COMError):
                continue
            match = _FILTER_MAC.search(filter_id or "")
            if match and "bth" in filter_id.lower():
                macs.add(match.group(1).upper())
        return macs
    finally:
        if owns_com:
            comtypes.CoUninitialize()


CONNECT_TIMEOUT_S = 25.0
LINK_SETTLE_S = 0.5
REQUEST_EVERY_S = 1.0  # ask for audio this often until it comes up
REWAKE_AFTER_S = 3.0  # re-wake the link only if it has been down this long


def connect(mac: str) -> None:
    """Bring the headset's audio to this PC, waking the Bluetooth link first.

    Wakes the link once, then asks for audio every second until the endpoint
    is active. The link is only re-woken if it actually drops: waking it
    repeatedly seemed to restart the AirPods' handover from the other device.
    Returns once audio is active; raises ConnectError otherwise.
    """
    mac = mac.upper()
    start = time.monotonic()
    device = _bluetooth_device(mac)
    responded = _wake_link(device)
    link_up_at = time.monotonic() if responded else None
    if responded:
        log.info("Bluetooth link awake after %.1fs", link_up_at - start)
    time.sleep(LINK_SETTLE_S)

    requests = 0
    next_request = time.monotonic()
    link_down_since: float | None = None
    while time.monotonic() - start < CONNECT_TIMEOUT_S:
        now = time.monotonic()
        if mac in active_devices():
            log.info("Audio up %.1fs after Connect (%d requests)", now - start, requests)
            return
        if _link_up(device):
            link_down_since = None
        else:
            link_down_since = link_down_since or now
            if now - link_down_since >= REWAKE_AFTER_S:
                responded |= _wake_link(device)
                link_down_since = None
        if now >= next_request:
            _oneshot(mac, _Op.RECONNECT)
            requests += 1
            next_request = now + REQUEST_EVERY_S
        time.sleep(0.2)

    if not responded:
        raise ConnectError("The AirPods didn't respond. Are they nearby and out of the case?")
    raise ConnectError("The AirPods responded but wouldn't switch their audio to this PC.")


def _bluetooth_device(mac: str):
    async def get():
        from winrt.windows.devices.bluetooth import BluetoothDevice

        return await BluetoothDevice.from_bluetooth_address_async(int(mac, 16))

    try:
        return asyncio.run(get())
    except Exception:
        log.debug("Could not open the Bluetooth device", exc_info=True)
        return None


def _link_up(device) -> bool:
    try:
        return device is not None and int(device.connection_status) == 1  # BluetoothConnectionStatus.CONNECTED
    except Exception:
        return False


def _wake_link(device) -> bool:
    """Force Windows to page the device by asking for its services uncached."""
    if device is None:
        return False

    async def query() -> bool:
        from winrt.windows.devices.bluetooth import BluetoothCacheMode

        result = await device.get_rfcomm_services_with_cache_mode_async(BluetoothCacheMode.UNCACHED)
        return int(result.error) == 0

    try:
        return asyncio.run(query())
    except Exception:
        log.debug("Waking the Bluetooth link failed", exc_info=True)
        return False


def disconnect(mac: str) -> None:
    _oneshot(mac, _Op.DISCONNECT)


def reconnect(mac: str, *, drop_timeout_s: float = 10.0, settle_s: float = 1.0) -> None:
    """Drop and re-open the audio link: the fix for "connected but no sound"."""
    disconnect(mac)
    deadline = time.monotonic() + drop_timeout_s
    while mac.upper() in active_devices() and time.monotonic() < deadline:
        time.sleep(0.25)
    time.sleep(settle_s)
    connect(mac)


def _oneshot(mac: str, op: _Op) -> None:
    owns_com = _init_com()
    try:
        enumerator = comtypes.CoCreateInstance(_CLSID_MM_DEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        filters = _filters_for(enumerator, mac.upper())
        if not filters:
            raise ConnectError("No Bluetooth audio device found for this address. Is it paired with this PC?")
        # Stereo (A2DP) render filters first; one successful call is enough.
        filters.sort(key=lambda f: (not f.render, _A2DP_SINK not in f.device_id.lower()))
        errors = []
        for f in filters:
            try:
                _ks_property(enumerator, f.device_id, op)
                log.info("Bluetooth %s requested via %s", op.name.lower(), f.device_id)
                return
            except (OSError, comtypes.COMError) as exc:
                errors.append(exc)
        raise ConnectError(f"Windows refused the {op.name.lower()} request: {errors[-1]}")
    finally:
        if owns_com:
            comtypes.CoUninitialize()


def _init_com() -> bool:
    """Initialise COM on this thread; False if it already was (any apartment)."""
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        return True
    except OSError as exc:
        if exc.winerror == _RPC_E_CHANGED_MODE:
            return False
        raise


def _filters_for(enumerator, mac: str) -> list[_Filter]:
    found: dict[str, _Filter] = {}
    collection = enumerator.EnumAudioEndpoints(_E_ALL, _DEVICE_STATE_ACTIVE | _DEVICE_STATE_UNPLUGGED)
    for i in range(collection.GetCount()):
        endpoint = collection.Item(i)
        try:
            filter_id = _connected_filter_id(endpoint)
        except (OSError, comtypes.COMError):
            continue  # endpoints without a topology, e.g. virtual devices
        if filter_id and mac in filter_id.upper().replace(":", "") and filter_id not in found:
            render = endpoint.GetId().startswith("{0.0.0.")  # render endpoints are {0.0.0.*}, capture {0.0.1.*}
            found[filter_id] = _Filter(filter_id, render)
    return list(found.values())


def _connected_filter_id(endpoint) -> str | None:
    topology = endpoint.Activate(byref(IDeviceTopology._iid_), CLSCTX_ALL, None).QueryInterface(IDeviceTopology)
    if topology.GetConnectorCount() == 0:
        return None
    return topology.GetConnector(0).GetDeviceIdConnectedTo()


def _ks_property(enumerator, filter_id: str, op: _Op) -> None:
    device = enumerator.GetDevice(filter_id)
    control = device.Activate(byref(IKsControl._iid_), CLSCTX_ALL, None).QueryInterface(IKsControl)
    prop = _KSPROPERTY(_KSPROPSETID_BT_AUDIO, op, _KSPROPERTY_TYPE_GET)
    control.KsProperty(byref(prop), ctypes.sizeof(prop), None, 0)
