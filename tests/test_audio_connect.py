import pytest

from podpop.audio_connect import _FILTER_MAC, ConnectError, mac_from_device_id

# Real IDs from Windows for AirPods Pro 2 (USB-C).
WATCHER_ID = "Bluetooth#Bluetooth4c:77:cb:9c:5e:36-68:3e:c0:b7:f4:2c"
A2DP_FILTER = (
    r"{2}.\\?\bthenum#{0000110b-0000-1000-8000-00805f9b34fb}_vid&0001004c_pid&2024"
    r"#8&42e1e6a&0&683ec0b7f42c_c00000000#{6994ad04-93ef-11d0-a3cc-00a0c9223196}\src"
)


def test_mac_from_watcher_id():
    assert mac_from_device_id(WATCHER_ID) == "683EC0B7F42C"


def test_mac_missing():
    with pytest.raises(ConnectError):
        mac_from_device_id("Bluetooth#nothing-here")


def test_mac_from_audio_filter_id():
    assert _FILTER_MAC.search(A2DP_FILTER).group(1).upper() == mac_from_device_id(WATCHER_ID)
