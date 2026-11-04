from podpop.handoff import Handoff


def test_lock_while_wearing_releases_then_unlock_takes_back():
    h = Handoff()
    assert h.lock(connected=True, wearing=True)
    assert h.grace_over(connected=True, wearing=True, playing=False)
    assert h.unlock(connected=False, wearing=True)


def test_quick_unlock_does_nothing():
    h = Handoff()
    assert h.lock(connected=True, wearing=True)
    assert not h.unlock(connected=True, wearing=True)  # back within the grace period
    assert not h.grace_over(connected=True, wearing=True, playing=False)  # stale timer


def test_keeps_airpods_playing_from_this_pc():
    h = Handoff()
    assert h.lock(connected=True, wearing=True)
    assert not h.grace_over(connected=True, wearing=True, playing=True)
    assert not h.unlock(connected=True, wearing=True)


def test_ignores_airpods_not_worn_or_not_on_this_pc():
    h = Handoff()
    assert not h.lock(connected=True, wearing=False)  # in the case: they let go by themselves
    assert not h.lock(connected=False, wearing=True)  # already on the phone
    assert not h.unlock(connected=False, wearing=True)  # never took them, so never takes them back


def test_buds_taken_out_during_grace_are_left_alone():
    h = Handoff()
    assert h.lock(connected=True, wearing=True)
    assert not h.grace_over(connected=True, wearing=False, playing=False)


def test_unlock_without_wearing_them_leaves_them_on_the_phone():
    h = Handoff()
    h.lock(connected=True, wearing=True)
    assert h.grace_over(connected=True, wearing=True, playing=False)
    assert not h.unlock(connected=False, wearing=False)
    assert not h.unlock(connected=False, wearing=True)  # only once per hand-off
