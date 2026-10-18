-- Read-only login for Analytics on the FinancePowerApp database.
--
-- This is the text of FinancePowerApp's `database/050_analytics_reader.sql`. FinancePowerApp has no GitHub
-- remote and is not visible from the cloud session, so the script lives here until it is copied there.
-- NOT RUN against SQL Server by the session that wrote it: run it on a development server first.
--
-- Run as a sysadmin / db_owner. Set the password before running; never commit it.

USE master;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'analytics_reader')
    CREATE LOGIN analytics_reader WITH PASSWORD = N'CHANGE-ME-before-running', CHECK_POLICY = ON;
GO

USE FinancePowerApp;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'analytics_reader')
    CREATE USER analytics_reader FOR LOGIN analytics_reader;
GO

-- SELECT only, on the schemas Analytics reads. No INSERT/UPDATE/DELETE/EXECUTE anywhere.
GRANT SELECT ON SCHEMA::org TO analytics_reader;
GRANT SELECT ON SCHEMA::gl  TO analytics_reader;
GRANT SELECT ON SCHEMA::ar  TO analytics_reader;
GRANT SELECT ON SCHEMA::ap  TO analytics_reader;
GRANT SELECT ON SCHEMA::tax TO analytics_reader;
GRANT SELECT ON dbo.AccountingPeriods TO analytics_reader;

-- Columns that can hold personal details or free text: the login cannot read them, so a mistake in
-- Analytics cannot load them. (Column DENY wins over the schema GRANT.)
DENY SELECT ON org.Party (Email, Phone)                      TO analytics_reader;
DENY SELECT ON gl.JournalEntry (Memo, CreatedBy, PostedBy)   TO analytics_reader;
DENY SELECT ON gl.JournalLine (Memo)                         TO analytics_reader;
DENY SELECT ON gl.Account (Description)                      TO analytics_reader;
DENY SELECT ON gl.CategoryMap (Description)                  TO analytics_reader;
DENY SELECT ON tax.TaxCode (Description)                     TO analytics_reader;
DENY SELECT ON ar.Item (Reference)                           TO analytics_reader;
DENY SELECT ON ap.Item (Reference)                           TO analytics_reader;
GO

-- Not granted on purpose: integ.* (the inbox as received).
