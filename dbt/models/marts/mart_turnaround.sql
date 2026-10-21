-- Order to first final result, by clinic, month the order was placed, department (Lab = LabFlow,
-- Diagnostics = ClinicReport), test and priority: median and 90th percentile in minutes.
-- Orders still waiting are in orders_placed and not in the percentiles.
select
    clinic_slug,
    date_trunc('month', placed_at)::date as month,
    department,
    coalesce(test_code, 'unknown') as test_code,
    coalesce(priority, 'unknown') as priority,
    count(*) as orders_placed,
    count(turnaround_minutes) as orders_resulted,
    median(turnaround_minutes) as median_minutes,
    quantile_cont(turnaround_minutes, 0.9) as p90_minutes
from {{ ref('fact_order') }}
where placed_at is not null
group by 1, 2, 3, 4, 5
