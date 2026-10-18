select
    Code as code,
    Name as name,
    RatePercent::decimal(5, 2) as rate_percent,
    Recoverable::boolean as recoverable
from {{ source('raw', 'tax_taxcode') }}
