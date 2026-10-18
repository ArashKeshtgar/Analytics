select
    AccountId::integer as account_id,
    Number as number,
    Name as name,
    Type as account_type,
    Subtype::varchar as subtype,
    ParentId::integer as parent_id,
    IsPostable::boolean as is_postable,
    IsActive::boolean as is_active,
    GifiCode::varchar as gifi_code
from {{ source('raw', 'gl_account') }}
