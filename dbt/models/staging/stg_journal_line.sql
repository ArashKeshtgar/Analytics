select
    JournalLineId::bigint as journal_line_id,
    JournalEntryId::bigint as journal_entry_id,
    LineNumber::integer as line_number,
    AccountId::integer as account_id,
    Debit::decimal(14, 2) as debit,
    Credit::decimal(14, 2) as credit,
    PartyId::integer as party_id,
    Department as department,
    ProviderCode as provider_code,
    TaxCode as tax_code
from {{ source('raw', 'gl_journalline') }}
