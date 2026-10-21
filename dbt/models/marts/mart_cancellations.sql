-- Cancels that went through and cancels the application refused (results entered, report started),
-- by clinic and the month of the cancel, department and test of the order.
select
    e.clinic_slug,
    date_trunc('month', e.occurred_at)::date as month,
    coalesce(o.department, 'Unknown') as department,
    coalesce(o.test_code, 'unknown') as test_code,
    count(*) filter (where e.type = 'order.cancelled') as cancelled,
    count(*) filter (where e.type = 'order.cancel-refused') as cancel_refused
from {{ ref('stg_clinical_event') }} as e
left join {{ ref('fact_order') }} as o on o.clinic_slug = e.clinic_slug and o.order_id = e.order_id
where e.type in ('order.cancelled', 'order.cancel-refused')
group by 1, 2, 3, 4
