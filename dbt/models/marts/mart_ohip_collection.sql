-- Per business and month: what was billed to OHIP (by item date), what was paid, and what was
-- short-paid or refused (journal lines on the accounts mapped to the Adjustment.* categories, by
-- posting month). Days to pay is not built: receivable items do not carry a payment date.
with items as (
    select
        i.business_id,
        date_trunc('month', i.item_date)::date as month,
        sum(i.amount) as billed,
        sum(i.paid) as paid,
        sum(i.adjusted) as adjusted,
        sum(i.balance) as outstanding
    from {{ ref('stg_ar_item') }} as i
    inner join {{ ref('dim_party') }} as p on p.party_id = i.party_id
    where p.party_type = 'OHIP'
    group by 1, 2
),

adjustment_accounts as (
    select distinct category, account_id
    from {{ ref('stg_category_map') }}
    where category in ('Adjustment.ShortPaid', 'Adjustment.Refused')
),

adjustments as (
    select
        f.business_id,
        f.period_month as month,
        sum(case when m.category = 'Adjustment.ShortPaid' then f.debit - f.credit else 0 end) as short_paid,
        sum(case when m.category = 'Adjustment.Refused' then f.debit - f.credit else 0 end) as refused
    from {{ ref('fact_gl_line') }} as f
    inner join adjustment_accounts as m on m.account_id = f.account_id
    inner join {{ ref('dim_party') }} as p on p.party_id = f.party_id
    where p.party_type = 'OHIP'
    group by 1, 2
),

joined as (
    select
        coalesce(i.business_id, a.business_id) as business_id,
        coalesce(i.month, a.month) as month,
        coalesce(i.billed, 0) as billed,
        coalesce(i.paid, 0) as paid,
        coalesce(i.adjusted, 0) as adjusted,
        coalesce(i.outstanding, 0) as outstanding,
        coalesce(a.short_paid, 0) as short_paid,
        coalesce(a.refused, 0) as refused
    from items as i
    full outer join adjustments as a on a.business_id = i.business_id and a.month = i.month
)

select
    business_id,
    month,
    billed::decimal(14, 2) as billed,
    paid::decimal(14, 2) as paid,
    adjusted::decimal(14, 2) as adjusted,
    outstanding::decimal(14, 2) as outstanding,
    short_paid::decimal(14, 2) as short_paid,
    refused::decimal(14, 2) as refused,
    case when billed > 0 then round(short_paid / billed, 4) end as short_paid_rate,
    case when billed > 0 then round(refused / billed, 4) end as refused_rate
from joined
