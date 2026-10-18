"""What is extracted from FinancePowerApp: tables and columns (see docs/sources.md).

Columns are listed one by one; nothing is `SELECT *`. Free text (`Memo`, `Description`), staff
names (`CreatedBy`, `PostedBy`), contact details (`Email`, `Phone`) and document references are left
out on purpose: they can carry personal information and a dashboard does not need them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceTable:
    schema: str
    name: str
    columns: tuple[str, ...]

    @property
    def raw_name(self) -> str:
        """File and warehouse name, e.g. `gl_journalline`."""
        return f"{self.schema}_{self.name}".lower()

    @property
    def query(self) -> str:
        # Double quotes work on SQL Server (QUOTED_IDENTIFIER is on for ODBC) and on DuckDB.
        cols = ", ".join(f'"{c}"' for c in self.columns)
        return f"SELECT {cols} FROM {self.schema}.{self.name}"


_OPEN_ITEM = (
    "ItemId",
    "EntityId",
    "PartyId",
    "Source",
    "DocumentId",
    "ItemDate",
    "DueDate",
    "Amount",
    "Paid",
)

FINANCE_TABLES: tuple[SourceTable, ...] = (
    SourceTable(
        "org",
        "Entity",
        (
            "EntityId",
            "Code",
            "Name",
            "Kind",
            "HstNumber",
            "Province",
            "IsDefault",
            "IsActive",
            "CreatedUtc",
        ),
    ),
    SourceTable("org", "EntitySource", ("Source", "SourceKey", "EntityId")),
    SourceTable(
        "org", "Party", ("PartyId", "PartyType", "Code", "Name", "PaymentTermsDays", "IsActive")
    ),
    SourceTable("tax", "TaxCode", ("Code", "Name", "RatePercent", "Recoverable")),
    SourceTable(
        "gl",
        "Account",
        (
            "AccountId",
            "Number",
            "Name",
            "Type",
            "Subtype",
            "ParentId",
            "IsPostable",
            "IsActive",
            "GifiCode",
        ),
    ),
    SourceTable(
        "gl",
        "JournalEntry",
        (
            "JournalEntryId",
            "EntityId",
            "Number",
            "EntryDate",
            "PeriodId",
            "Source",
            "DocumentId",
            "Status",
            "ReversalOfId",
            "LatePosting",
            "PostedUtc",
        ),
    ),
    SourceTable(
        "gl",
        "JournalLine",
        (
            "JournalLineId",
            "JournalEntryId",
            "LineNumber",
            "AccountId",
            "Debit",
            "Credit",
            "PartyId",
            "Department",
            "ProviderCode",
            "TaxCode",
        ),
    ),
    SourceTable("gl", "CategoryMap", ("CategoryMapId", "EntityId", "Category", "AccountId")),
    SourceTable("gl", "ControlMap", ("ControlMapId", "PartyType", "Side", "AccountId")),
    SourceTable("ar", "Item", (*_OPEN_ITEM, "Adjusted")),
    SourceTable("ap", "Item", _OPEN_ITEM),
    SourceTable("dbo", "AccountingPeriods", ("PeriodId", "Year", "Month", "IsClosed")),
)

# Columns that must never be extracted. A test checks FINANCE_TABLES against this list.
FORBIDDEN_COLUMNS = frozenset(
    {"Email", "Phone", "Memo", "Description", "CreatedBy", "PostedBy", "Reference"}
)

# Tables that also keep a daily history in the warehouse, for ageing.
HISTORY_TABLES = ("ar_item", "ap_item")
