"""Pause and resume whatever is playing, via Windows' media session API.

Uses GlobalSystemMediaTransportControlsSessionManager (the same sessions the
Windows volume flyout shows). Unlike sending a play/pause key, it knows
whether anything is actually playing, so taking a bud out never *starts*
music, and resume goes back to the exact app that was paused.

Calls run on a single worker thread so the UI never waits on WinRT. Only
the latest request matters: if you flick a bud out and back quickly, a queued
pause that has been overtaken by a resume is dropped rather than applied late.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)

_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING


class MediaController:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="podpop-media")
        self._paused_app: str | None = None  # only touched on the worker thread
        self._requests = itertools.count(1)
        self._latest = 0

    def pause(self) -> Future[bool]:
        """Pause every playing session; resolves True if anything was paused."""
        return self._submit(self._pause)

    def resume(self) -> Future[bool]:
        """Resume what pause() paused, if it is still paused."""
        return self._submit(self._resume)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _submit(self, coro_fn) -> Future[bool]:
        self._latest = request = next(self._requests)
        return self._executor.submit(self._run, coro_fn, request)

    def _run(self, coro_fn, request: int) -> bool:
        if request != self._latest:
            log.debug("Skipping %s: superseded by a newer request", coro_fn.__name__)
            return False
        try:
            return asyncio.run(coro_fn())
        except Exception:
            log.exception("Media control failed")
            return False

    async def _pause(self) -> bool:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        paused = None
        seen = []
        for session in manager.get_sessions():
            status = session.get_playback_info().playback_status
            seen.append(f"{session.source_app_user_model_id}={int(status)}")
            if status == _PLAYING and await session.try_pause_async():
                paused = paused or session.source_app_user_model_id
        if not paused and self._paused_app:
            return True  # still paused from our earlier pause (its resume was superseded)
        if not paused:
            log.info("Nothing playing to pause (sessions: %s)", ", ".join(seen) or "none")
        if paused:
            self._paused_app = paused
            log.info("Paused %s", paused)
        return paused is not None

    async def _resume(self) -> bool:
        app, self._paused_app = self._paused_app, None
        if app is None:
            return False
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        for session in manager.get_sessions():
            if session.source_app_user_model_id == app and session.get_playback_info().playback_status != _PLAYING:
                resumed = await session.try_play_async()
                log.info("Resumed %s: %s", app, resumed)
                return bool(resumed)
        return False
