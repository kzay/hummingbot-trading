import time

from services.contracts.event_schemas import ExecutionIntentEvent
from services.contracts.stream_names import EXECUTION_INTENT_STREAM
from services.hb_bridge.intent_consumer import HBIntentConsumer


class _FakeRedis:
    def __init__(self):
        self.enabled = True
        self._entries = []
        self.acked = []
        self.dead_letter = []

    def create_group(self, stream: str, group: str) -> None:
        return None

    def read_group(self, stream: str, group: str, consumer: str, count: int = 10, block_ms: int = 1000):
        out = self._entries[:count]
        self._entries = self._entries[count:]
        return out

    def xadd(self, stream: str, payload, maxlen=None):
        self.dead_letter.append((stream, payload))
        return "1-0"

    def ack(self, stream: str, group: str, entry_id: str) -> None:
        self.acked.append((stream, group, entry_id))


def _intent(event_id: str, expires_at_ms=None):
    return ExecutionIntentEvent(
        producer="coord",
        event_id=event_id,
        instance_name="bot1",
        controller_id="epp_v2_4",
        action="resume",
        expires_at_ms=expires_at_ms,
    ).model_dump()


def test_deduplicates_same_event_id():
    fake = _FakeRedis()
    consumer = HBIntentConsumer(fake, group="g1", consumer_name="c1", dedup_ttl_sec=60)
    fake._entries = [("1-0", _intent("same-id")), ("2-0", _intent("same-id"))]
    first = consumer.poll()
    assert len(first) == 1
    consumer.ack(first[0][0], first[0][1].event_id)
    second = consumer.poll()
    assert len(second) == 0


def test_expired_intents_go_dead_letter():
    fake = _FakeRedis()
    consumer = HBIntentConsumer(fake, group="g1", consumer_name="c1", dedup_ttl_sec=60)
    fake._entries = [("1-0", _intent("expired-id", int(time.time() * 1000) - 1))]
    out = consumer.poll()
    assert out == []
    assert fake.dead_letter, "expired intent should be written to dead letter stream"
    assert fake.acked[0][0] == EXECUTION_INTENT_STREAM

