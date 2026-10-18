select
    JournalEntryId::bigint as journal_entry_id,
    EntityId::integer as business_id,
    Number as number,
    EntryDate::date as entry_date,
    PeriodId::integer as period_id,
    Source as source,
    DocumentId::bigint as document_id,
    Status as status,
    ReversalOfId::bigint as reversal_of_id,
    LatePosting::boolean as late_posting,
    PostedUtc::timestamp as posted_utc
from {{ source('raw', 'gl_journalentry') }}
