from podpop.catalog import lookup


def test_hud_artwork_by_model():
    expected = {
        0x2002: "airpods", 0x200F: "airpods",  # AirPods 1, 2
        0x2013: "airpodsGen3",
        0x2019: "airpodsGen4", 0x201B: "airpodsGen4",  # AirPods 4, 4 ANC
        0x200E: "airpodsPro", 0x2014: "airpodsPro", 0x2024: "airpodsPro",
        0x200A: "airpodsMax", 0x201F: "airpodsMax",
        0x2006: "beatssolo", 0x200C: "beatssolo",
        0x2009: "beatsstudio", 0x2011: "beatsstudio", 0x2016: "beatsstudio", 0x2012: "beatsstudio",
    }
    for model_id, hud in expected.items():
        assert lookup(model_id).hud == hud, hex(model_id)


def test_unknown_model_falls_back_to_gen4():
    assert lookup(0x2FFF).hud == "airpodsGen4"
