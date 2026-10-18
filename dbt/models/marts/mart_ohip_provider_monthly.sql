-- OHIP by provider (OHIP billing number) and posting month, from the journal:
--   billed      credits minus debits on the accounts mapped to OHIP.Professional / Technical / Reciprocal
--   short_paid, refused   debits minus credits on the Adjustment.* accounts, lines of an OHIP party
-- 'Paid' and days to pay are not here: payments are not recorded per provider (see docs/sources.md).
with ohip_accounts as (
    select distinct account_id
    from {{ ref('stg_category_map') }}
    where category in ('OHIP.Professional', 'OHIP.Technical', 'OHIP.Reciprocal')
),

adjustment_accounts as (
    select distinct category, account_id
    from {{ ref('stg_category_map') }}
    where category in ('Adjustment.ShortPaid', 'Adjustment.Refused')
),

billed as (
    select
        f.business_id,
        coalesce(f.provider_code, 'none') as provider_code,
        f.period_month as month,
        sum(f.credit - f.debit) as billed
    from {{ ref('fact_gl_line') }} as f
    inner join ohip_accounts as o on o.account_id = f.account_id
    group by 1, 2, 3
),

adjustments as (
    select
        f.business_id,
        coalesce(f.provider_code, 'none') as provider_code,
        f.period_month as month,
        sum(case when m.category = 'Adjustment.ShortPaid' then f.debit - f.credit else 0 end) as short_paid,
        sum(case when m.category = 'Adjustment.Refused' then f.debit - f.credit else 0 end) as refused
    from {{ ref('fact_gl_line') }} as f
    inner join adjustment_accounts as m on m.account_id = f.account_id
    inner join {{ ref('dim_party') }} as p on p.party_id = f.party_id
    where p.party_type = 'OHIP'
    group by 1, 2, 3
)

select
    coalesce(b.business_id, a.business_id) as business_id,
    coalesce(b.provider_code, a.provider_code) as provider_code,
    coalesce(b.month, a.month) as month,
    coalesce(b.billed, 0)::decimal(14, 2) as billed,
    coalesce(a.short_paid, 0)::decimal(14, 2) as short_paid,
    coalesce(a.refused, 0)::decimal(14, 2) as refused
from billed as b
full outer join adjustments as a
    on a.business_id = b.business_id and a.provider_code = b.provider_code and a.month = b.month
