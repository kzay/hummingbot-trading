## ADDED Requirements

### Requirement: Migration script re-compresses existing data
A migration script SHALL read all existing Parquet files under `data/historical/`, re-write them with Zstd compression and 100K row groups, and verify data integrity.

#### Scenario: Migrate candle files
- **WHEN** the migration script is run on a directory containing Snappy-compressed candle Parquet files
- **THEN** each file SHALL be re-written with Zstd compression and row_group_size=100,000
- **AND** the row count before and after SHALL be identical
- **AND** the logical column values SHALL be identical after reload

#### Scenario: Atomic writes prevent corruption
- **WHEN** the migration script re-writes a Parquet file
- **THEN** it SHALL write to a temporary file first, then atomically rename to the original path

#### Scenario: Idempotent re-runs
- **WHEN** the migration script is run on files already compressed with Zstd
- **THEN** it SHALL re-write them without error (idempotent)
- **AND** the reloaded table content SHALL remain identical

### Requirement: Migration reports summary
The migration script SHALL print a summary of files processed, original sizes, new sizes, and total savings.

#### Scenario: Summary output
- **WHEN** the migration script completes
- **THEN** it SHALL print the number of files migrated, total bytes saved, and overall compression ratio improvement
