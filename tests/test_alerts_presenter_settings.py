import json

from podpop.alerts import LowBatteryMonitor
from podpop.catalog import Family, lookup
from podpop.presenter import build_view, clean_device_name
from podpop.protocol import Part
from podpop.settings import Settings
from podpop.state import Component, Snapshot


def snap(left=None, right=None, case=None, charging=False, model=0x2024) -> Snapshot:
    def c(level):
        return Component(level, charging, fresh=True) if level is not None else Component()

    return Snapshot(model=lookup(model), left=c(left), right=c(right), case=c(case))


# --- alerts ---------------------------------------------------------------


def test_alert_fires_once_per_threshold():
    m = LowBatteryMonitor((20, 10))
    assert m.update(snap(left=30)) == []
    assert [a.part for a in m.update(snap(left=20))] == [Part.LEFT]
    assert m.update(snap(left=20)) == []
    assert [a.level for a in m.update(snap(left=10))] == [10]
    assert m.update(snap(left=10)) == []


def test_alert_skips_straight_to_lowest_threshold():
    m = LowBatteryMonitor((20, 10))
    assert len(m.update(snap(right=10))) == 1
    assert m.update(snap(right=10)) == []


def test_alert_rearms_after_charging():
    m = LowBatteryMonitor((20,))
    m.update(snap(left=20))
    m.update(snap(left=40, charging=True))
    assert len(m.update(snap(left=20))) == 1


# --- presenter --------------------------------------------------------------


def test_clean_device_name():
    assert clean_device_name("karim’s AirPods Pro #2 - Find My") == "karim’s AirPods Pro #2"
    assert clean_device_name("AirPods") == "AirPods"


def test_view_for_buds():
    view = build_view(snap(left=100, right=60, case=70), "karim’s AirPods Pro #2 - Find My", connected=True)
    assert view.title == "karim’s AirPods Pro #2"
    assert view.subtitle == "AirPods Pro 2 (USB-C) · Connected"
    assert [i.label for i in view.items] == ["Left", "Case", "Right"]
    assert view.lowest_pod_level == 60


def test_view_for_headphones_has_one_battery():
    view = build_view(snap(right=50, model=0x200A), None, connected=False)
    assert view.family is Family.HEADPHONES
    assert [(i.label, i.level) for i in view.items] == [("Battery", 50)]
    assert view.subtitle == "Nearby"


def test_view_before_any_advert_uses_name():
    view = build_view(Snapshot(), "Bob’s AirPods Max", connected=True)
    assert view.family is Family.HEADPHONES
    assert all(i.level is None for i in view.items)


# --- settings ---------------------------------------------------------------


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(popup_duration_s=4.0, low_battery_thresholds=(30, 15))
    s.save(path)
    assert Settings.load(path) == s


def test_settings_tolerate_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"popup_duration_s": 5, "min_rssi": "loud", "unknown": 1}))
    s = Settings.load(path)
    assert s.popup_duration_s == 5.0
    assert s.min_rssi == Settings().min_rssi


def test_settings_missing_or_corrupt(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert Settings.load(bad) == Settings()
