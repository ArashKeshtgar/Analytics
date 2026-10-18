-- One row per order (one test), from its events, whatever order they arrived in:
-- placed -> accepted -> resulted (final, maybe amended) or cancelled.
-- Orders the hub never saw placed (before it started) have results but no `placed_at`: they have no
-- turnaround and are left out of the percentiles.
with events as (
    select * from {{ ref('stg_clinical_event') }}
),

orders as (
    select
        clinic_slug,
        order_id,
        min(occurred_at) filter (where type = 'order.placed') as placed_at,
        min(occurred_at) filter (where type = 'order.accepted') as accepted_at,
        min(occurred_at) filter (where type = 'result.final') as first_final_at,
        max(occurred_at) filter (where type = 'result.final') as last_final_at,
        count(*) filter (where type = 'result.amended') as amended_count,
        max(occurred_at) filter (where type = 'result.amended') as last_amended_at,
        min(occurred_at) filter (where type = 'order.cancelled') as cancelled_at,
        count(*) filter (where type = 'order.cancel-refused') as cancel_refused_count,
        arg_min(application, occurred_at) filter (where application is not null) as application,
        arg_min(test_code, occurred_at) filter (where test_code is not null) as test_code,
        arg_min(test_code_system, occurred_at) filter (where test_code_system is not null) as test_code_system,
        arg_min(priority, occurred_at) filter (where priority is not null) as priority,
        arg_min(patient_pseudonym, occurred_at) filter (where patient_pseudonym is not null) as patient_pseudonym
    from events
    group by clinic_slug, order_id
)

select
    clinic_slug,
    order_id,
    application,
    case application
        when 'labflow' then 'Lab'
        when 'clinicreport' then 'Diagnostics'
        else coalesce(application, 'Unknown')
    end as department,
    test_code_system,
    test_code,
    priority,
    patient_pseudonym,
    placed_at,
    accepted_at,
    first_final_at,
    last_final_at,
    amended_count,
    last_amended_at,
    cancelled_at,
    cancel_refused_count,
    case
        when cancelled_at is not null then 'cancelled'
        when first_final_at is not null and placed_at is null then 'resulted (placed before the hub)'
        when first_final_at is not null then 'resulted'
        when accepted_at is not null then 'accepted'
        when placed_at is not null then 'placed'
        else 'unknown'
    end as status,
    -- minutes from the order being placed to its first final result
    case
        when placed_at is not null and first_final_at is not null
        then date_diff('second', placed_at, first_final_at) / 60.0
    end as turnaround_minutes
from orders
