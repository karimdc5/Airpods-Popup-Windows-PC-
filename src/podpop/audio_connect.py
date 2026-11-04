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
from ctypes import HRESULT, POINTER, Structure, byref, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p
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


class _PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


class _PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("ptr", c_void_p), ("pad", c_void_p)]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_ulong), "cProps")),
        COMMETHOD([], HRESULT, "GetAt", (["in"], c_ulong, "iProp"), (["out"], POINTER(_PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(_PROPERTYKEY), "key"), (["out"], POINTER(_PROPVARIANT), "pv")),
    ]


_PKEY_DEVICE_FRIENDLY_NAME = _PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
_VT_LPWSTR = 31


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
FAST_PATH_WAIT_S = 8.0  # how long the hands-free + stereo request gets before falling back
REQUEST_EVERY_S = 2.0  # fallback: re-ask for stereo this often
REWAKE_AFTER_S = 3.0  # re-wake the link only if it has been down this long


def connect(mac: str, device_name: str | None = None) -> None:
    """Bring the headset's audio to this PC. Returns once audio is active.

    1. Wake the Bluetooth link (uncached SDP query: Windows must page the device).
    2. Fast path: request the hands-free (HFP) channel, then stereo (A2DP).
       Measured on AirPods Pro 2 taken over from an iPhone: audio in ~3-8 s,
       versus ~13-15 s when asking for stereo alone, which the AirPods hold
       off until they have released the phone.
    3. Fallback: keep asking for stereo every couple of seconds.

    Raises ConnectError if the audio never came up.
    """
    mac = mac.upper()
    start = time.monotonic()
    device = _bluetooth_device(mac)
    responded = _wake_link(device)
    if responded:
        log.info("Bluetooth link awake after %.1fs", time.monotonic() - start)
    time.sleep(LINK_SETTLE_S)

    if device_name:
        _request_headset_and_stereo(mac, device_name)
        if _wait_for_audio(mac, FAST_PATH_WAIT_S):
            log.info("Audio up %.1fs after Connect (hands-free + stereo)", time.monotonic() - start)
            return
        log.info("Fast path didn't bring audio up; falling back to stereo requests")

    next_request = 0.0
    link_down_since: float | None = None
    while time.monotonic() - start < CONNECT_TIMEOUT_S:
        now = time.monotonic()
        if mac in active_devices():
            log.info("Audio up %.1fs after Connect (stereo fallback)", now - start)
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
            next_request = now + REQUEST_EVERY_S
        time.sleep(0.2)

    if not responded:
        raise ConnectError("The AirPods didn't respond. Are they nearby and out of the case?")
    raise ConnectError("The AirPods responded but wouldn't switch their audio to this PC.")


def _request_headset_and_stereo(mac: str, device_name: str) -> None:
    owns_com = _init_com()
    try:
        enumerator = comtypes.CoCreateInstance(_CLSID_MM_DEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        headset = _headset_filters(enumerator, device_name)
        stereo = [f.device_id for f in _filters_for(enumerator, mac) if f.render]
        if not headset:
            log.info("No hands-free channel found for %r", device_name)
        for filter_id in headset + stereo:
            try:
                _ks_property(enumerator, filter_id, _Op.RECONNECT)
            except (OSError, comtypes.COMError) as exc:
                log.info("Connect request on %s failed: %s", filter_id, exc)
    finally:
        if owns_com:
            comtypes.CoUninitialize()


def _wait_for_audio(mac: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if mac in active_devices():
            return True
        time.sleep(0.2)
    return False


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


def release(mac: str, device_name: str | None = None) -> None:
    """Drop hands-free *and* stereo, so the AirPods are free for another device.

    disconnect() only drops stereo, which is enough to reset a stuck stream,
    but the hands-free channel keeps the Bluetooth link up: the AirPods still
    count the PC as theirs, the phone doesn't take over, and Windows reopens
    stereo over that link a few dozen seconds later.
    """
    mac = mac.upper()
    owns_com = _init_com()
    try:
        enumerator = comtypes.CoCreateInstance(_CLSID_MM_DEVICE_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
        stereo = [f.device_id for f in _filters_for(enumerator, mac)]
        headset = _headset_filters(enumerator, device_name) if device_name else []
        if not stereo and not headset:
            raise ConnectError("No Bluetooth audio device found for this address. Is it paired with this PC?")
        dropped = 0
        for filter_id in stereo + headset:
            try:
                _ks_property(enumerator, filter_id, _Op.DISCONNECT)
                dropped += 1
                log.info("Bluetooth disconnect requested via %s", filter_id)
            except (OSError, comtypes.COMError) as exc:
                log.info("Disconnect request on %s failed: %s", filter_id, exc)
        if not dropped:
            raise ConnectError("Windows refused every disconnect request.")
    finally:
        if owns_com:
            comtypes.CoUninitialize()


def reconnect(mac: str, device_name: str | None = None, *, drop_timeout_s: float = 10.0, settle_s: float = 1.0) -> None:
    """Drop and re-open the audio link: the fix for "connected but no sound"."""
    disconnect(mac)
    deadline = time.monotonic() + drop_timeout_s
    while mac.upper() in active_devices() and time.monotonic() < deadline:
        time.sleep(0.25)
    time.sleep(settle_s)
    connect(mac, device_name)


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


def _friendly_name(endpoint) -> str:
    """e.g. 'Headset (karim’s AirPods Pro #2 - Find My)'."""
    try:
        store = ctypes.cast(endpoint.OpenPropertyStore(0), POINTER(IPropertyStore))  # STGM_READ
        value = store.GetValue(byref(_PKEY_DEVICE_FRIENDLY_NAME))
        if value.vt == _VT_LPWSTR and value.ptr:
            return ctypes.wstring_at(value.ptr)
    except (OSError, comtypes.COMError):
        pass
    return ""


def _headset_filters(enumerator, device_name: str) -> list[str]:
    """KS filters of the hands-free (HFP) channel, found by the device's name.

    The HFP filter id has no Bluetooth address in it, unlike the stereo one,
    but its endpoints are named after the device: 'Headset (<device name>)'.
    """
    found = []
    collection = enumerator.EnumAudioEndpoints(_E_ALL, _DEVICE_STATE_ACTIVE | _DEVICE_STATE_UNPLUGGED)
    for i in range(collection.GetCount()):
        endpoint = collection.Item(i)
        if device_name not in _friendly_name(endpoint):
            continue
        try:
            filter_id = _connected_filter_id(endpoint)
        except (OSError, comtypes.COMError):
            continue
        if filter_id and "bthhfenum" in filter_id.lower() and filter_id not in found:
            found.append(filter_id)
    return found


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
