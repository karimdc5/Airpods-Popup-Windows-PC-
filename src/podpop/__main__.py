"""Entry point: ``python -m podpop`` (tray app), ``--sniff``, ``--demo``."""

from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from podpop import APP_NAME, __version__
from podpop.catalog import Family
from podpop.settings import Settings, config_dir, log_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="podpop", description="iPhone-style AirPods popup for Windows.")
    parser.add_argument("--sniff", action="store_true", help="print decoded AirPods adverts to the console")
    parser.add_argument(
        "--demo",
        nargs="?",
        const=Family.PRO.value,
        choices=[f.value for f in Family],
        help="show the popup with sample data",
    )
    parser.add_argument("--theme", choices=["dark", "light"], help="with --demo: force a theme")
    parser.add_argument("--nearby", action="store_true", help="with --demo: show the not-connected state")
    parser.add_argument("--screenshot", type=Path, metavar="PNG", help="with --demo: save the popup to a PNG and exit")
    parser.add_argument("--at-ms", type=int, default=2600, help="with --screenshot: capture this long after opening")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    _configure_logging(args.debug)
    logging.info("Launching %s %s (pid %d)", APP_NAME, __version__, os.getpid())
    settings_path = config_dir() / "settings.json"
    settings = Settings.load(settings_path)

    if args.sniff:
        from podpop import sniff

        return sniff.run(settings.min_rssi)

    from PySide6.QtWidgets import QApplication

    _set_app_user_model_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    if args.demo:
        from podpop import demo

        return demo.run(app, Family(args.demo), args.theme, args.screenshot, args.nearby, args.at_ms)

    from podpop.app import PodPopApp
    from podpop.single_instance import SingleInstance
    from podpop.ui.tray import render_icon

    instance = SingleInstance(APP_NAME)
    if not instance.claim():
        logging.info("Already running; asked the existing instance to show the popup")
        return 0

    if getattr(sys, "frozen", False):
        from podpop import autostart

        if not settings_path.exists():
            # First launch of the exe: start at sign-in from now on (Settings can turn it off),
            # and save the settings so this happens only once.
            threading.Thread(target=autostart.set_enabled, args=(True,), name="podpop-autostart", daemon=True).start()
            settings.save(settings_path)
        else:
            # Keep the startup entry pointing at this exe (and on the logon task).
            threading.Thread(target=autostart.refresh, name="podpop-autostart", daemon=True).start()

    app.setWindowIcon(render_icon())
    podpop = PodPopApp(settings, settings_path)
    instance.activated.connect(podpop.show_popup)
    podpop.start()
    logging.info("%s %s started", APP_NAME, __version__)
    try:
        return app.exec()
    finally:
        podpop.shutdown()


def _configure_logging(debug: bool) -> None:
    handlers: list[logging.Handler] = []
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir() / "podpop.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass
    if sys.stderr is not None:  # None under pythonw.exe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("bleak").setLevel(logging.INFO if debug else logging.WARNING)
    logging.getLogger("comtypes").setLevel(logging.WARNING)


def _set_app_user_model_id() -> None:
    """Group notifications and the taskbar under PodPop rather than python.exe."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.{APP_NAME}")
    except (AttributeError, OSError):
        pass


if __name__ == "__main__":
    sys.exit(main())
