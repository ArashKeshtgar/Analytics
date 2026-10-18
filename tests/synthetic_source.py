"""A small FinancePowerApp-shaped database, all synthetic, with hand-checkable numbers.

Businesses: 1 = Harbourview (clinic), 2 = lab. Parties: 1 OHIP, 2 Patients (private pay), 3 Provider
A, 4 WSIB, 5 Supplier. Amounts are chosen so the expected marts can be added up by hand
(see tests/test_pipeline.py).
"""

import duckdb

from analytics.finance_tables import FINANCE_TABLES


def create(unbalanced_entry: bool = False, tax_entries: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for schema in ("org", "tax", "gl", "ar", "ap", "dbo"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    # Every column of the real tables that exists here, plus the ones the extract must NOT read:
    # if the extract ever selected them, the test on column lists would catch it first.
    con.execute("""
        CREATE TABLE org.Entity (EntityId int, Code varchar, Name varchar, Kind varchar, HstNumber varchar,
            Province varchar, IsDefault boolean, IsActive boolean, CreatedUtc timestamp);
        CREATE TABLE org.EntitySource (Source varchar, SourceKey varchar, EntityId int);
        CREATE TABLE org.Party (PartyId int, PartyType varchar, Code varchar, Name varchar, Email varchar,
            Phone varchar, PaymentTermsDays int, IsActive boolean);
        CREATE TABLE tax.TaxCode (Code varchar, Name varchar, RatePercent decimal(5,2), Recoverable boolean,
            Description varchar);
        CREATE TABLE gl.Account (AccountId int, Number varchar, Name varchar, "Type" varchar, Subtype varchar,
            ParentId int, IsPostable boolean, IsActive boolean, GifiCode varchar, Description varchar);
        CREATE TABLE gl.JournalEntry (JournalEntryId bigint, EntityId int, Number varchar, EntryDate date,
            PeriodId int, Source varchar, DocumentId bigint, Memo varchar, "Status" varchar,
            ReversalOfId bigint, LatePosting boolean, CreatedBy varchar, CreatedUtc timestamp,
            PostedBy varchar, PostedUtc timestamp);
        CREATE TABLE gl.JournalLine (JournalLineId bigint, JournalEntryId bigint, LineNumber smallint,
            AccountId int, Debit decimal(14,2), Credit decimal(14,2), PartyId int, Department varchar,
            ProviderCode varchar, TaxCode varchar, Memo varchar);
        CREATE TABLE gl.CategoryMap (CategoryMapId int, EntityId int, Category varchar, AccountId int,
            Description varchar);
        CREATE TABLE gl.ControlMap (ControlMapId int, PartyType varchar, Side varchar, AccountId int);
        CREATE TABLE ar.Item (ItemId bigint, EntityId int, PartyId int, Source varchar, Reference varchar,
            DocumentId bigint, ItemDate date, DueDate date, Amount decimal(14,2), Paid decimal(14,2),
            Adjusted decimal(14,2), Balance decimal(14,2));
        CREATE TABLE ap.Item (ItemId bigint, EntityId int, PartyId int, Source varchar, Reference varchar,
            DocumentId bigint, ItemDate date, DueDate date, Amount decimal(14,2), Paid decimal(14,2),
            Balance decimal(14,2));
        CREATE TABLE dbo.AccountingPeriods (PeriodId int, "Year" int, "Month" int, IsClosed boolean,
            ClosedDate timestamp);
    """)
    con.execute("""
        INSERT INTO org.Entity VALUES
          (1, 'HV', 'Harbourview Clinic', 'Clinic', NULL, 'ON', true, true, '2026-01-01'),
          (2, 'LAB', 'Group Lab', 'Lab', NULL, 'ON', false, true, '2026-01-01');
        INSERT INTO org.EntitySource VALUES ('clinichub', 'harbourview', 1), ('labflow', 'lab', 2);
        INSERT INTO org.Party VALUES
          (1, 'OHIP', 'OHIP', 'OHIP', 'secret@example.test', '555-0100', 30, true),
          (2, 'Patient', 'PATIENTS', 'Patients (private pay)', NULL, NULL, 0, true),
          (3, 'Provider', '123456', 'Provider A', 'provider@example.test', '555-0101', 30, true),
          (4, 'WSIB', 'WSIB', 'WSIB', NULL, NULL, 30, true),
          (5, 'Supplier', 'SUP1', 'Supplier One', NULL, NULL, 30, true);
        INSERT INTO tax.TaxCode VALUES ('EXEMPT', 'Exempt', 0, false, 'x');
        INSERT INTO gl.Account VALUES
          (1, '1000', 'Bank', 'Asset', 'Bank', NULL, true, true, '1001', NULL),
          (2, '1100', 'Receivables', 'Asset', 'Receivable', NULL, true, true, '1060', NULL),
          (3, '4000', 'OHIP revenue', 'Revenue', NULL, NULL, true, true, '8000', NULL),
          (4, '4100', 'Uninsured revenue', 'Revenue', NULL, NULL, true, true, '8000', NULL),
          (5, '4910', 'Refused claims', 'Revenue', NULL, NULL, true, true, '8000', NULL),
          (6, '4920', 'Short-paid claims', 'Revenue', NULL, NULL, true, true, '8000', NULL),
          (7, '5000', 'Cost of goods', 'Expense', 'CostOfSales', NULL, true, true, '8518', NULL),
          (8, '6000', 'Office', 'Expense', NULL, NULL, true, true, '8810', NULL);
        INSERT INTO gl.CategoryMap VALUES
          (1, NULL, 'Adjustment.Refused', 5, NULL), (2, NULL, 'Adjustment.ShortPaid', 6, NULL),
          (3, NULL, 'OHIP.Professional', 3, NULL);
        INSERT INTO gl.ControlMap VALUES (1, 'OHIP', 'Receivable', 2);
        INSERT INTO dbo.AccountingPeriods VALUES
          (1, 2026, 9, true, '2026-10-01'), (2, 2026, 10, false, NULL);
    """)
    # Entries: (id, business, number, date, period, status). Lines: (entry, no, account, debit, credit,
    # party, department, provider).
    con.execute("""
        INSERT INTO gl.JournalEntry (JournalEntryId, EntityId, Number, EntryDate, PeriodId, Source, "Status",
                                     LatePosting, Memo, CreatedBy) VALUES
          (1, 1, 'JE1', '2026-09-10', 1, 'clinichub', 'Posted', false, 'must not be extracted', 'staff'),
          (2, 1, 'JE2', '2026-09-20', 1, 'clinichub', 'Posted', false, NULL, 'staff'),
          (3, 1, 'JE3', '2026-10-05', 2, 'clinichub', 'Posted', false, NULL, 'staff'),
          (4, 1, 'JE4', '2026-10-12', 2, 'clinichub', 'Posted', false, NULL, 'staff'),
          (5, 1, 'JE5', '2026-10-14', 2, 'clinichub', 'Posted', false, NULL, 'staff'),
          (6, 1, 'JE6', '2026-10-15', 2, 'clinichub', 'Draft', false, NULL, 'staff'),
          (7, 2, 'JE7', '2026-10-02', 2, 'labflow', 'Posted', false, NULL, 'staff');
        INSERT INTO gl.JournalLine (JournalLineId, JournalEntryId, LineNumber, AccountId, Debit, Credit,
                                    PartyId, Department, ProviderCode) VALUES
          (1, 1, 1, 2, 100, 0, 1, 'Clinic', NULL),   (2, 1, 2, 3, 0, 100, NULL, 'Clinic', '123456'),
          (3, 2, 1, 2, 50, 0, 2, 'Clinic', NULL),    (4, 2, 2, 4, 0, 50, NULL, 'Clinic', NULL),
          (5, 3, 1, 2, 200, 0, 1, 'Clinic', NULL),   (6, 3, 2, 3, 0, 200, NULL, 'Clinic', '123456'),
          (7, 4, 1, 5, 30, 0, 1, 'Clinic', NULL),    (8, 4, 2, 2, 0, 30, 1, 'Clinic', NULL),
          (9, 5, 1, 6, 10, 0, 1, 'Clinic', NULL),    (10, 5, 2, 2, 0, 10, 1, 'Clinic', NULL),
          (11, 6, 1, 2, 999, 0, 1, 'Clinic', NULL),  (12, 6, 2, 3, 0, 999, NULL, 'Clinic', '123456'),
          (13, 7, 1, 2, 70, 0, 2, 'Lab', NULL),      (14, 7, 2, 4, 0, 70, NULL, 'Lab', NULL);
    """)
    if unbalanced_entry:
        con.execute(
            "INSERT INTO gl.JournalEntry (JournalEntryId, EntityId, Number, EntryDate, PeriodId, Source, "
            "\"Status\", LatePosting) VALUES (8, 1, 'JE8', '2026-10-20', 2, 'clinichub', 'Posted', false)"
        )
        con.execute(
            "INSERT INTO gl.JournalLine (JournalLineId, JournalEntryId, LineNumber, AccountId, Debit, Credit) "
            "VALUES (15, 8, 1, 2, 5, 0), (16, 8, 2, 3, 0, 4)"
        )
    if tax_entries:
        _add_tax_entries(con)
    con.execute("""
        INSERT INTO ar.Item VALUES
          (1, 1, 1, 'clinichub', 'REF-1', 1, '2026-09-10', '2026-10-10', 100, 60, 30, 10),
          (2, 1, 1, 'clinichub', 'REF-2', 3, '2026-10-05', '2026-11-04', 200, 0, 0, 200),
          (3, 1, 2, 'clinichub', 'REF-3', 2, '2026-09-20', '2026-10-20', 50, 0, 0, 50);
        INSERT INTO ap.Item VALUES
          (1, 1, 5, 'manual', 'BILL-1', NULL, '2026-09-01', '2026-09-30', 40, 0, 40);
    """)
    return con


def table_names() -> list[str]:
    return [t.raw_name for t in FINANCE_TABLES]


def _add_tax_entries(con: duckdb.DuckDBPyConnection) -> None:
    """HST cases for Harbourview, on top of the base data (used by a separate warehouse so the
    hand-computed numbers of the other tests do not move).

    Expected, all HV unless said (posting month): sales by tax code
      Sep: EXEMPT 150, HST13 100.   Oct: EXEMPT 200, ZERO 40, (none) -40 (refund and short-pay lines)
    tax collected Sep 13;  purchases Oct HST13 200;  ITCs Oct 26.   LAB Oct: sales EXEMPT 70.
    """
    con.execute("""
        INSERT INTO tax.TaxCode VALUES
          ('ZERO', 'Zero-rated', 0, true, NULL), ('HST13', 'HST 13%', 13, true, NULL);
        INSERT INTO gl.Account VALUES
          (9, '2200', 'HST payable', 'Liability', 'TaxPayable', NULL, true, true, '2680', NULL),
          (10, '1300', 'HST recoverable', 'Asset', 'TaxRecoverable', NULL, true, true, '2670', NULL),
          (11, '2100', 'Accounts payable', 'Liability', 'Payable', NULL, true, true, '2600', NULL);
        UPDATE gl.JournalLine SET TaxCode = 'EXEMPT' WHERE AccountId IN (3, 4);
        INSERT INTO gl.JournalEntry (JournalEntryId, EntityId, Number, EntryDate, PeriodId, Source,
                                     "Status", LatePosting) VALUES
          (10, 1, 'JE10', '2026-09-15', 1, 'clinichub', 'Posted', false),
          (11, 1, 'JE11', '2026-10-10', 2, 'manual', 'Posted', false),
          (12, 1, 'JE12', '2026-10-12', 2, 'clinichub', 'Posted', false);
        INSERT INTO gl.JournalLine (JournalLineId, JournalEntryId, LineNumber, AccountId, Debit, Credit,
                                    PartyId, Department, ProviderCode, TaxCode) VALUES
          (17, 10, 1, 2, 113, 0, 2, 'Clinic', NULL, NULL),
          (18, 10, 2, 4, 0, 100, NULL, 'Clinic', NULL, 'HST13'),
          (19, 10, 3, 9, 0, 13, NULL, NULL, NULL, 'HST13'),
          (20, 11, 1, 8, 200, 0, NULL, 'Clinic', NULL, 'HST13'),
          (21, 11, 2, 10, 26, 0, NULL, NULL, NULL, 'HST13'),
          (22, 11, 3, 11, 0, 226, 5, NULL, NULL, NULL),
          (23, 12, 1, 2, 40, 0, 2, 'Clinic', NULL, NULL),
          (24, 12, 2, 4, 0, 40, NULL, 'Clinic', NULL, 'ZERO');
    """)
