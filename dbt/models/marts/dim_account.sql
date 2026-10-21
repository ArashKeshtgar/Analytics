select
    account_id,
    number,
    name,
    account_type,
    subtype,
    parent_id,
    is_postable,
    is_active,
    gifi_code,
    case
        when account_type = 'Revenue' then 'Revenue'
        when account_type = 'Expense' and subtype = 'CostOfSales' then 'Cost of sales'
        when account_type = 'Expense' then 'Operating expense'
        else account_type
    end as account_group
from {{ ref('stg_account') }}
