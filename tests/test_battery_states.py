from podpop.presenter import ItemView
from podpop.protocol import Part
from podpop.ui.popup import LOW, OK, WARN, battery_color, is_charging


def test_bud_in_ear_never_shows_charging():
    assert not is_charging(ItemView(Part.LEFT, "Left", 80, charging=True, in_ear=True))
    assert is_charging(ItemView(Part.LEFT, "Left", 80, charging=True, in_ear=False))  # in the case


def test_case_charging_is_its_own_column():
    case = ItemView(Part.CASE, "Case", 40, charging=True)
    bud = ItemView(Part.RIGHT, "Right", 40, charging=False)
    assert is_charging(case)
    assert not is_charging(bud)


def test_absent_part_is_not_charging():
    assert not is_charging(ItemView(Part.CASE, "Case", None, charging=True))


def test_colours_follow_ios():
    assert battery_color(21, charging=False) == OK
    assert battery_color(20, charging=False) == WARN
    assert battery_color(11, charging=False) == WARN
    assert battery_color(10, charging=False) == LOW
    assert battery_color(5, charging=True) == OK  # charging is green regardless of level


# --- grouping like iOS: AirPods together, case separately ---------------------

from podpop.catalog import Family  # noqa: E402
from podpop.presenter import DeviceView  # noqa: E402
from podpop.ui.popup import battery_groups  # noqa: E402


def _view(left, right, case, *, left_charging=False, right_charging=False, case_charging=False, in_ear=True):
    items = (
        ItemView(Part.LEFT, "Left", left, charging=left_charging, in_ear=in_ear and not left_charging),
        ItemView(Part.CASE, "Case", case, charging=case_charging),
        ItemView(Part.RIGHT, "Right", right, charging=right_charging, in_ear=in_ear and not right_charging),
    )
    return DeviceView("AirPods Pro", "", Family.PRO, items)


def test_buds_share_a_battery_when_close():
    groups = battery_groups(_view(96, 100, 73))
    assert [(g.kind, g.level) for g in groups] == [("pair", 96), ("case", 73)]


def test_buds_split_when_far_apart():
    groups = battery_groups(_view(40, 90, 73))
    assert [(g.kind, g.level) for g in groups] == [("left", 40), ("right", 90), ("case", 73)]


def test_pair_charges_only_when_every_bud_does():
    both = battery_groups(_view(96, 96, 73, left_charging=True, right_charging=True, in_ear=False))
    assert both[0].charging
    one = battery_groups(_view(96, 96, 73, left_charging=True))
    assert not one[0].charging


def test_case_charging_never_marks_the_buds():
    groups = battery_groups(_view(80, 80, 50, case_charging=True))
    assert not groups[0].charging and groups[1].charging


def test_missing_buds_show_a_dash():
    groups = battery_groups(_view(None, None, 50))
    assert groups[0].kind == "pair" and groups[0].level is None
