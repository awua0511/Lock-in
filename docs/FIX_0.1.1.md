# 0.1.1: Legacy daily-review database compatibility

An early schema-3 database had four columns in `review_deliveries`. Later schema-3 code expected a fifth, `delivery_day`, but an existing profile skipped the already-recorded migration. Periodic review checks failed with `OperationalError: no such column: delivery_day`, displaying the generic yellow operation-failure banner even when viewing a review succeeded.

Version 0.1.1 introduces a separate, atomic migration 4. It supports both old and newer schema-3 layouts, preserves settings/history/receipts, and maintains daily notification deduplication using original local attempt dates. Multiple legacy receipts on one delivery date remain stored; only one owns that day's delivery slot. Skipped receipts do not consume a slot. Existing modern delivery dates are not rewritten.

Startup backs up an existing database before migration to `lock-in.pre-migration.backup.sqlite3` beside the database. Do not delete your database or clear its migration history. After upgrading to schema 4, use version 0.1.1 or newer, not the old EXE; rollback across schemas is intentionally refused.

Regression coverage includes legacy upgrade, modern upgrade, repeated startup, preserved receipts/settings, catch-up dates, unique delivery slots, backup integrity and rollback/retry after an injected failure. The affected local profile was additionally copied into memory: migration, row-count preservation, database integrity and the formerly failing due-check path all passed without changing the source profile during diagnosis.

Validation: 175 Python tests, 3 JavaScript tests, 6 Windows communication scenarios and all 10 packaged checks passed (`build/release-check-0.1.1/results.json`). This compatibility repair does not change the broader M7 public-release limitations.

The affected local installation was upgraded to 0.1.1 after the user exited the tray. Under the normal single-instance guard, its database was backed up and migrated to schema 4. Every pre-existing table value (excluding the migration ledger and newly added column) was compared before/after and preserved; SQLite integrity and foreign-key checks passed. Browser IDs were retained by setup. Final visible UI acceptance remains with the user.
