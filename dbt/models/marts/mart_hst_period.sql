-- HST by business, posting month and tax code, in four measures read from the journal:
--   sales         credits minus debits on revenue accounts
--   purchases     debits minus credits on expense accounts
--   tax_collected credits minus debits on accounts of subtype TaxPayable
--   itc           debits minus credits on accounts of subtype TaxRecoverable
-- A line with no tax code is '(none)'. The GST34 line numbers are not mapped here (see docs/sources.md).
with lines as (
    select
        f.business_id,
        f.period_month as month,
        coalesce(f.tax_code, '(none)') as tax_code,
        a.account_type,
        a.subtype,
        f.debit,
        f.credit
    from {{ ref('fact_gl_line') }} as f
    inner join {{ ref('dim_account') }} as a on a.account_id = f.account_id
),

measures as (
    select business_id, month, tax_code, 'sales' as measure, credit - debit as amount
    from lines where account_type = 'Revenue'
    union all
    select business_id, month, tax_code, 'purchases', debit - credit
    from lines where account_type = 'Expense'
    union all
    select business_id, month, tax_code, 'tax_collected', credit - debit
    from lines where subtype = 'TaxPayable'
    union all
    select business_id, month, tax_code, 'itc', debit - credit
    from lines where subtype = 'TaxRecoverable'
)

select
    m.business_id,
    m.month,
    m.tax_code,
    t.name as tax_name,
    t.rate_percent,
    m.measure,
    sum(m.amount)::decimal(14, 2) as amount
from measures as m
left join {{ ref('stg_tax_code') }} as t on t.code = m.tax_code
group by 1, 2, 3, 4, 5, 6
