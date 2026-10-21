-- raw.clinical_event holds one row per event id (the loader keeps the first one received).
select event_id, count(*) as n
from {{ ref('stg_clinical_event') }}
group by 1
having count(*) > 1
