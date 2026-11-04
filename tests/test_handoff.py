from podpop.handoff import AWAY_S, Handoff

AWAY = AWAY_S + 1


def test_step_away_releases_then_coming_back_offers_connect():
    h = Handoff()
    assert not h.due(idle_s=10, connected=True, wearing=True)  # still at the PC
    assert h.due(idle_s=AWAY, connected=True, wearing=True)
    assert h.confirm(playing=False, connected=True, wearing=True)
    assert not h.due(idle_s=AWAY + 60, connected=True, wearing=True)  # only once per time away
    assert not h.back(idle_s=AWAY + 60)  # still away
    assert h.back(idle_s=0.5)  # touched the mouse
    assert not h.back(idle_s=0.5)


def test_keeps_airpods_playing_from_this_pc():
    h = Handoff()
    assert h.due(idle_s=AWAY, connected=True, wearing=True)
    assert not h.confirm(playing=True, connected=True, wearing=True)
    assert not h.due(idle_s=AWAY + 300, connected=True, wearing=True)  # don't re-check every tick
    assert not h.back(idle_s=1)  # nothing was released, so nothing to offer
    assert h.due(idle_s=AWAY, connected=True, wearing=True)  # next time away is checked again


def test_ignores_airpods_not_worn_or_not_on_this_pc():
    h = Handoff()
    assert not h.due(idle_s=AWAY, connected=True, wearing=False)  # in the case: they let go by themselves
    assert not h.due(idle_s=AWAY, connected=False, wearing=True)  # already on the phone


def test_buds_taken_out_during_the_check_are_left_alone():
    h = Handoff()
    assert h.due(idle_s=AWAY, connected=True, wearing=True)
    assert not h.due(idle_s=AWAY, connected=True, wearing=True)  # check still running
    assert not h.confirm(playing=False, connected=True, wearing=False)
    assert not h.back(idle_s=1)


def test_custom_away_time():
    h = Handoff(away_s=300)
    assert not h.due(idle_s=200, connected=True, wearing=True)
    assert h.due(idle_s=301, connected=True, wearing=True)


def test_hold_after_release_until_done_or_expired():
    from podpop.handoff import HOLD_S

    h = Handoff()
    assert not h.holding(0)
    h.hold(100)
    assert h.holding(100 + HOLD_S - 1)  # Windows grabbing them back now gets undone
    assert not h.holding(100 + HOLD_S + 1)
    h.hold(200)
    h.end_hold()  # phone took them, or you pressed Connect
    assert not h.holding(201)
