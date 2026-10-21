"""Reading IntegrationHub's events: what is accepted, what is refused and what is never kept.

Parsing is checked without a broker; the consumer against a real RabbitMQ (Testcontainers) set up
the way IntegrationHub sets it up: a durable topic exchange and a durable queue bound to everything.
"""

import json
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pika
import polars as pl
import pytest
from testcontainers.community.rabbitmq import RabbitMqContainer
from typer.testing import CliRunner

from analytics.cli import app
from analytics.events import (
    ConsumerError,
    Ignored,
    Rejected,
    consume,
    ensure_topology,
    events_dir,
    parse_event,
)
from analytics.settings import Settings
from analytics.warehouse import load_events
from tests import synthetic_events
from tests.conftest import make_settings

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
MARKERS = ["Zzyzx", "Testpatient", "123-456-789", "secret-note"]


def good() -> dict[str, Any]:
    return synthetic_events.event(
        "result.final", "harbourview", "101", synthetic_events.day(5, "13:30"), status="final"
    )


def parse(raw: Any) -> dict[str, Any]:
    body = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
    return parse_event(body, NOW)


# ---- parsing ------------------------------------------------------------------------------------


def test_a_valid_event_becomes_a_row_with_utc_times() -> None:
    event = good() | {"occurredAt": "2026-10-05T15:30:00+02:00"}
    row = parse(event)
    assert row["event_id"] == event["eventId"]
    assert (row["type"], row["clinic_slug"], row["application"]) == (
        "result.final",
        "harbourview",
        "labflow",
    )
    assert (row["order_id"], row["test_code"], row["priority"], row["status"]) == (
        "service-request|101",
        "718-7",
        "routine",
        "final",
    )
    assert row["occurred_at"] == datetime(2026, 10, 5, 13, 30)  # 15:30 at +02:00
    assert row["received_at"] == datetime(2026, 10, 10, 12)
    assert len(row["patient_pseudonym"]) == 64


def test_what_the_contract_does_not_name_is_dropped_not_stored() -> None:
    row = parse(
        good() | {"patientName": "Zzyzx Testpatient", "note": "secret-note", "finance": {"x": 1}}
    )
    assert set(row) == {
        "event_id",
        "schema_version",
        "type",
        "occurred_at",
        "clinic_slug",
        "application",
        "order_id",
        "test_code_system",
        "test_code",
        "priority",
        "status",
        "patient_pseudonym",
        "received_at",
    }
    assert not any(marker in json.dumps(row, default=str) for marker in MARKERS)


def test_an_event_without_a_pseudonym_or_code_is_fine() -> None:
    row = parse(
        good()
        | {"patientPseudonym": None, "testCode": None, "testCodeSystem": None, "priority": None}
    )
    assert row["patient_pseudonym"] is None and row["test_code"] is None and row["priority"] is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"schemaVersion": 2}, "unsupported-schema-version"),
        ({"schemaVersion": "1"}, "unsupported-schema-version"),
        ({"schemaVersion": True}, "unsupported-schema-version"),
        ({"schemaVersion": None}, "unsupported-schema-version"),
        ({"type": "order.exploded"}, "unknown-type"),
        ({"type": None}, "unknown-type"),
        ({"occurredAt": "yesterday"}, "bad-occurredAt"),
        ({"occurredAt": "2026-10-05T13:30:00"}, "bad-occurredAt"),
        ({"occurredAt": None}, "bad-occurredAt"),
        ({"clinicSlug": None}, "missing-clinicSlug"),
        ({"clinicSlug": "Harbour View"}, "bad-clinicSlug"),
        ({"application": "lab flow"}, "bad-application"),
        ({"orderId": None}, "missing-orderId"),
        ({"orderId": "101"}, "bad-orderId"),
        ({"orderId": "service-request|Zzyzx Testpatient"}, "bad-orderId"),
        ({"patientPseudonym": "123-456-789"}, "bad-patientPseudonym"),
        ({"patientPseudonym": "Zzyzx Testpatient"}, "bad-patientPseudonym"),
        ({"patientPseudonym": "A" * 64}, "bad-patientPseudonym"),
        ({"patientPseudonym": 12345}, "bad-patientPseudonym"),
        ({"priority": "very urgent"}, "bad-priority"),
        ({"testCode": "718 7; drop table"}, "bad-testCode"),
        ({"testCodeSystem": "has a space"}, "bad-testCodeSystem"),
        ({"status": "Final Report"}, "bad-status"),
        ({"eventId": "not-a-uuid"}, "bad-eventId"),
        ({"eventId": None}, "bad-eventId"),
    ],
)
def test_an_event_that_does_not_look_like_the_contract_is_rejected_by_code(
    change: dict[str, Any], reason: str
) -> None:
    with pytest.raises(Rejected) as caught:
        parse(good() | change)
    assert caught.value.reason == reason
    # the error says what was wrong, never what was in the field
    shown = f"{caught.value} {caught.value.reason} {caught.value.event_id} {caught.value.type}"
    assert not any(marker in shown for marker in MARKERS)


