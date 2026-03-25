## ADDED Requirements

### Requirement: SHA-256 checksum in catalog entries
The system SHALL compute and store a SHA-256 hash of each parquet file when registering it in the catalog.

#### Scenario: Hash computed at registration
- **WHEN** a dataset is registered via `DataCatalog.register()`
- **THEN** the catalog entry SHALL include a `sha256` field containing the hex-encoded SHA-256 hash of the parquet file at `file_path`

#### Scenario: Backward compatibility with existing entries
- **WHEN** the catalog contains entries without a `sha256` field (pre-existing data)
- **THEN** the system SHALL treat missing `sha256` as "unverified" and not fail; verification of those entries SHALL skip the hash check and log a warning suggesting re-registration

### Requirement: Single-entry integrity verification
The system SHALL provide a `verify_entry(entry)` method that checks a single catalog entry against the file on disk.

#### Scenario: All checks pass
- **WHEN** the file exists, file size matches `file_size_bytes`, SHA-256 matches `sha256`, and parquet metadata row count matches `row_count`
- **THEN** `verify_entry()` SHALL return an empty list (no warnings)

#### Scenario: File missing
- **WHEN** the file referenced by `file_path` does not exist on disk
- **THEN** `verify_entry()` SHALL return a warning string indicating the file is missing

#### Scenario: Hash mismatch
- **WHEN** the file exists but its SHA-256 does not match the catalog's `sha256`
- **THEN** `verify_entry()` SHALL return a warning string indicating data corruption (hash mismatch)

#### Scenario: Size mismatch
- **WHEN** the file exists but its size does not match `file_size_bytes`
- **THEN** `verify_entry()` SHALL return a warning string indicating size mismatch

### Requirement: Full catalog verification
The system SHALL provide a `verify_all()` method that runs `verify_entry()` on every catalog entry and returns a summary.

#### Scenario: All entries valid
- **WHEN** all catalog entries pass verification
- **THEN** `verify_all()` SHALL return a dict with zero warnings across all entries

#### Scenario: Some entries invalid
- **WHEN** 2 of 10 catalog entries fail verification
- **THEN** `verify_all()` SHALL return a dict mapping dataset keys to their warning lists, with the 2 failing entries containing non-empty warning lists

### Requirement: Disk reconciliation
The system SHALL provide a `reconcile_disk(base_dir)` method that identifies mismatches between catalog entries and parquet files on disk.

#### Scenario: Orphan parquet file detected
- **WHEN** a `data.parquet` file exists at `{base_dir}/{exchange}/{pair}/{resolution}/data.parquet` but has no corresponding catalog entry
- **THEN** `reconcile_disk()` SHALL include it in the `orphans` list of the result

#### Scenario: Stale catalog entry detected
- **WHEN** a catalog entry references a `file_path` that does not exist on disk
- **THEN** `reconcile_disk()` SHALL include it in the `stale` list of the result

#### Scenario: Clean state
- **WHEN** all parquet files on disk have catalog entries and all catalog entries point to existing files
- **THEN** `reconcile_disk()` SHALL return empty `orphans` and `stale` lists

### Requirement: Integrity check during data refresh
The system SHALL run `verify_all()` and `reconcile_disk()` as part of each data-refresh cycle.

#### Scenario: Integrity warnings logged
- **WHEN** the data-refresh job runs and `verify_all()` finds hash mismatches or missing files
- **THEN** the system SHALL log each warning at WARNING level with the affected dataset key and issue description
