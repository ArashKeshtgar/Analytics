select
    EntityId::integer as entity_id,
    Code as code,
    Name as name,
    Kind as kind,
    HstNumber as hst_number,
    Province as province,
    IsDefault::boolean as is_default,
    IsActive::boolean as is_active,
    CreatedUtc::timestamp as created_utc
from {{ source('raw', 'org_entity') }}
