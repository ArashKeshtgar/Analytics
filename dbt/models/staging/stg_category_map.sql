select
    CategoryMapId::integer as category_map_id,
    EntityId::integer as business_id,
    Category as category,
    AccountId::integer as account_id
from {{ source('raw', 'gl_categorymap') }}
