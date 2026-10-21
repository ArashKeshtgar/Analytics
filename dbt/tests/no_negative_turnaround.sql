-- A result cannot come before its order (the hub stamps both with its own clock).
select clinic_slug, order_id, turnaround_minutes
from {{ ref('fact_order') }}
where turnaround_minutes < 0
