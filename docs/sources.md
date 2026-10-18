# Sources

What Analytics reads, as known on 2026-10-17.

## FinancePowerApp (phase 1)

- SQL Server database `FinancePowerApp` (development: `Server=.;Database=FinancePowerApp;Integrated Security=True;TrustServerCertificate=True`).
  Repository: local only (`D:\E\Projects\FinancePowerApp`), no GitHub remote yet. Schema scripts:
  `database/010_erp_schema.sql`, `011_expense_posting.sql`, `030_reports.sql`.
- Schemas added by the ERP: `org` (businesses), `gl` (accounts, journal), `tax`, `ar`, `ap`, `integ` (inbox). The
  original Power App objects (`dbo.Expenses`, `dbo.AccountingPeriods`, …) are unchanged; read `dbo.AccountingPeriods`
  only.
- Facts worth knowing:
  - Each business's `sourceKey` is the sending application's name for it: ClinicHub's clinic slug (e.g.
    `harbourview`, `lakeshore`), LabFlow's `lab`, PharmaFlow's pharmacy key.
  - Posted entries are never edited; they are reversed. A document dated in a closed month is posted in the next
    open month and marked late — use the posting period for the books, the document date for operations.
  - `dbo.Expenses.TaxAmount` is the income-tax deductible amount, **not HST**.
  - Clinics and labs make HST-exempt supplies; prescriptions are zero-rated.
  - Revenue categories sent by the applications: `OHIP.Professional`, `OHIP.Technical`, `OHIP.Reciprocal`,
    `WSIB.Services`, `Uninsured.Services`, `Lab.OHIP`, `Lab.Uninsured`, `Diagnostics.Echo`, `Diagnostics.ECG`,
    `Pharmacy.Drug`, `Pharmacy.DispensingFee`, `Pharmacy.OTC`; adjustments `Adjustment.Refused`,
    `Adjustment.ShortPaid`, `Adjustment.WriteOff`; costs `Pharmacy.COGS`, `Expense.PhysicianShare`.
  - Reports API for cross-checks (development, single developer user): `http://localhost:5400/api/reports/`
    `dashboard`, `trial-balance`, `income-statement`, `balance-sheet`, `hst`, `aging`.

## IntegrationHub events (phase 4)

RabbitMQ exchange `clinical.events`, de-identified. Schema is owned by IntegrationHub (`docs/events.md` there); this
is how Analytics reads it.

- Kept: `order.placed`, `order.accepted`, `order.cancelled`, `order.cancel-refused`, `result.final`, `result.amended`.
  Ignored: `finance.document`. Refused (reason code only): anything that does not match the contract's shapes or has a
  `schemaVersion` other than 1.
- Columns of `raw.clinical_event`: event id, schema version, type, occurred at (UTC), clinic slug, application, order id,
  test code system and code, priority, status, patient pseudonym, received at. Nothing else is stored.
