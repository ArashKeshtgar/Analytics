"""The event feed from IntegrationHub (its docs/events.md, schema version 1).

Each message is checked against a strict allow-list before anything is kept: a field that does
not look like what the contract says it is (a pseudonym that is not 64 hex characters, an order id
with a space in it) rejects the whole event, and the rejection records a reason code, never the
value.
Fields the contract does not know are dropped, not stored. Valid events are written in batches, as
Parquet files, and only then acknowledged, so a crash loses nothing and a repeat is harmless (the
warehouse keeps one row per event id).

Only the operational events are kept. `finance.document` is ignored: the money comes from
FinancePowerApp's database, and counting it twice would be wrong.
"""

import contextlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pika
import pika.exceptions
import polars as pl
from pika.adapters.blocking_connection import BlockingChannel

from analytics.settings import Settings

SCHEMA_VERSION = 1
OPERATIONAL_TYPES = frozenset(
    {
        "order.placed",
        "order.accepted",
        "order.cancelled",
        "order.cancel-refused",
        "result.final",
        "result.amended",
    }
)
IGNORED_TYPES = frozenset({"finance.document"})

EVENT_COLUMNS: dict[str, Any] = {
    "event_id": pl.String,
    "schema_version": pl.Int32,
    "type": pl.String,
    "occurred_at": pl.Datetime("us"),
    "clinic_slug": pl.String,
    "application": pl.String,
    "order_id": pl.String,
    "test_code_system": pl.String,
    "test_code": pl.String,
    "priority": pl.String,
    "status": pl.String,
    "patient_pseudonym": pl.String,
    "received_at": pl.Datetime("us"),
}

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
_ORDER_ID = re.compile(r"^service-request\|[A-Za-z0-9._-]{1,100}$")
_CODE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_SYSTEM = re.compile(r"^[A-Za-z0-9:/._#-]{1,200}$")
_STATUS = re.compile(r"^[a-z-]{1,30}$")
_PSEUDONYM = re.compile(r"^[0-9a-f]{64}$")
_PRIORITIES = frozenset({"routine", "urgent", "asap", "stat"})


class Rejected(Exception):
    """The event cannot be stored. `reason` is a short code, safe to write down."""

    def __init__(self, reason: str, event_id: str | None = None, type_: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.event_id = event_id
        self.type = type_


class Ignored(Exception):
    """A valid event of a kind Analytics does not use."""


def _text(
    raw: dict[str, Any], name: str, pattern: re.Pattern[str], *, required: bool
) -> str | None:
    value = raw.get(name)
    if value is None:
        if required:
            raise Rejected(f"missing-{name}")
        return None
    if not isinstance(value, str) or not pattern.match(value):
        raise Rejected(f"bad-{name}")
    return value


def parse_event(body: bytes, received_at: datetime) -> dict[str, Any]:
    """The row to store (only EVENT_COLUMNS), or raises Rejected / Ignored."""
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise Rejected("invalid-json") from None
    if not isinstance(raw, dict):
        raise Rejected("invalid-json")

    type_ = raw.get("type")
    safe_type = type_ if isinstance(type_, str) and _CODE.match(type_) else None
    event_id = raw.get("eventId")
    try:
        parsed_id = str(uuid.UUID(str(event_id)))
    except ValueError:
        raise Rejected("bad-eventId", type_=safe_type) from None

    def reject(reason: str) -> Rejected:
        return Rejected(reason, parsed_id, safe_type)

    version = raw.get("schemaVersion")
    if version != SCHEMA_VERSION or isinstance(version, bool):
        raise reject("unsupported-schema-version")
    if type_ in IGNORED_TYPES:
        raise Ignored
    if type_ not in OPERATIONAL_TYPES:
        raise reject("unknown-type")
    try:
        occurred = datetime.fromisoformat(str(raw.get("occurredAt")).replace("Z", "+00:00"))
    except ValueError:
        raise reject("bad-occurredAt") from None
    if occurred.tzinfo is None:
        raise reject("bad-occurredAt")

    try:
        priority = raw.get("priority")
        if priority is not None and priority not in _PRIORITIES:
            raise Rejected("bad-priority")
        pseudonym = _text(raw, "patientPseudonym", _PSEUDONYM, required=False)
        return {
            "event_id": parsed_id,
            "schema_version": SCHEMA_VERSION,
            "type": type_,
            "occurred_at": occurred.astimezone(UTC).replace(tzinfo=None),
            "clinic_slug": _text(raw, "clinicSlug", _TOKEN, required=True),
            "application": _text(raw, "application", _TOKEN, required=True),
            "order_id": _text(raw, "orderId", _ORDER_ID, required=True),
            "test_code_system": _text(raw, "testCodeSystem", _SYSTEM, required=False),
            "test_code": _text(raw, "testCode", _CODE, required=False),
            "priority": priority,
            "status": _text(raw, "status", _STATUS, required=False),
            "patient_pseudonym": pseudonym,
            "received_at": received_at.astimezone(UTC).replace(tzinfo=None),
        }
    except Rejected as e:
        raise reject(e.reason) from None


# ---- files -------------------------------------------------------------------------------------


def events_dir(settings: Settings) -> Path:
    return settings.data_dir / "raw" / "events"


def write_batch(
    settings: Settings, rows: list[dict[str, Any]], rejects: list[dict[str, Any]]
) -> None:
    """Write one Parquet file of events and one JSON-lines file of rejections, each atomically."""
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    directory = events_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    if rows:
        final = directory / f"events-{stamp}.parquet"
        temp = directory / f".{final.name}.tmp"
        pl.DataFrame(rows, schema=EVENT_COLUMNS).write_parquet(temp)
        _sync(temp)
        os.replace(temp, final)
    if rejects:
        folder = directory / "rejected"
        folder.mkdir(exist_ok=True)
        final = folder / f"rejected-{stamp}.jsonl"
        temp = folder / f".{final.name}.tmp"
        temp.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rejects), encoding="utf-8"
        )
        _sync(temp)
        os.replace(temp, final)


