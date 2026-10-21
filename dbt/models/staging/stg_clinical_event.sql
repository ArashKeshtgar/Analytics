-- Operational events from IntegrationHub (docs/events.md there). No names, health cards, dates of birth,
-- notes or values exist in them: the patient is an HMAC pseudonym, only meaningful within one clinic.
select
    event_id,
    schema_version::integer as schema_version,
    type,
    occurred_at::timestamp as occurred_at,
    clinic_slug,
    application,
    order_id,
    test_code_system,
    test_code,
    priority,
    status,
    patient_pseudonym,
    received_at::timestamp as received_at
from {{ source('raw', 'clinical_event') }}