- Department: `labflow` is Lab and `clinicreport` is Diagnostics; any other application keeps its name.
- Questions: (1) Are `labflow` and `clinicreport` the only applications that receive orders? [Yes.] (2) Should a test
  code be shown with a name? [No names exist in the events; the page shows codes. A code-to-name table would have to
  come from LabFlow's test catalogue and ClinicReport's templates.] (3) Is the hub's `occurredAt` (when it relayed the
  call) good enough as the time of an order and of a result? [Yes; the lab's own clocks are not in the events.]

## LabFlow dw (optional, phase 4)

LabFlow's `dw` schema (`DimDate`, `DimTest`, `DimPayer`, `DimPatient` with hashed ids, `FactLabResult`), built by its
SSIS ETL from the legacy lab system. Already de-identified.

### Columns not to extract

`org.Party.Email`, `org.Party.Phone`: physicians and suppliers are parties, and these are their personal contact
details, which a dashboard does not need. Extract `PartyId`, `PartyType`, `Code`, `Name`, `IsActive` only. Patients
are a single party ("Patients (private pay)"), never individuals. `integ.Document` (the inbox as received) is not
needed: use the posted journal.

## FinancePowerApp tables (copied from its `database/010_erp_schema.sql` on 2026-10-17)

Constraints and indexes trimmed out; the repository is the authority if this drifts.

```sql
CREATE TABLE org.Entity (
    EntityId        int IDENTITY(1,1) CONSTRAINT PK_Entity PRIMARY KEY,
    Code            varchar(20)   NOT NULL CONSTRAINT UQ_Entity_Code UNIQUE,
    Name            nvarchar(120) NOT NULL,
    Kind            varchar(20)   NOT NULL CONSTRAINT CK_Entity_Kind CHECK (Kind IN ('Clinic','Lab','Diagnostics','Pharmacy','Holding')),
    HstNumber       varchar(15)   NULL CONSTRAINT CK_Entity_Hst CHECK (HstNumber IS NULL OR HstNumber LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]RT[0-9][0-9][0-9][0-9]'),
    Province        char(2)       NOT NULL CONSTRAINT DF_Entity_Province DEFAULT 'ON',
    IsDefault       bit           NOT NULL CONSTRAINT DF_Entity_IsDefault DEFAULT 0,
    IsActive        bit           NOT NULL CONSTRAINT DF_Entity_IsActive DEFAULT 1,
    CreatedUtc      datetime2(3)  NOT NULL CONSTRAINT DF_Entity_Created DEFAULT SYSUTCDATETIME()
);

CREATE TABLE org.EntitySource (
    Source     varchar(30) NOT NULL,
    SourceKey  varchar(60) NOT NULL,
    EntityId   int NOT NULL CONSTRAINT FK_EntitySource_Entity REFERENCES org.Entity(EntityId),
);

CREATE TABLE org.Party (
    PartyId    int IDENTITY(1,1) CONSTRAINT PK_Party PRIMARY KEY,
    PartyType  varchar(20)   NOT NULL CONSTRAINT CK_Party_Type CHECK (PartyType IN ('OHIP','ODB','WSIB','Province','Insurer','Patient','Provider','Supplier','Other')),
    Code       varchar(40)   NOT NULL,
    Name       nvarchar(150) NOT NULL,
    Email      nvarchar(150) NULL,
    Phone      varchar(25)   NULL,
    PaymentTermsDays int     NOT NULL CONSTRAINT DF_Party_Terms DEFAULT 30,
    IsActive   bit           NOT NULL CONSTRAINT DF_Party_IsActive DEFAULT 1,
);

CREATE TABLE tax.TaxCode (
    Code         varchar(10)  NOT NULL CONSTRAINT PK_TaxCode PRIMARY KEY,
    Name         nvarchar(80) NOT NULL,
    RatePercent  decimal(5,2) NOT NULL CONSTRAINT CK_TaxCode_Rate CHECK (RatePercent BETWEEN 0 AND 100),
    Recoverable  bit          NOT NULL CONSTRAINT DF_TaxCode_Recoverable DEFAULT 1,
    Description  nvarchar(300) NULL
);

CREATE TABLE gl.Account (
    AccountId   int IDENTITY(1,1) CONSTRAINT PK_Account PRIMARY KEY,
    Number      varchar(10)   NOT NULL CONSTRAINT UQ_Account_Number UNIQUE,
    Name        nvarchar(120) NOT NULL,
    [Type]      varchar(10)   NOT NULL CONSTRAINT CK_Account_Type CHECK ([Type] IN ('Asset','Liability','Equity','Revenue','Expense')),
    Subtype     varchar(20)   NULL CONSTRAINT CK_Account_Subtype CHECK (Subtype IN ('Bank','Cash','Clearing','Receivable','Inventory','TaxRecoverable','Payable','TaxPayable','RetainedEarnings','CostOfSales')),
    ParentId    int NULL CONSTRAINT FK_Account_Parent REFERENCES gl.Account(AccountId),
    IsPostable  bit NOT NULL CONSTRAINT DF_Account_Postable DEFAULT 1,
    IsActive    bit NOT NULL CONSTRAINT DF_Account_Active DEFAULT 1,
    -- CRA's General Index of Financial Information line, for the T2 return.
    GifiCode    char(4) NULL,
    Description nvarchar(300) NULL
);

CREATE TABLE gl.JournalEntry (
    JournalEntryId  bigint IDENTITY(1,1) CONSTRAINT PK_JournalEntry PRIMARY KEY,
    EntityId        int NOT NULL CONSTRAINT FK_JournalEntry_Entity REFERENCES org.Entity(EntityId),
    Number          varchar(20) NOT NULL CONSTRAINT UQ_JournalEntry_Number UNIQUE,
    EntryDate       date NOT NULL,
    PeriodId        int NOT NULL CONSTRAINT FK_JournalEntry_Period REFERENCES dbo.AccountingPeriods(PeriodId),
    -- Manual, Expense (the Power App's approved expenses), or the application: clinichub, labflow, clinicreport, pharmaflow.
    Source          varchar(30) NOT NULL,
    DocumentId      bigint NULL,
    Memo            nvarchar(300) NULL,
    [Status]        varchar(10) NOT NULL CONSTRAINT CK_JournalEntry_Status CHECK ([Status] IN ('Draft','Posted','Reversed')),
    ReversalOfId    bigint NULL CONSTRAINT FK_JournalEntry_Reversal REFERENCES gl.JournalEntry(JournalEntryId),
    -- The document's own date fell in a closed month: posted in the next open one, and says so.
    LatePosting     bit NOT NULL CONSTRAINT DF_JournalEntry_Late DEFAULT 0,
    CreatedBy       nvarchar(100) NOT NULL,
    CreatedUtc      datetime2(3) NOT NULL CONSTRAINT DF_JournalEntry_Created DEFAULT SYSUTCDATETIME(),
    PostedBy        nvarchar(100) NULL,
    PostedUtc       datetime2(3) NULL,
);

CREATE TABLE gl.JournalLine (
    JournalLineId   bigint IDENTITY(1,1) CONSTRAINT PK_JournalLine PRIMARY KEY,
    JournalEntryId  bigint NOT NULL CONSTRAINT FK_JournalLine_Entry REFERENCES gl.JournalEntry(JournalEntryId) ON DELETE CASCADE,
    LineNumber          smallint NOT NULL,
    AccountId       int NOT NULL CONSTRAINT FK_JournalLine_Account REFERENCES gl.Account(AccountId),
    Debit           decimal(14,2) NOT NULL CONSTRAINT DF_JournalLine_Debit DEFAULT 0,
    Credit          decimal(14,2) NOT NULL CONSTRAINT DF_JournalLine_Credit DEFAULT 0,
    PartyId         int NULL CONSTRAINT FK_JournalLine_Party REFERENCES org.Party(PartyId),
    -- Analysis: which department of the business (Clinic, Lab, Echo, Pharmacy), which provider (OHIP billing number).
    Department      varchar(30) NULL,
    ProviderCode    varchar(20) NULL,
    TaxCode         varchar(10) NULL CONSTRAINT FK_JournalLine_Tax REFERENCES tax.TaxCode(Code),
    Memo            nvarchar(200) NULL,
);

CREATE TABLE gl.CategoryMap (
    CategoryMapId int IDENTITY(1,1) CONSTRAINT PK_CategoryMap PRIMARY KEY,
    EntityId      int NULL CONSTRAINT FK_CategoryMap_Entity REFERENCES org.Entity(EntityId),
    Category      varchar(60) NOT NULL,
    AccountId     int NOT NULL CONSTRAINT FK_CategoryMap_Account REFERENCES gl.Account(AccountId),
    Description   nvarchar(200) NULL
);

CREATE TABLE gl.ControlMap (
    ControlMapId int IDENTITY(1,1) CONSTRAINT PK_ControlMap PRIMARY KEY,
    PartyType    varchar(20) NOT NULL,
    Side         varchar(10) NOT NULL CONSTRAINT CK_ControlMap_Side CHECK (Side IN ('Receivable','Payable')),
    AccountId    int NOT NULL CONSTRAINT FK_ControlMap_Account REFERENCES gl.Account(AccountId),
);

CREATE TABLE gl.CashMap (
    Method    varchar(20) NOT NULL CONSTRAINT PK_CashMap PRIMARY KEY,
    AccountId int NOT NULL CONSTRAINT FK_CashMap_Account REFERENCES gl.Account(AccountId)
);

CREATE TABLE ar.Item (
    ItemId        bigint IDENTITY(1,1) CONSTRAINT PK_ArItem PRIMARY KEY,
    EntityId      int NOT NULL CONSTRAINT FK_ArItem_Entity REFERENCES org.Entity(EntityId),
    PartyId       int NOT NULL CONSTRAINT FK_ArItem_Party REFERENCES org.Party(PartyId),
    Source        varchar(30) NOT NULL,
    Reference     varchar(60) NOT NULL,
    DocumentId    bigint NULL,
    ItemDate      date NOT NULL,
    DueDate       date NOT NULL,
    Amount        decimal(14,2) NOT NULL CONSTRAINT CK_ArItem_Amount CHECK (Amount > 0),
    Paid          decimal(14,2) NOT NULL CONSTRAINT DF_ArItem_Paid DEFAULT 0,
    Adjusted      decimal(14,2) NOT NULL CONSTRAINT DF_ArItem_Adjusted DEFAULT 0,
    Balance       AS (Amount - Paid - Adjusted) PERSISTED,
);

CREATE TABLE ap.Item (
    ItemId        bigint IDENTITY(1,1) CONSTRAINT PK_ApItem PRIMARY KEY,
    EntityId      int NOT NULL CONSTRAINT FK_ApItem_Entity REFERENCES org.Entity(EntityId),
    PartyId       int NOT NULL CONSTRAINT FK_ApItem_Party REFERENCES org.Party(PartyId),
    Source        varchar(30) NOT NULL,
    Reference     varchar(60) NOT NULL,
    DocumentId    bigint NULL,
    ItemDate      date NOT NULL,
    DueDate       date NOT NULL,
    Amount        decimal(14,2) NOT NULL CONSTRAINT CK_ApItem_Amount CHECK (Amount > 0),
    Paid          decimal(14,2) NOT NULL CONSTRAINT DF_ApItem_Paid DEFAULT 0,
    Balance       AS (Amount - Paid) PERSISTED,
);

CREATE TABLE dbo.AccountingPeriods (
    PeriodId   int IDENTITY(1,1) NOT NULL CONSTRAINT PK_AccountingPeriods PRIMARY KEY,
    [Year]     int NOT NULL,
    [Month]    int NOT NULL,
    IsClosed   bit NOT NULL CONSTRAINT DF_AccountingPeriods_IsClosed DEFAULT ((0)),
    ClosedDate datetime NULL
);
```

## Open questions for FinancePowerApp (answer here, from the repository; phase 1 assumed the answer in brackets)

1. What is the `org.EntitySource.Source` value for ClinicHub's clinics? [`clinichub`, compared case-insensitively;
   it gives `dim_business.clinic_slug`.]
