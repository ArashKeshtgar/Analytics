-- Debits equal credits in every entry that reached the books.
select journal_entry_id, sum(debit) as debit, sum(credit) as credit
from {{ ref('fact_gl_line') }}
group by journal_entry_id
having sum(debit) <> sum(credit)
