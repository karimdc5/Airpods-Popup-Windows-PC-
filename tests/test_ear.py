from podpop.ear import RESUME_WITHIN_S, SETTLE_S, EarAction, EarDetector


class Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


def settle(d: EarDetector, clock: Clock, left: bool, right: bool) -> EarAction:
    """One advert with the new reading, then time passes with no more adverts."""
    assert d.update(left, right) is EarAction.NONE
    clock.now += SETTLE_S + 0.1
    return d.tick()


def detector() -> tuple[EarDetector, Clock]:
    clock = Clock()
    d = EarDetector(clock=clock)
    d.update(True, True)  # wearing both
    return d, clock


def test_take_one_out_pauses_and_putting_back_resumes():
    d, clock = detector()
    assert settle(d, clock, True, False) is EarAction.PAUSE
    assert settle(d, clock, True, True) is EarAction.RESUME


def test_a_single_advert_is_enough_without_a_second_one():
    d, clock = detector()
    d.update(True, False)
    assert d.pending
    clock.now += SETTLE_S / 2
    assert d.tick() is EarAction.NONE
    clock.now += SETTLE_S
    assert d.tick() is EarAction.PAUSE
    assert not d.pending


def test_confirming_advert_after_settle_also_works():
    d, clock = detector()
    d.update(True, False)
    clock.now += SETTLE_S + 0.1
    assert d.update(True, False) is EarAction.PAUSE


def test_glitch_is_cancelled_by_contradicting_advert():
    d, clock = detector()
    d.update(True, False)
    clock.now += 0.3
    assert d.update(True, True) is EarAction.NONE  # back before it settled
    clock.now += SETTLE_S + 1
    assert d.tick() is EarAction.NONE


def test_removing_second_bud_after_pause_does_nothing():
    d, clock = detector()
    settle(d, clock, True, False)
    assert settle(d, clock, False, False) is EarAction.NONE
    assert settle(d, clock, True, False) is EarAction.NONE  # one back: not yet
    assert settle(d, clock, True, True) is EarAction.RESUME


def test_single_bud_listening():
    clock = Clock()
    d = EarDetector(clock=clock)
    d.update(False, True)
    assert settle(d, clock, False, False) is EarAction.PAUSE
    assert settle(d, clock, False, True) is EarAction.RESUME


def test_no_resume_without_our_pause():
    d, clock = detector()
    settle(d, clock, True, False)
    d.forget_pause()  # nothing was playing
    assert settle(d, clock, True, True) is EarAction.NONE


def test_no_resume_after_a_long_break():
    d, clock = detector()
    settle(d, clock, False, False)
    clock.now += RESUME_WITHIN_S + 1
    assert settle(d, clock, True, True) is EarAction.NONE


def test_starting_with_no_buds_in_does_nothing():
    clock = Clock()
    d = EarDetector(clock=clock)
    d.update(False, False)
    assert settle(d, clock, True, True) is EarAction.NONE
