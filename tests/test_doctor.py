from podpop.doctor import AWAY_S, LinkDoctor


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def doctor() -> tuple[LinkDoctor, Clock]:
    clock = Clock()
    return LinkDoctor(clock=clock), clock


def test_back_in_range_while_windows_still_connected():
    d, clock = doctor()
    assert not d.advert(in_ear=True, audio_connected=True)
    clock.now += AWAY_S + 1  # walked away wearing them
    assert d.advert(in_ear=True, audio_connected=True)
    clock.now += 1
    assert not d.advert(in_ear=True, audio_connected=True)  # only once


def test_back_in_range_then_windows_relinks():
    d, clock = doctor()
    d.advert(in_ear=True, audio_connected=True)
    assert not d.audio_changed(connected=False)
    clock.now += AWAY_S + 1
    assert not d.advert(in_ear=True, audio_connected=False)  # never connects by itself
    assert d.audio_changed(connected=True)
    assert not d.audio_changed(connected=True)


def test_windows_relinks_before_first_advert():
    d, clock = doctor()
    d.advert(in_ear=True, audio_connected=True)
    d.audio_changed(connected=False)
    clock.now += AWAY_S + 1
    assert d.audio_changed(connected=True)
    assert not d.advert(in_ear=True, audio_connected=True)  # not twice


def test_switching_to_iphone_at_the_desk_is_left_alone():
    d, clock = doctor()
    d.advert(in_ear=True, audio_connected=True)
    assert not d.audio_changed(connected=False)  # you picked the AirPods on your iPhone
    for _ in range(10):  # still in range, still wearing them
        clock.now += 2
        assert not d.advert(in_ear=True, audio_connected=False)


def test_putting_them_away_is_not_a_problem():
    d, clock = doctor()
    d.advert(in_ear=True, audio_connected=True)
    d.advert(in_ear=False, audio_connected=True)  # taken out, into the case
    d.audio_changed(connected=False)
    clock.now += AWAY_S + 1  # case closed: quiet
    assert not d.advert(in_ear=False, audio_connected=False)
    assert not d.audio_changed(connected=True)
