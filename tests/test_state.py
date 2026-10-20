import dataclasses

from podpop.protocol import Battery, Part, ProximityReport
from podpop.state import CANDIDATE_TIMEOUT_S, LID_QUIET_S, POD_FRESH_S, Tracker


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def report(
    model=0x2024, left=None, right=None, case=None, lid_open=None, left_in_ear=False, right_in_ear=False, **charging
) -> ProximityReport:
    return ProximityReport(
        model_id=model,
        left=Battery(left, charging.get("left_charging", False)),
        right=Battery(right, charging.get("right_charging", False)),
        case=Battery(case, charging.get("case_charging", False)),
        left_in_ear=left_in_ear,
        right_in_ear=right_in_ear,
        lid_open=lid_open,
        broadcaster=Part.LEFT,
        color=0,
    )


def test_merges_partial_reports_from_each_pod():
    t = Tracker(clock=Clock())
    t.feed(report(left=100, case=70, left_charging=True), -50)
    t.feed(report(right=60), -52)
    snap = t.snapshot()
    assert (snap.left.level, snap.left.charging) == (100, True)
    assert snap.right.level == 60
    assert snap.case.level == 70
    assert snap.model.name == "AirPods Pro 2 (USB-C)"


def test_ignores_weak_adverts():
    t = Tracker(min_rssi=-75, clock=Clock())
    assert not t.feed(report(left=50), -90).changed
    assert t.snapshot().left.level is None


def test_readings_go_stale_but_are_kept():
    clock = Clock()
    t = Tracker(clock=clock)
    t.feed(report(left=80), -50)
    clock.now += POD_FRESH_S + 1
    left = t.snapshot().left
    assert left.level == 80 and not left.fresh


def test_drops_same_model_outlier():
    t = Tracker(clock=Clock())
    for _ in range(5):
        t.feed(report(left=80), -40)
    assert not t.feed(report(left=10), -72).changed  # a stranger's pair, much further away
    assert t.snapshot().left.level == 80


def test_switches_device_only_with_clear_margin():
    clock = Clock()
    t = Tracker(clock=clock)
    t.feed(report(model=0x2024, left=80), -55)
    t.feed(report(model=0x2014, left=30), -52)  # slightly stronger: not enough to switch
    assert t.snapshot().left.level == 80
    clock.now += CANDIDATE_TIMEOUT_S + 1
    t.feed(report(model=0x2014, left=30), -52)  # first device vanished
    assert t.snapshot().left.level == 30


def test_lid_open_transition():
    t = Tracker(clock=Clock())
    assert not t.feed(report(left=80, lid_open=False), -50).lid_opened
    assert not t.feed(report(left=80, lid_open=None), -50).lid_opened  # pod outside the case
    assert t.feed(report(left=80, lid_open=True), -50).lid_opened
    assert not t.feed(report(left=80, lid_open=True), -50).lid_opened


def test_snapshot_equality_ignores_rssi():
    t = Tracker(clock=Clock())
    t.feed(report(left=80), -50)
    assert not t.feed(report(left=80), -48).changed
    assert dataclasses.replace(t.snapshot(), rssi=-10) == t.snapshot()


def test_lid_open_after_quiet_case_counts_as_opening():
    clock = Clock()
    t = Tracker(clock=clock)
    assert t.feed(report(left=80, lid_open=True), -50).lid_opened  # first sighting of an open case
    clock.now += 1
    assert not t.feed(report(left=80, lid_open=True), -50).lid_opened  # still open
    clock.now += LID_QUIET_S + 1  # case closed: pods went quiet
    assert t.feed(report(left=80, lid_open=True), -50).lid_opened


def test_unknown_in_ear_keeps_last_trusted_value():
    t = Tracker(clock=Clock())
    t.feed(report(left=100, right=20, left_in_ear=False, right_in_ear=True), -50)  # from the worn right bud
    t.feed(report(left=100, right=20, left_in_ear=False, right_in_ear=None), -50)  # from the left bud in the case
    snap = t.snapshot()
    assert snap.right.in_ear and not snap.left.in_ear
