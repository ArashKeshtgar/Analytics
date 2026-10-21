-- When each receivable item was paid: one row per item and receipt (FinancePowerApp's ar.vw_ItemPayments, built from
-- the receipts it posted). Empty when the source has no such view. No references or text.
select
    ItemId::bigint as item_id,
    EntityId::integer as business_id,
    PaymentDate::date as payment_date,
    Amount::decimal(14, 2) as amount
from {{ source('raw', 'ar_vw_itempayments') }}
