-- One snapshot per calendar day and item, receivable and payable together.
select
    'receivable' as side,
    snapshot_date::date as snapshot_date,
    ItemId::bigint as item_id,
    EntityId::integer as business_id,
    PartyId::integer as party_id,
    ItemDate::date as item_date,
    DueDate::date as due_date,
    Amount::decimal(14, 2) as amount,
    Paid::decimal(14, 2) as paid,
    Adjusted::decimal(14, 2) as adjusted
from {{ source('raw', 'ar_item_history') }}

union all

select
    'payable' as side,
    snapshot_date::date,
    ItemId::bigint,
    EntityId::integer,
    PartyId::integer,
    ItemDate::date,
    DueDate::date,
    Amount::decimal(14, 2),
    Paid::decimal(14, 2),
    0::decimal(14, 2) as adjusted
from {{ source('raw', 'ap_item_history') }}
