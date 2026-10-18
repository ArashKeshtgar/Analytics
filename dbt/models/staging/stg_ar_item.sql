-- Current receivable items (latest extract). Reference numbers are not extracted.
select
    ItemId::bigint as item_id,
    EntityId::integer as business_id,
    PartyId::integer as party_id,
    Source as source,
    ItemDate::date as item_date,
    DueDate::date as due_date,
    Amount::decimal(14, 2) as amount,
    Paid::decimal(14, 2) as paid,
    Adjusted::decimal(14, 2) as adjusted,
    (Amount - Paid - Adjusted)::decimal(14, 2) as balance
from {{ source('raw', 'ar_item') }}
