-- Revenue = credits minus debits on revenue accounts, by posting month. Refund and adjustment accounts
-- that are revenue-type accounts reduce it. Department is the line of business.
select
    f.business_id,
    coalesce(f.department, 'Unassigned') as line_of_business,
    coalesce(f.provider_code, 'none') as provider_code,
    f.period_month as month,
    sum(f.credit - f.debit)::decimal(14, 2) as revenue,
    count(distinct f.journal_entry_id) as entries
from {{ ref('fact_gl_line') }} as f
inner join {{ ref('dim_account') }} as a on a.account_id = f.account_id
where a.account_type = 'Revenue'
group by 1, 2, 3, 4