@pytest.mark.parametrize(
    "body", [b"not json", b"\xff\xfe", b"[1, 2]", b'"text"', b"42", b"null", b""]
)
def test_a_body_that_is_not_a_json_object_is_rejected(body: bytes) -> None:
    with pytest.raises(Rejected) as caught:
        parse(body)
    assert caught.value.reason == "invalid-json"


def test_a_rejection_keeps_the_id_and_type_only_when_they_are_well_formed() -> None:
    with pytest.raises(Rejected) as caught:
        parse(good() | {"schemaVersion": 2})
    assert caught.value.event_id == good()["eventId"] and caught.value.type == "result.final"
    with pytest.raises(Rejected) as caught:
        parse(good() | {"eventId": "x", "type": "Zzyzx Testpatient"})
    assert caught.value.event_id is None and caught.value.type is None


def test_finance_documents_are_ignored_not_stored() -> None:
    finance = good() | {
        "type": "finance.document",
        "orderId": None,
        "clinicSlug": None,
        "finance": {"sourceKey": "harbourview", "externalId": "x", "kind": "Invoice"},
    }
    with pytest.raises(Ignored):
        parse(finance)
    # ...but a future schema version is refused even for them
    with pytest.raises(Rejected):
        parse(finance | {"schemaVersion": 2})


# ---- the consumer, against a real broker --------------------------------------------------------


@pytest.fixture(scope="module")
def rabbit() -> Iterator[RabbitMqContainer]:
    with RabbitMqContainer("rabbitmq:3.13-management-alpine") as container:
        yield container


class Hub:
    """What IntegrationHub does: a durable topic exchange and queue, persistent publishing."""

    def __init__(self, rabbit: RabbitMqContainer, settings: Settings) -> None:
        self.settings = settings
        self.connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
        self.channel = self.connection.channel()
        self.channel.exchange_declare(settings.rabbitmq_exchange, "topic", durable=True)
        self.channel.queue_declare(settings.rabbitmq_queue, durable=True)
        self.channel.queue_bind(settings.rabbitmq_queue, settings.rabbitmq_exchange, "#")

    def publish(self, event: dict[str, Any] | bytes) -> None:
        body = event if isinstance(event, bytes) else json.dumps(event).encode()
        kind = "x" if isinstance(event, bytes) else str(event.get("type"))
        self.channel.basic_publish(
            self.settings.rabbitmq_exchange,
            kind,
            body,
            pika.BasicProperties(content_type="application/json", delivery_mode=2),
        )

    def waiting(self) -> int:
        return int(
            self.channel.queue_declare(
                self.settings.rabbitmq_queue, passive=True
            ).method.message_count
        )

    def purge(self) -> None:
        self.channel.queue_purge(self.settings.rabbitmq_queue)

    def close(self) -> None:
        self.connection.close()


@pytest.fixture
def hub(rabbit: RabbitMqContainer, tmp_path: Path) -> Iterator[Hub]:
    url = f"amqp://guest:guest@{rabbit.get_container_host_ip()}:{rabbit.get_exposed_port(5672)}/"
    settings = make_settings(tmp_path, rabbitmq_url=url, consume_flush_seconds=0.2)
    h = Hub(rabbit, settings)
    h.purge()
    yield h
    h.purge()
    h.close()


def stored(settings: Settings) -> pl.DataFrame:
    files = sorted(events_dir(settings).glob("events-*.parquet"))
    return pl.concat([pl.read_parquet(f) for f in files]) if files else pl.DataFrame()