2. When an entry is reversed, is the original entry set to `Reversed` and the reversal entry `Posted`? [Yes: both are
   kept in `fact_gl_line` and net to zero; only `Draft` is left out.]
3. Do the lines of `Adjustment.Refused` / `Adjustment.ShortPaid` carry the payer's `PartyId` (OHIP)? [Yes:
   `mart_ohip_collection` counts only lines whose party is of type OHIP. If they do not, refused and short-paid show 0.]
4. Are those adjustments posted to the accounts that `gl.CategoryMap` maps for those categories, and are those
   revenue-type accounts (contra-revenue)? [Yes: they then reduce `mart_revenue_monthly`, which is the stated meaning.]
5. Is `Department` always set on revenue lines? [Used as the line of business; `Unassigned` when empty.]
6. Is there a payment date anywhere (`ar.Item` has only `Paid`, no date)? Without it **days to pay is not built**.
   A payments table, or the journal entry that cleared the item, would give it.
7. What does `/api/reports/trial-balance` return (fields, rounding)? The cross-check test against a recorded
   answer is **not built** until a sample answer is pasted here.

## ClinicHub tokens (phase 2)

Issuer `http://localhost:5301/`, keys at `{issuer}.well-known/jwks` (same as IntegrationHub's contracts). Questions;
phase 2 assumed the answer in brackets. Check with the payload of a real token for a user signed in to the `analytics`
client (the part between the dots, base64url, without the signature).

1. Signing algorithm. [`RS256`]
2. Claim `permission`: a JSON array when a user has several, a string when one; values like `analytics:dashboard.view`.
   [Either is read.]
3. Claim `clinic_slug`: present for a clinic user, with the same value as `org.EntitySource.SourceKey` of the ClinicHub
   source (e.g. `harbourview`). [Yes; the match is case-insensitive.] What does a group user (several clinics) get?
   [Nothing needed: `group.view` does not look at it.]
4. Claim `name`: the display name. [Used only for `/api/me`.]
5. `aud` of an access token for the `analytics` client. [Unknown: not checked until `ANALYTICS_OIDC_AUDIENCE` is set.]

**Answered by a real token** (2026-10-18, ClinicHub `c71b3bd`, a physician and the administrator at Harbourview), header
and payload without the signature, values shortened:

```json
{"alg": "RS256", "typ": "at+jwt"}
{"iss": "http://localhost:5301/", "client_id": "analytics", "sub": "…", "name": "Dr. Nadia Patel",
 "clinic_slug": "harbourview", "permission": "dashboard.view", "exp": …}
```

1. `RS256`, `typ: at+jwt`. 2. A string for one, an array for several, and **without the prefix** (`dashboard.view`,
`group.view`, `models.view`): ClinicHub gives each application its own keys that way. Both forms are read.
3. `clinic_slug` is there for every user, the administrator's included (the clinic they chose). 4. `name` is the display
name. 5. **No `aud`**: leave `ANALYTICS_OIDC_AUDIENCE` empty; `client_id` is `analytics`.

## Questions from phase 3 (the dashboard)

Phase 3 assumed the answer in brackets.

1. HST: the accounts of subtype `TaxPayable` hold the HST collected and `TaxRecoverable` the ITCs, and the tax lines
   carry the same `TaxCode` as the line they tax. [Yes. A tax line without a code shows as "(none)".]
2. Which lines make up each GST34 line (101, 103, 106, …), and is the filing period a month or a quarter? [Not
   mapped: the page shows sales and purchases by tax code and the two tax totals, by month or quarter.] A recorded
   answer of FinancePowerApp's `/api/reports/hst` for a period is needed to compare.
3. OHIP billed by provider: the revenue accounts mapped to `OHIP.Professional`, `OHIP.Technical` and
   `OHIP.Reciprocal` (gl.CategoryMap) carry the provider's billing number in `ProviderCode`. [Yes; lines without one
   are "none".] And the `Adjustment.*` lines carry the provider too? [Not in the test data: they show under "none".]
4. Is a month with receivables but no revenue possible (it would not give the dashboard a "latest month")? [The latest
   month with revenue is taken as the latest month with data.]

