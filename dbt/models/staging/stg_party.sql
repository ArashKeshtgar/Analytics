-- No e-mail or phone: they are not extracted.
select
    PartyId::integer as party_id,
    PartyType as party_type,
    Code as code,
    Name as name,
    PaymentTermsDays::integer as payment_terms_days,
    IsActive::boolean as is_active
from {{ source('raw', 'org_party') }}
