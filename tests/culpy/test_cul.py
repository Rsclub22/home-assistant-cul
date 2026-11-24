"""Tests for the CUL core."""

import asyncio

import pytest

from custom_components.cul.culpy.cul import Cul, probe
from custom_components.cul.culpy.transport.fake import FakeTransport

ANSWERS = {"V": "V 1.67 CUL868", "T01": "1034", "T03": "FF", "X": "21  900"}


async def until(cond, timeout=2.0):  # noqa: ASYNC109
    async with asyncio.timeout(timeout):
        while not cond():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


def make(fake, **kw):
    events, states = [], []
    cul = Cul(lambda: fake, fhtid="1034", on_event=events.append,
              on_state=lambda s: states.append(s.connected), reconnect_min=0.01,
              reconnect_max=0.02, query_timeout=0.2, **kw)
    return cul, events, states


async def test_init_sequence_keeps_matching_fhtid():
    fake = FakeTransport(ANSWERS)
    cul, _, _ = make(fake)
    await cul.start()
    await until(lambda: cul.state.connected)
    assert fake.written == ["V", "X21", "T01", "T03", "X"]
    assert (cul.state.version, cul.state.fhtid, cul.state.fhtbuf, cul.state.credit10ms) == (
        "V 1.67 CUL868", "1034", 255, 900)
    await cul.stop()


async def test_init_sets_other_fhtid():
    fake = FakeTransport({**ANSWERS, "T01": "0000"})
    cul, _, _ = make(fake)
    await cul.start()
    await until(lambda: cul.state.connected)
    assert "T011034" in fake.written
    await cul.stop()


async def test_rf_event_and_lovf():
    fake = FakeTransport(ANSWERS)
    cul, events, _ = make(fake)
    await cul.start()
    await until(lambda: cul.state.connected)
    fake.feed("T1C504169284A")
    fake.feed("LOVF")
    await until(lambda: events and cul.state.lovf)
    assert events[0].values == {"desired-temp": 20.0}
    await cul.stop()


async def test_rf_line_during_query_is_not_an_answer():
    fake = FakeTransport({k: v for k, v in ANSWERS.items() if k != "T03"})
    cul, events, _ = make(fake)
    await cul.start()
    await until(lambda: "T03" in fake.written)
    fake.feed("T1C504169284A")
    fake.feed("FF")
    await until(lambda: cul.state.connected)
    assert cul.state.fhtbuf == 255
    assert events[0].values == {"desired-temp": 20.0}
    await cul.stop()


async def test_garbage_lines_do_not_crash():
    fake = FakeTransport(ANSWERS)
    cul, events, _ = make(fake)
    await cul.start()
    await until(lambda: cul.state.connected)
    for line in ["", "T1C500026334", "\x00\x01", "K123456789012", "T1C50002633"]:
        fake.feed(line)
    fake.feed("T1C504169284A")
    await until(lambda: events)
    # the K frame and the truncated FHT frame (no RSSI, reads as FHT80TF state 0x26)
    assert cul.state.dropped == 2
    assert [e.protocol for e in events] == ["fht"]
    assert cul.state.connected
    await cul.stop()


async def test_reconnect_after_failures_and_drop():
    fake = FakeTransport(ANSWERS, connect_failures=2)
    cul, _, states = make(fake)
    await cul.start()
    await until(lambda: cul.state.connected)
    assert fake.connects == 3
    fake.drop()
    await until(lambda: fake.connects == 4 and cul.state.connected)
    first_true = states.index(True)
    assert False in states[first_true:]
    assert states[-1] is True
    await cul.stop()


async def test_write_without_connection_raises():
    cul, _, _ = make(FakeTransport(ANSWERS))
    with pytest.raises(ConnectionError):
        await cul.write("T1C504128")


async def test_probe():
    fake = FakeTransport(ANSWERS)
    fake.feed("T1C504169284A")  # RF noise before answers is ignored
    assert await probe(fake, timeout=0.5) == ("V 1.67 CUL868", "1034")


async def test_callback_exception_does_not_kill_connection():
    fake = FakeTransport(ANSWERS)
    seen = []

    def boom(event):
        seen.append(event)
        if len(seen) == 1:
            raise RuntimeError("boom")

    cul = Cul(lambda: fake, fhtid="1034", on_event=boom, reconnect_min=0.01,
              reconnect_max=0.02, query_timeout=0.2)
    await cul.start()
    await until(lambda: cul.state.connected)
    fake.feed("T1C504169284A")
    fake.feed("T1C504169284A")
    await until(lambda: len(seen) == 2)
    assert cul.state.connected
    assert fake.connects == 1
    await cul.stop()


async def test_idle_heartbeat_answered_stays_connected():
    fake = FakeTransport(ANSWERS)
    cul, _, _ = make(fake, idle_timeout=0.05)
    await cul.start()
    await until(lambda: cul.state.connected)
    await until(lambda: fake.written.count("V") >= 3)
    assert cul.state.connected
    assert fake.connects == 1
    await cul.stop()


async def test_idle_heartbeat_unanswered_reconnects():
    fake = FakeTransport(ANSWERS)
    cul, _, states = make(fake, idle_timeout=0.05)
    await cul.start()
    await until(lambda: cul.state.connected)
    version = fake.answers.pop("V")  # half-open: nothing comes back any more
    await until(lambda: fake.connects >= 2)
    fake.answers["V"] = version
    await until(lambda: cul.state.connected and fake.written.count("X21") >= 2)
    assert False in states
    await cul.stop()
