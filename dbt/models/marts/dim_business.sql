-- One row per business (org.Entity). `clinic_slug` is the key ClinicHub uses for the clinic; see
-- docs/sources.md for the open question on the exact `Source` value.
with keys as (
    select
        entity_id,
        list({'source': source, 'source_key': source_key} order by source, source_key) as source_keys,
        max(case when lower(source) = 'clinichub' then source_key end) as clinic_slug
    from {{ ref('stg_entity_source') }}
    group by entity_id
)

select
    e.entity_id as business_id,
    e.code,
    e.name,
    e.kind,
    e.hst_number,
    e.province,
    e.is_default,
    e.is_active,
    k.clinic_slug,
    k.source_keys
from {{ ref('stg_entity') }} as e
left join keys as k on k.entity_id = e.entity_id
