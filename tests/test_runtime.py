from podpop.catalog import Family, lookup
from podpop.runtime import MIN_STEP_S, RuntimeEstimator, format_time_left
from podpop.state import Component, Snapshot


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def snap(left=None, right=None, charging=False) -> Snapshot:
    def c(level):
        return Component(level, charging, fresh=True) if level is not None else Component()

    return Snapshot(model=lookup(0x2024), left=c(left), right=c(right))


def test_uses_rated_time_before_learning():
    est = RuntimeEstimator(clock=Clock())
    est.update(snap(left=100, right=100))
    assert est.minutes_left(snap(left=100, right=100), Family.PRO) == 360  # Pro: 6 h rated


def test_learns_measured_drain_and_uses_the_emptier_bud():
    clock = Clock()
    est = RuntimeEstimator(clock=clock)
    est.update(snap(left=80, right=60))
    for level in (70, 60, 50):  # left drops a step every 20 minutes
        clock.now += 20 * 60
        est.update(snap(left=level, right=60))
    # 3 drops -> 2 timed steps of 20 min; left at 50 % right after a drop
    assert est.minutes_left(snap(left=50, right=60), Family.PRO) == 100
    est_right_lower = est.minutes_left(snap(left=50, right=20), Family.PRO)
    assert est_right_lower == 72  # right never measured: rated 36 min/step x 2 steps


def test_charging_resets_and_is_excluded():
    clock = Clock()
    est = RuntimeEstimator(clock=clock)
    est.update(snap(left=50))
    clock.now += 600
    est.update(snap(left=60, charging=True))
    assert est.minutes_left(snap(left=60, charging=True), Family.PRO) is None


def test_ignores_implausible_steps():
    clock = Clock()
    est = RuntimeEstimator(clock=clock)
    est.update(snap(left=80))
    clock.now += 1
    est.update(snap(left=70))
    clock.now += MIN_STEP_S / 2
    assert not est.update(snap(left=60))  # too fast to be real drain


def test_round_trip_profile():
    clock = Clock()
    est = RuntimeEstimator(clock=clock)
    est.update(snap(left=80))
    clock.now += 1200
    est.update(snap(left=70))
    clock.now += 1200
    assert est.update(snap(left=60))
    restored = RuntimeEstimator(clock=clock)
    restored.load(est.to_dict())
    assert restored.to_dict() == est.to_dict()
    restored.load({"left": ["junk", -5, 1e9]})
    assert restored.to_dict()["left"] == []


def test_format():
    assert format_time_left(None) is None
    assert format_time_left(4) == "Less than 10m left"
    assert format_time_left(53) == "About 55m left"
    assert format_time_left(222) == "About 3h 40m left"
    assert format_time_left(360) == "About 6h left"
