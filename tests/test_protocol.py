from podpop.protocol import Battery, Part, parse

# Captured from real AirPods Pro 2 (USB-C) on 2026-10-20: left pod in the
# (closed) case charging at 100 %, right pod in use at 60 %, case at 70 %.
FROM_LEFT_IN_CASE = bytes.fromhex("0719012420736a973a0005cf848b3a480aa9f2b79dbaac66504b29")
FROM_RIGHT_IN_EAR = bytes.fromhex("071901242013a6a71100059e726d7a809dc13881d27c3445744877")
FROM_RIGHT_ALONE = bytes.fromhex("071901242002f68f110005c79d5a99995a54b6dadd33430c6dbcae")


def test_both_pods_agree_on_left_and_right():
    a, b = parse(FROM_LEFT_IN_CASE), parse(FROM_RIGHT_IN_EAR)
    for report in (a, b):
        assert report.model_id == 0x2024
        assert report.left == Battery(100, charging=True)
        assert report.right == Battery(60, charging=False)
        assert report.case == Battery(70, charging=False)
    assert a.broadcaster is Part.LEFT
    assert b.broadcaster is Part.RIGHT


def test_in_ear_ignores_charging_pod():
    a = parse(FROM_LEFT_IN_CASE)
    assert a.left_in_ear is False  # in-ear bit is set, but the pod is charging
    b = parse(FROM_RIGHT_IN_EAR)
    assert b.right_in_ear is True and b.left_in_ear is False


def test_pod_in_case_cannot_vouch_for_the_other():
    # Seen live: left in the open case reports "right not in ear" while it is.
    assert parse(FROM_LEFT_IN_CASE).right_in_ear is None


# Live capture, both buds worn: status 0x0b (both in), then 0x09 (right out).
BOTH_IN = bytes.fromhex("0719012420" + "0b" + "a28f1100" + "05" + "00" * 16)
RIGHT_OUT = bytes.fromhex("0719012420" + "09" + "a28f1100" + "05" + "00" * 16)


def test_worn_pod_reports_both():
    both, right_out = parse(BOTH_IN), parse(RIGHT_OUT)
    assert (both.left_in_ear, both.right_in_ear) == (True, True)
    assert (right_out.left_in_ear, right_out.right_in_ear) == (True, False)


def test_lid_only_trusted_from_pod_in_case():
    assert parse(FROM_LEFT_IN_CASE).lid_open is False
    assert parse(FROM_RIGHT_IN_EAR).lid_open is None


def test_unknown_nibbles():
    report = parse(FROM_RIGHT_ALONE)
    assert report.right == Battery(60)
    assert report.left.level is None
    assert report.case.level is None


def test_lid_open_with_both_in_case():
    payload = bytearray(FROM_RIGHT_IN_EAR)
    payload[5] = 0x04  # both in case, broadcaster is right, not charging
    payload[8] = 0x01  # closed bit clear
    assert parse(bytes(payload)).lid_open is True


def test_rejects_other_messages():
    assert parse(b"") is None
    assert parse(bytes.fromhex("1005")) is None
    assert parse(bytes.fromhex("10061d1d")) is None
    assert parse(FROM_LEFT_IN_CASE[:9]) is None


# Live capture 03:06: left bud resting in the open case, NOT charging, status
# 0x73. It claims to be in an ear and says the worn right bud is out.
LEFT_IN_CASE_NOT_CHARGING = bytes.fromhex("0719012420" + "73" + "29" + "0f" + "3a" + "05" + "00" * 16)


def test_pod_in_case_without_charging_is_not_in_ear():
    r = parse(LEFT_IN_CASE_NOT_CHARGING)
    assert r.broadcaster is Part.LEFT and not r.left.charging
    assert r.left_in_ear is False
    assert r.right_in_ear is None  # can't vouch for the worn bud