def rejected_lines(settings: Settings) -> list[dict[str, Any]]:
    folder = events_dir(settings) / "rejected"
    lines = [line for f in sorted(folder.glob("*.jsonl")) for line in f.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def everything_on_disk(settings: Settings) -> bytes:
    return b"".join(p.read_bytes() for p in events_dir(settings).rglob("*") if p.is_file())


def test_it_reads_what_is_waiting_writes_it_and_acknowledges_it(hub: Hub) -> None:
    events = synthetic_events.all_events()
    for e in events:
        hub.publish(e)

    result = consume(hub.settings, drain=True)

    assert (result.stored, result.rejected, result.ignored) == (len(events), 0, 0)
    df = stored(hub.settings)
    assert df.height == len(events)
    assert set(df["event_id"]) == {e["eventId"] for e in events}
    assert df.schema["occurred_at"] == pl.Datetime("us")
    assert hub.waiting() == 0  # acknowledged: nothing comes back


def test_a_batch_is_as_big_as_the_setting(hub: Hub) -> None:
    settings = hub.settings.model_copy(update={"consume_batch_size": 3})
    for e in synthetic_events.all_events()[:7]:
        hub.publish(e)

    result = consume(settings, drain=True)

    assert (result.stored, result.batches) == (7, 3)
    assert len(list(events_dir(settings).glob("events-*.parquet"))) == 3


def test_a_repeated_event_is_one_row_in_the_warehouse(hub: Hub) -> None:
    event = good()
    for _ in range(3):
        hub.publish(event)

    result = consume(hub.settings, drain=True)

    assert result.stored == 3  # at least once: the files hold it three times
    con = duckdb.connect(":memory:")
    assert load_events(hub.settings, con) == 1
    assert con.execute("select count(*) from raw.clinical_event").fetchone() == (1,)


def test_refused_events_are_counted_by_reason_and_leave_no_trace_of_their_content(hub: Hub) -> None:
    bad_pseudonym = good() | {
        "eventId": "7e1c5f3a-0000-4000-8000-000000000001",
        "patientPseudonym": "Zzyzx Testpatient 123-456-789",
    }
    future = good() | {
        "eventId": "7e1c5f3a-0000-4000-8000-000000000002",
        "schemaVersion": 2,
        "note": "secret-note",
    }
    finance = good() | {
        "type": "finance.document",
        "eventId": "7e1c5f3a-0000-4000-8000-000000000003",
    }
    hub.publish(good())
    hub.publish(bad_pseudonym)
    hub.publish(future)
    hub.publish(b"Zzyzx Testpatient is not json")
    hub.publish(finance)

    result = consume(hub.settings, drain=True)

    assert (result.stored, result.rejected, result.ignored) == (1, 3, 1)
    assert result.reasons == {
        "bad-patientPseudonym": 1,
        "unsupported-schema-version": 1,
        "invalid-json": 1,
    }
    assert hub.waiting() == 0  # refused events are acknowledged too: they would never get better
    lines = rejected_lines(hub.settings)
    assert sorted(line["reason"] for line in lines) == sorted(
        result.reasons.elements()
        if False
        else ["bad-patientPseudonym", "invalid-json", "unsupported-schema-version"]
    )
    assert {line["event_id"] for line in lines} >= {bad_pseudonym["eventId"], future["eventId"]}
    disk = everything_on_disk(hub.settings)
    assert not any(marker.encode() in disk for marker in MARKERS)


def test_a_field_the_contract_does_not_know_never_reaches_the_disk(hub: Hub) -> None:
    hub.publish(good() | {"patientName": "Zzyzx Testpatient", "healthCard": "123-456-789"})

    consume(hub.settings, drain=True)

    assert stored(hub.settings).height == 1
    assert "patientName" not in stored(hub.settings).columns
    assert not any(marker.encode() in everything_on_disk(hub.settings) for marker in MARKERS)


def test_if_the_batch_cannot_be_written_nothing_is_acknowledged(hub: Hub) -> None:
    for e in synthetic_events.all_events()[:5]:
        hub.publish(e)

    def broken(*args: object) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        consume(hub.settings, drain=True, writer=broken)

    # the broker gives them out again: five messages are still there
    deadline = time.monotonic() + 5
    while hub.waiting() != 5 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert hub.waiting() == 5
    assert consume(hub.settings, drain=True).stored == 5


def test_it_keeps_reading_until_told_to_stop(hub: Hub) -> None:
    stop = threading.Event()
    results: list[Any] = []
    thread = threading.Thread(target=lambda: results.append(consume(hub.settings, stop=stop)))
    thread.start()
    try:
        time.sleep(1)  # nothing waiting yet
        for e in synthetic_events.all_events()[:4]:
            hub.publish(e)
        deadline = time.monotonic() + 15
        while stored(hub.settings).height < 4 and time.monotonic() < deadline:
            time.sleep(0.2)
        assert stored(hub.settings).height == 4
    finally:
        stop.set()
        thread.join(timeout=15)
    assert not thread.is_alive() and results[0].stored == 4
    assert hub.waiting() == 0


def test_declaring_the_queue_again_changes_nothing(hub: Hub) -> None:
    for e in synthetic_events.all_events()[:2]:
        hub.publish(e)
    channel = hub.connection.channel()
    ensure_topology(channel, hub.settings)
    ensure_topology(channel, hub.settings)
    assert hub.waiting() == 2


QUEUE_ONLY = r"^analytics\.clinical-events$"
QUEUE_AND_EXCHANGE = r"^(analytics\.clinical-events|clinical\.events)$"


def account(rabbit: RabbitMqContainer, name: str, configure: str, write: str, read: str) -> str:
    """A RabbitMQ account other than guest (which only works from the broker's own host)."""
    for command in (
        ["rabbitmqctl", "add_user", name, "pw-" + name],
        ["rabbitmqctl", "set_permissions", "-p", "/", name, configure, write, read],
    ):
        exit_code, output = rabbit.exec(command)
        assert exit_code == 0, output
    return (
        f"amqp://{name}:pw-{name}@{rabbit.get_container_host_ip()}:{rabbit.get_exposed_port(5672)}/"
    )


def test_the_documented_account_is_enough_and_needs_nothing_on_the_exchange_but_read(
    hub: Hub, rabbit: RabbitMqContainer
) -> None:
    url = account(rabbit, "analytics-ok", QUEUE_ONLY, QUEUE_ONLY, QUEUE_AND_EXCHANGE)
    hub.publish(good())

    result = consume(hub.settings.model_copy(update={"rabbitmq_url": url}), drain=True)

    assert result.stored == 1 and hub.waiting() == 0


def test_without_write_on_the_queue_the_binding_is_refused_with_a_plain_message(
    hub: Hub, rabbit: RabbitMqContainer
) -> None:
    url = account(rabbit, "analytics-nowrite", QUEUE_ONLY, "", QUEUE_AND_EXCHANGE)

    with pytest.raises(ConsumerError) as caught:
        consume(hub.settings.model_copy(update={"rabbitmq_url": url}), drain=True)

    assert "refused access (403)" in str(caught.value)
    assert "analytics-nowrite" not in str(caught.value) and "pw-" not in str(caught.value)


def test_before_the_hub_has_made_the_exchange_the_error_says_so(hub: Hub) -> None:
    settings = hub.settings.model_copy(
        update={"rabbitmq_exchange": "not.yet.declared", "rabbitmq_queue": "analytics.not-yet"}
    )

    with pytest.raises(ConsumerError, match="HUB_EVENTS_ENABLED=true"):
        consume(settings, drain=True)


def test_an_unreachable_broker_is_an_error_that_does_not_show_the_url_or_password(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path, rabbitmq_url="amqp://someuser:s3cretpw@127.0.0.1:1/")
    with pytest.raises(ConsumerError) as caught:
        consume(settings, drain=True)
    assert "s3cretpw" not in str(caught.value) and "someuser" not in str(caught.value)

    result = CliRunner().invoke(
        app,
        ["consume", "--drain"],
        env={"ANALYTICS_RABBITMQ_URL": settings.rabbitmq_url, "ANALYTICS_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 2
    assert "s3cretpw" not in result.output and "someuser" not in result.output


def test_the_command_reports_what_it_did(hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    hub.publish(good())
    hub.publish(
        good() | {"eventId": "7e1c5f3a-0000-4000-8000-000000000009", "priority": "whenever"}
    )
    monkeypatch.setenv("ANALYTICS_RABBITMQ_URL", hub.settings.rabbitmq_url)
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(hub.settings.data_dir))

    result = CliRunner().invoke(app, ["consume", "--drain"])

    assert result.exit_code == 0, result.output
    assert "stored 1, rejected 1, ignored 0, batches 1" in result.output
    assert "rejected: bad-priority x1" in result.output
