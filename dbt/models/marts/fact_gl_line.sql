-- Every line of every entry that reached the books. Drafts are left out; entries that were reversed
-- and the reversals themselves are both kept, as they are in the books (they net to zero).
-- `period_month` is the posting period; `entry_date` is the document date.
select
    l.journal_line_id,
    l.journal_entry_id,
    e.business_id,
    e.entry_date,
    e.period_id,
    p.month_start as period_month,
    e.source,
    e.status,
    e.late_posting,
    e.reversal_of_id,
    l.account_id,
    l.debit,
    l.credit,
    l.party_id,
    l.department,
    l.provider_code,
    l.tax_code
from {{ ref('stg_journal_line') }} as l
inner join {{ ref('stg_journal_entry') }} as e on e.journal_entry_id = l.journal_entry_id
left join {{ ref('stg_period') }} as p on p.period_id = e.period_id
where e.status <> 'Draft'
