select
    PeriodId::integer as period_id,
    Year::integer as period_year,
    Month::integer as period_month,
    make_date(Year::integer, Month::integer, 1) as month_start,
    IsClosed::boolean as is_closed
from {{ source('raw', 'dbo_accountingperiods') }}
