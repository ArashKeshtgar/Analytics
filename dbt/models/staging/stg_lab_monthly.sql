-- LabFlow's warehouse (the legacy lab's history) as monthly totals per test and kind of payer. Its dates are
-- shifted by up to 180 days to de-identify it, so a month here is approximate. No rows, values or patients.
select
    make_date(Year::integer, Month::integer, 1) as month,
    TestKey::integer as test_key,
    PayerType as payer_type,
    Results::bigint as results,
    Visits::bigint as visits,
    Answered::bigint as answered,
    Abnormal::bigint as abnormal,
    Critical::bigint as critical,
    TurnaroundDaysSum::bigint as turnaround_days_sum,
    TurnaroundCount::bigint as turnaround_count
from {{ source('raw', 'dw_vw_analyticsmonthly') }}
