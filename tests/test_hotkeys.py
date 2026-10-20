from podpop.hotkeys import Hotkey, parse_hotkey


def test_parse_common_combos():
    assert parse_hotkey("Ctrl+Alt+A") == Hotkey(0x2 | 0x1, ord("A"))
    assert parse_hotkey("ctrl + shift + f9") == Hotkey(0x2 | 0x4, 0x78)
    assert parse_hotkey("Win+Space") == Hotkey(0x8, 0x20)
    assert parse_hotkey("Alt+7") == Hotkey(0x1, ord("7"))


def test_rejects_unsafe_or_invalid():
    assert parse_hotkey("") is None
    assert parse_hotkey("A") is None  # would swallow typing
    assert parse_hotkey("Shift+A") is None
    assert parse_hotkey("Ctrl+Banana") is None
    assert parse_hotkey("Hyper+A") is None
    assert parse_hotkey("Ctrl+F25") is None
