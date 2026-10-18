select period_id, period_year, period_month, month_start, is_closed
from {{ ref('stg_period') }}
