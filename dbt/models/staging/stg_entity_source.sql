select
    Source as source,
    SourceKey as source_key,
    EntityId::integer as entity_id
from {{ source('raw', 'org_entitysource') }}
