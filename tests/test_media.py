import threading

from podpop.media import MediaController


def test_superseded_requests_are_dropped():
    m = MediaController()
    ran = []
    gate = threading.Event()

    async def blocker():
        gate.wait(2)
        return True

    async def record(name):
        ran.append(name)
        return True

    async def first():
        return await record("first")

    async def second():
        return await record("second")

    try:
        m._submit(blocker)  # occupies the worker
        f1 = m._submit(first)
        f2 = m._submit(second)  # supersedes first before it runs
        gate.set()
        assert f2.result(5) is True
        assert f1.result(5) is False
        assert ran == ["second"]
    finally:
        m.shutdown()
