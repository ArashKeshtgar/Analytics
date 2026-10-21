-- Lab volumes from LabFlow's warehouse: results, visits, abnormal and critical results and the mean
-- visit-to-result time in days, per month (date-shifted, see stg_lab_monthly), test and kind of payer.
select
    m.month,
    m.test_key,
    coalesce(t.TestName, 'Test ' || m.test_key) as test_name,
    t.LoincCode as loinc_code,
    t.LabFlowCode as labflow_code,
    m.payer_type,
    m.results,
    m.visits,
    m.answered,
    m.abnormal,
    m.critical,
    m.turnaround_days_sum,
    m.turnaround_count,
    case when m.turnaround_count > 0
        then round(m.turnaround_days_sum / m.turnaround_count, 2)::double end as turnaround_mean_days
from {{ ref('stg_lab_monthly') }} as m
left join {{ source('raw', 'dw_dimtest') }} as t on t.TestKey = m.test_key
