-- One row per order in fact_order.
select clinic_slug, order_id, count(*) as n
from {{ ref('fact_order') }}
group by 1, 2
having count(*) > 1
