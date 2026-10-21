-- The trial balance of each business nets to zero.
select business_id, sum(debit) as debit, sum(credit) as credit
from {{ ref('fact_gl_line') }}
group by business_id
having sum(debit) <> sum(credit)