def _sync(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


# ---- consumer ----------------------------------------------------------------------------------


class ConsumerError(Exception):
    """The broker cannot be reached or refused us. The message never contains the connection URL."""


@dataclass
class ConsumeResult:
    stored: int = 0
    rejected: int = 0
    ignored: int = 0
    batches: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


Writer = Callable[[Settings, list[dict[str, Any]], list[dict[str, Any]]], None]


def ensure_topology(channel: BlockingChannel, settings: Settings) -> None:
    """Declare what IntegrationHub declares, the same way (durable, no arguments): idempotent."""
    channel.exchange_declare(
        exchange=settings.rabbitmq_exchange, exchange_type="topic", durable=True
    )
    channel.queue_declare(queue=settings.rabbitmq_queue, durable=True)
    channel.queue_bind(
        queue=settings.rabbitmq_queue, exchange=settings.rabbitmq_exchange, routing_key="#"
    )


def consume(
    settings: Settings,
    *,
    drain: bool = False,
    stop: threading.Event | None = None,
    writer: Writer = write_batch,
) -> ConsumeResult:
    """Read events until `stop` is set, or, with `drain`, until the queue is empty.

    A batch is acknowledged only after `writer` returned. If the writer raises, nothing of the
    batch is acknowledged, the error propagates and the broker gives the messages out again.
    """
    result = ConsumeResult()
    try:
        connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    except pika.exceptions.AMQPError as e:
        raise ConsumerError(f"cannot connect to RabbitMQ ({type(e).__name__})") from None
    try:
        channel = connection.channel()
        ensure_topology(channel, settings)
        channel.basic_qos(prefetch_count=settings.consume_batch_size)
        _loop(channel, settings, result, drain, stop, writer)
    except pika.exceptions.AMQPError as e:
        raise ConsumerError(f"RabbitMQ failed ({type(e).__name__})") from None
    finally:
        with contextlib.suppress(pika.exceptions.AMQPError):
            connection.close()
    return result


def _loop(
    channel: BlockingChannel,
    settings: Settings,
    result: ConsumeResult,
    drain: bool,
    stop: threading.Event | None,
    writer: Writer,
) -> None:
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    last_tag: int | None = None
    first_at = 0.0

    def flush() -> None:
        nonlocal rows, rejects, last_tag
        if last_tag is None:
            return
        writer(settings, rows, rejects)
        channel.basic_ack(delivery_tag=last_tag, multiple=True)
        result.stored += len(rows)
        result.rejected += len(rejects)
        result.batches += 1
        rows, rejects, last_tag = [], [], None

    try:
        for method, _properties, body in channel.consume(
            settings.rabbitmq_queue, inactivity_timeout=0.5
        ):
            if stop is not None and stop.is_set():
                break
            if method is None:
                waited = time.monotonic() - first_at
                if last_tag is not None and (drain or waited >= settings.consume_flush_seconds):
                    flush()
                if drain and last_tag is None and _queue_is_empty(channel, settings):
                    break
                continue
            if last_tag is None:
                first_at = time.monotonic()
            last_tag = method.delivery_tag
            try:
                rows.append(parse_event(body, datetime.now(UTC)))
            except Ignored:
                result.ignored += 1
            except Rejected as e:
                rejects.append(
                    {
                        "received_at": datetime.now(UTC).isoformat(),
                        "reason": e.reason,
                        "event_id": e.event_id,
                        "type": e.type,
                    }
                )
                result.reasons[e.reason] = result.reasons.get(e.reason, 0) + 1
            if len(rows) + len(rejects) >= settings.consume_batch_size:
                flush()
        flush()
    finally:
        channel.cancel()


def _queue_is_empty(channel: BlockingChannel, settings: Settings) -> bool:
    declared = channel.queue_declare(queue=settings.rabbitmq_queue, passive=True)
    return int(declared.method.message_count) == 0


def run_forever(settings: Settings, stop: threading.Event) -> None:
    """Keep consuming, reconnecting with a growing pause when the broker goes away."""
    pause = 1.0
    while not stop.is_set():
        try:
            consume(settings, stop=stop)
            return
        except ConsumerError as e:
            print(f"{e}; retrying in {pause:.0f} s", flush=True)
            stop.wait(pause)
            pause = min(pause * 2, 60.0)
