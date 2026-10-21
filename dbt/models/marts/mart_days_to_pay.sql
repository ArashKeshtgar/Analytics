-- Days to pay: from the item date to each payment, per business, payer type and payment month. The mean is weighted by
-- the amount paid, so a large remittance counts for what it is worth. A payment dated before its item counts as 0 days
-- (the posting engine accepts a receipt dated before the claim is raised).
select
    p.business_id,
    t.party_type,
    date_trunc('month', p.payment_date)::date as month,
    count(*) as payments,
    sum(p.amount)::decimal(14, 2) as amount,
    round(sum(p.amount * greatest(date_diff('day', i.item_date, p.payment_date), 0)) / nullif(sum(p.amount), 0), 1) as mean_days,
    max(greatest(date_diff('day', i.item_date, p.payment_date), 0)) as max_days
from {{ ref('stg_item_payment') }} as p
inner join {{ ref('stg_ar_item') }} as i on i.item_id = p.item_id
inner join {{ ref('dim_party') }} as t on t.party_id = i.party_id
group by 1, 2, 3
