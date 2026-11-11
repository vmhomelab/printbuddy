"""An RTSP stream repeating one frame is restarted, not trusted (#3218).

On a P2S whose camera session had dropped, ffmpeg kept writing ~29 fps of one
byte-identical JPEG for two hours with no socket to the printer left. Every
repeat looked like a live stream to every check. 20 s without a changed frame
now restarts ffmpeg while the viewer stays attached -- unless the restart shows
the very same picture again, which is a still scene (a dark, idle chamber), not
a frozen ffmpeg.
"""

import asyncio
from contextlib import suppress

import pytest

from backend.app.api.routes import camera
from backend.app.services.camera_profiles import CameraProfile

PRINTER_ID = 3218
STREAM_ID = f"{PRINTER_ID}-fanout-frozen"


def _jpeg(n: int) -> bytes:
    return b"\xff\xd8frame-" + str(n).encode() + b"\xff\xd9"


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class _FakeServer:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class _Stdout:
    """One frame per read, the clock advancing a second each time."""

    def __init__(self, frames, clock: _Clock) -> None:
        self._frames = iter(frames)
        self._clock = clock

    async def read(self, _size: int = -1) -> bytes:
        self._clock.now += 1.0
        return next(self._frames, b"")


class _Proc:
    _next_pid = 79000

    def __init__(self, frames, clock: _Clock) -> None:
        _Proc._next_pid += 1
        self.pid = _Proc._next_pid
        self.returncode = None
        self.stdout = _Stdout(frames, clock)
        self.stderr = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.fixture
def rtsp(monkeypatch):
    clock = _Clock()
    sessions: list = []
    spawned: list[_Proc] = []
    real_sleep = asyncio.sleep

    async def _fake_exec(*_args, **_kwargs):
        proc = _Proc(sessions.pop(0) if sessions else [], clock)
        spawned.append(proc)
        return proc

    async def _fake_proxy(_ip: str, _port: int):
        return 48997, _FakeServer()

    async def _no_sleep(_seconds, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(camera, "get_ffmpeg_path", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(camera, "create_tls_proxy", _fake_proxy)
    monkeypatch.setattr(camera.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(camera.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(camera.time, "time", clock)
    monkeypatch.setattr(
        camera, "get_camera_profile", lambda _m: CameraProfile(rtsp_reconnect_max=3, rtsp_reconnect_delay=0.2)
    )
    yield clock, sessions, spawned
    camera._release_printer_frame_state(PRINTER_ID)


def _stream():
    return camera.generate_rtsp_mjpeg_stream(
        ip_address="192.0.2.41",
        access_code="test-code",
        model="P2S",
        fps=30,
        stream_id=STREAM_ID,
        disconnect_event=asyncio.Event(),
        printer_id=PRINTER_ID,
    )


async def _collect(stream, limit: int) -> list[bytes]:
    frames = []
    async for chunk in stream:
        if b"image/jpeg" in chunk:
            frames.append(chunk.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
        if len(frames) >= limit:
            break
    with suppress(Exception):
        await stream.aclose()
    return frames


async def test_a_frozen_session_is_restarted_and_the_viewer_keeps_going(rtsp):
    _clock, sessions, spawned = rtsp
    # The reporter's case: one real frame, then ffmpeg repeats it forever.
    sessions.append([_jpeg(1)] * 100)
    sessions.append([_jpeg(n) for n in range(2, 40)])

    frames = await asyncio.wait_for(_collect(_stream(), limit=40), timeout=10)

    assert len(spawned) == 2
    assert spawned[0].terminated
    # About 20 s of the frozen frame went out, then the new session's frames,
    # on the same viewer stream.
    assert 20 <= frames.count(_jpeg(1)) <= 23
    assert frames[-1] != _jpeg(1)


async def test_a_moving_picture_is_never_restarted(rtsp):
    _clock, sessions, spawned = rtsp
    sessions.append([_jpeg(n) for n in range(120)])

    frames = await asyncio.wait_for(_collect(_stream(), limit=120), timeout=10)

    assert len(frames) == 120
    assert len(spawned) == 1


async def test_short_runs_of_repeats_are_fine(rtsp):
    """ffmpeg's -r repeats frames when it outputs faster than the camera
    sends; a few repeats between changes are normal and keep the session."""
    _clock, sessions, spawned = rtsp
    sessions.append([_jpeg(n // 5) for n in range(150)])

    frames = await asyncio.wait_for(_collect(_stream(), limit=150), timeout=10)

    assert len(frames) == 150
    assert len(spawned) == 1


async def test_a_still_scene_is_rechecked_rarely_not_every_20s(rtsp):
    """A dark chamber can encode to the same frame every time. The first
    restart shows the same picture again, so the camera really shows it."""
    _clock, sessions, spawned = rtsp
    black = _jpeg(0)
    sessions.append([black] * 30)  # restarted after 20 s...
    sessions.append([black] * 400)  # ...and the picture is the same

    frames = await asyncio.wait_for(_collect(_stream(), limit=250), timeout=10)

    assert len(frames) == 250
    # One restart, then no more for the 230-odd seconds that follow.
    assert len(spawned) == 2


async def test_a_still_scene_is_still_rechecked_eventually(rtsp):
    _clock, sessions, spawned = rtsp
    black = _jpeg(0)
    sessions.append([black] * 30)
    sessions.append([black] * 400)
    sessions.append([_jpeg(n) for n in range(1, 50)])  # lights on

    frames = await asyncio.wait_for(_collect(_stream(), limit=360), timeout=10)

    # The re-check after 300 s found the picture moving again.
    assert len(spawned) == 3
    assert frames[-1] != black


async def test_a_moving_picture_resets_the_still_scene(rtsp):
    """Once the picture moves, a later freeze is caught after 20 s again."""
    _clock, sessions, spawned = rtsp
    black = _jpeg(0)
    sessions.append([black] * 30)
    # Same picture first (a still scene), then it moves, then freezes again.
    sessions.append([black] + [_jpeg(n) for n in range(1, 10)] + [_jpeg(9)] * 400)
    sessions.append([_jpeg(n) for n in range(100, 140)])

    frames = await asyncio.wait_for(_collect(_stream(), limit=90), timeout=10)

    # Restarted 20 s into the second freeze, not 300 s: the third session's
    # frames arrive within the 90 collected.
    assert len(spawned) == 3
    assert frames[-1] in {_jpeg(n) for n in range(100, 140)}


async def test_every_frame_still_counts_for_the_stream_watchdogs(rtsp):
    """/camera/status, the diagnostic and the orphan janitor keep reading
    every frame as before; the frozen check lives in the stream itself, so a
    still scene never looks stalled to them."""
    clock, sessions, _spawned = rtsp
    sessions.append([_jpeg(1)] * 11)

    stream = _stream()
    seen = 0
    async for chunk in stream:
        if b"image/jpeg" in chunk:
            seen += 1
            if seen == 11:
                break
    assert camera._last_frame_times[PRINTER_ID] == clock.now
    assert camera._stream_last_frame_times[STREAM_ID] == clock.now
    with suppress(Exception):
        await stream.aclose()
