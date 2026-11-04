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
