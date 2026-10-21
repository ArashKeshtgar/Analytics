-- PartyType: OHIP, ODB, WSIB, Province, Insurer, Patient, Provider, Supplier, Other.
select party_id, party_type, code, name, payment_terms_days, is_active
from {{ ref('stg_party') }}
