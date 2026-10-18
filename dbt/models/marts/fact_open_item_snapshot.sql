-- Open receivable/payable items per day an extract was taken, with days past due and ageing bucket.
with items as (
    select *, amount - paid - adjusted as balance
    from {{ ref('stg_open_item_history') }}
)

select
    side,
    snapshot_date,
    item_id,
    business_id,
    party_id,
    item_date,
    due_date,
    amount,
    paid,
    adjusted,
    balance,
    date_diff('day', due_date, snapshot_date) as days_past_due,
    case
        when snapshot_date <= due_date then 'current'
        when date_diff('day', due_date, snapshot_date) <= 30 then '1-30'
        when date_diff('day', due_date, snapshot_date) <= 60 then '31-60'
        when date_diff('day', due_date, snapshot_date) <= 90 then '61-90'
        else '90+'
    end as aging_bucket
from items
where balance <> 0
