"""Tests for the FHT send queue."""

import asyncio

from custom_components.cul.culpy.cul import Cul
from custom_components.cul.culpy.protocols.base import DeviceEvent
from custom_components.cul.culpy.protocols.fht import encode_value
from custom_components.cul.culpy.sendqueue import CommandFailed, FhtSendQueue
from custom_components.cul.culpy.transport.fake import FakeTransport

ANSWERS = {"V": "V 1.67 CUL868", "T01": "1034", "T03": "FF", "X": "21  900"}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def connected(answers=ANSWERS):
    fake = FakeTransport(answers)
    cul = Cul(lambda: fake, fhtid="1034", query_timeout=0.2)
    await cul.start()
    async with asyncio.timeout(2):
        while not cul.state.connected:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
    fake.written.clear()
    return cul, fake


def sent(fake):
    return [w for w in fake.written if w.startswith("T1C50")]


async def test_send_and_coalesce():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", encode_value("desired-temp", 20.0))])
    q.submit("1c50", [("desired-temp", encode_value("desired-temp", 21.0))])
    assert q.pending_for("1c50") == {"desired-temp": 42}
    assert await q.pump() is True
    assert sent(fake) == ["T1C50412A"]
    assert await q.pump() is False  # already sent, waits for ack
    await cul.stop()


async def test_priority_order_and_batch():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("night-temp", 34), ("minute", 5), ("desired-temp", 40)])
    await q.pump()
    assert sent(fake) == ["T1C50640541288422"]
    await cul.stop()


async def test_buffer_too_small():
    cul, fake = await connected({**ANSWERS, "T03": "04"})
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", 40)])  # needs 5 bytes
    assert await q.pump() is False
    assert sent(fake) == []
    await cul.stop()


async def test_lovf_pauses():
    cul, fake = await connected({**ANSWERS, "X": "21  0"})
    clock = Clock()
    q = FhtSendQueue(cul, clock=clock, lovf_pause=60)
    cul.state.lovf = True
    q.submit("1c50", [("desired-temp", 40)])
    assert await q.pump() is False
    fake.answers["X"] = "21  900"
    clock.now = 30
    assert await q.pump() is False  # still paused
    clock.now = 61
    assert await q.pump() is True
    await cul.stop()


async def test_ack_matches_encoded_value():
    cul, _ = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", encode_value("desired-temp", 20.25))])
    await q.pump()
    assert q.on_event(DeviceEvent("fht", "1c50", {"desired-temp": 20.0})) == ["desired-temp"]
    assert q.pending_for("1c50") == {}
    await cul.stop()


async def test_no_ack_keys_done_after_send():
    cul, _ = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("report1", 255), ("report2", 255)])
    await q.pump()
    assert q.pending_for("1c50") == {}
    await cul.stop()


async def test_expire():
    cul, _ = await connected()
    clock = Clock()
    q = FhtSendQueue(cul, clock=clock, ack_timeout=900)
    q.submit("1c50", [("desired-temp", 40)])
    await q.pump()
    clock.now = 899
    assert q.expire() == []
    clock.now = 901
    assert q.expire() == [CommandFailed("1c50", "desired-temp", 40)]
    assert q.pending_for("1c50") == {}
    await cul.stop()


async def test_pump_without_connection_is_noop():
    cul = Cul(lambda: FakeTransport(ANSWERS))
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", 40)])
    assert await q.pump() is False


async def test_submit_during_pump_is_not_lost():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", 40)])
    orig = cul.refresh_status

    async def refresh():
        await orig()
        q.submit("1c50", [("desired-temp", 44)])

    cul.refresh_status = refresh
    assert await q.pump() is True
    assert sent(fake) == ["T1C504128"]
    cul.refresh_status = orig
    assert await q.pump() is True  # newer value still unsent
    assert sent(fake) == ["T1C504128", "T1C50412C"]
    await cul.stop()


async def test_no_ack_submit_during_pump_is_not_deleted():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("report1", 255)])
    orig = cul.refresh_status

    async def refresh():
        await orig()
        q.submit("1c50", [("report1", 0)])

    cul.refresh_status = refresh
    await q.pump()
    assert q.pending_for("1c50") == {"report1": 0}
    await cul.stop()


async def test_entry_removed_during_pump_no_keyerror():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock(), ack_timeout=10)
    clock = q._clock
    q.submit("1c50", [("desired-temp", 40), ("report1", 255)])
    orig = cul.refresh_status

    async def refresh():
        await orig()
        clock.now = 100
        q.expire()

    cul.refresh_status = refresh
    assert await q.pump() is True
    assert q.pending_for("1c50") == {}
    await cul.stop()


async def test_real_lovf_line_pauses_even_with_credit():
    cul, fake = await connected()
    clock = Clock()
    q = FhtSendQueue(cul, clock=clock, lovf_pause=60)
    fake.feed("LOVF")
    async with asyncio.timeout(2):
        while not cul.state.lovf:  # noqa: ASYNC110
            await asyncio.sleep(0.005)
    q.submit("1c50", [("desired-temp", 40)])
    assert await q.pump() is False
    clock.now = 30
    assert await q.pump() is False
    assert sent(fake) == []
    clock.now = 61
    assert await q.pump() is True
    await cul.stop()


async def test_buffer_fits_one_item_sends_one():
    cul, fake = await connected({**ANSWERS, "T03": "05"})  # 5 bytes: 3 + 2 * 1
    q = FhtSendQueue(cul, clock=Clock())
    q.submit("1c50", [("desired-temp", 40), ("mode", 1), ("day-temp", 42)])
    assert await q.pump() is True
    assert sent(fake) == ["T1C504128"]
    assert sorted(k for k, _ in q.pending_for("1c50").items()) == ["day-temp", "desired-temp", "mode"]
    await cul.stop()


async def test_blocked_address_does_not_block_other():
    cul, fake = await connected()
    q = FhtSendQueue(cul, clock=Clock(), can_send=lambda a: a != "1c50")
    q.submit("1c50", [("desired-temp", 40)])
    q.submit("2c50", [("desired-temp", 42)])
    assert await q.pump() is True
    assert [w for w in fake.written if w.startswith("T")] == ["T03", "T2C50412A"]
    assert await q.pump() is False  # 1c50 still waits
    assert q.pending_for("1c50") == {"desired-temp": 40}
    await cul.stop()


async def test_low_buffer_warns_once(caplog):
    cul, fake = await connected({**ANSWERS, "T03": "04"})
    clock = Clock()
    q = FhtSendQueue(cul, clock=clock)
    q.submit("1c50", [("desired-temp", 40)])
    for t in (0, 300, 601, 900, 1200):
        clock.now = t
        assert await q.pump() is False
    assert sum("buffer" in r.getMessage() for r in caplog.records if r.levelname == "WARNING") == 1
    await cul.stop()
