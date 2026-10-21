"""A day-by-day set of events the way IntegrationHub publishes them (its docs/events.md), with
turnaround times that can be worked out by hand.

October 2026. Harbourview (HV) orders, all labflow ("Lab") unless noted:
  101  718-7   routine  placed 10-05 09:00, result 13:30                  270 min
  102  2160-0  urgent   placed 10-05 09:00, result 10:00                   60 min  (its result event arrives
                                                                                   before its order events)
  103  718-7   routine  placed 10-06 08:00, result 18:00, amended 10-07   600 min
  104  718-7   routine  placed 10-07 08:00, cancelled 09:00                cancelled
  105  2160-0  routine  placed 10-08 08:00, result 08:45, cancel refused 09:00   45 min
  106  echo    routine  clinicreport ("Diagnostics"), placed 10-06 10:00, result 10-08 10:00   2880 min
  107  718-7   routine  placed 10-09 08:00, accepted only                 waiting
  108  718-7   stat     placed 10-09 08:00, the lab refused it           placed only
  999  (a result for an order the hub never saw)                          no turnaround
Lakeshore (LS): 201  718-7 routine, labflow, placed 10-05 09:00, result 10:00   60 min.
Patients: 101 and 103 are one patient, the others differ.

Expected, Harbourview, department Lab:  placed 7, resulted 4 (45, 60, 270, 600), cancelled 1, waiting 2,
  median 165, p90 501.  By test: 718-7 placed 5, resulted 2 (270, 600): median 435, p90 567;
  2160-0 placed 2, resulted 2 (45, 60): median 52.5, p90 58.5.
Diagnostics: placed 1, resulted 1, median and p90 2880.
Everything (HV + LS): placed 9, resulted 6 (45, 60, 60, 270, 600, 2880), median 165, p90 1740.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from analytics.events import parse_event, write_batch
from analytics.settings import Settings

NS = uuid.UUID("6f1e3f0e-2b8b-4f3a-9a52-0d7a2f0c1b11")
LOINC = "http://loinc.org"


def pseudonym(patient: str) -> str:
    import hashlib

    return hashlib.sha256(f"synthetic|{patient}".encode()).hexdigest()


def event(
    type_: str,
    clinic: str,
    order: str,
    at: str,
    *,
    application: str = "labflow",
    code: str | None = "718-7",
    system: str | None = LOINC,
    priority: str | None = "routine",
    status: str | None = None,
    patient: str | None = "P1",
) -> dict[str, Any]:
    """One event as the hub publishes it. The id is derived from the content, like the hub's."""
    return {
        "schemaVersion": 1,
        "eventId": str(uuid.uuid5(NS, f"{type_}|{clinic}|{order}|{at}")),
        "type": type_,
        "occurredAt": datetime.fromisoformat(at).isoformat().replace("+00:00", "Z"),
        "clinicSlug": clinic,
        "application": application,
        "orderId": f"service-request|{order}",
        "testCodeSystem": system,
        "testCode": code,
        "priority": priority,
        "status": status,
        "patientPseudonym": pseudonym(patient) if patient else None,
        "finance": None,
    }


def day(d: int, hhmm: str) -> str:
    return f"2026-10-{d:02d}T{hhmm}:00+00:00"


def order_events(order: str, clinic: str, placed: str, **kw: Any) -> list[dict[str, Any]]:
    placed_at = datetime.fromisoformat(placed)
    accepted = placed_at.replace(second=5).isoformat()
    return [
        event("order.placed", clinic, order, placed, status="active", **kw),
        event("order.accepted", clinic, order, accepted, status="active", **kw),
    ]


def all_events() -> list[dict[str, Any]]:
    hv = "harbourview"
    out: list[dict[str, Any]] = []
    out += order_events("101", hv, day(5, "09:00"), patient="P1")
    out.append(event("result.final", hv, "101", day(5, "13:30"), status="final", patient="P1"))
    # 102: the result is delivered before the order's own events
    out.append(
        event(
            "result.final",
            hv,
            "102",
            day(5, "10:00"),
            code="2160-0",
            priority="urgent",
            status="final",
            patient="P2",
        )
    )
    out += order_events("102", hv, day(5, "09:00"), code="2160-0", priority="urgent", patient="P2")
    out += order_events("103", hv, day(6, "08:00"), patient="P1")
    out.append(event("result.final", hv, "103", day(6, "18:00"), status="final", patient="P1"))
    out.append(event("result.amended", hv, "103", day(7, "08:00"), status="amended", patient="P1"))
    out += order_events("104", hv, day(7, "08:00"), patient="P3")
    out.append(event("order.cancelled", hv, "104", day(7, "09:00"), status="revoked", patient="P3"))
    out += order_events("105", hv, day(8, "08:00"), code="2160-0", patient="P4")
    out.append(
        event(
            "result.final", hv, "105", day(8, "08:45"), code="2160-0", status="final", patient="P4"
        )
    )
    out.append(
        event(
            "order.cancel-refused",
            hv,
            "105",
            day(8, "09:00"),
            code="2160-0",
            status="revoked",
            patient="P4",
        )
    )
    echo = {"application": "clinicreport", "code": "echo-tte", "system": None, "patient": "P5"}
    out += order_events("106", hv, day(6, "10:00"), **echo)
    out.append(event("result.final", hv, "106", day(8, "10:00"), status="final", **echo))
    out += order_events("107", hv, day(9, "08:00"), patient="P6")
    out.append(
        event(
            "order.placed",
            hv,
            "108",
            day(9, "08:00"),
            priority="stat",
            status="active",
            patient="P7",
        )
    )
    out.append(
        event(
            "result.final",
            hv,
            "999",
            day(9, "12:00"),
            code="6690-2",
            priority=None,
            status="final",
            patient=None,
        )
    )
    out += order_events("201", "lakeshore", day(5, "09:00"), patient="P8")
    out.append(
        event("result.final", "lakeshore", "201", day(5, "10:00"), status="final", patient="P8")
    )
    return out


def as_message(e: dict[str, Any]) -> bytes:
    return json.dumps(e).encode()


def store_events(settings: Settings, events: list[dict[str, Any]]) -> None:
    """Write events the way the consumer does (one batch), without a broker."""
    received = datetime(2026, 10, 10, tzinfo=UTC)
    rows = [parse_event(as_message(e), received) for e in events]
    write_batch(settings, rows, [])
