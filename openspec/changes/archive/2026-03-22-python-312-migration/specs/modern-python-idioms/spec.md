## ADDED Requirements

### Requirement: Union type annotations use PEP 604 syntax

All type annotations in the codebase SHALL use the `X | Y` syntax instead of `Union[X, Y]` and `X | None` instead of `Optional[X]`. Ruff rules UP007 and UP045 SHALL be enforced (removed from ignore list).

#### Scenario: ruff UP007 enabled
- **WHEN** ruff linting runs
- **THEN** rule UP007 (non-pep604-annotation-union) SHALL NOT be in the ignore list

#### Scenario: ruff UP045 enabled
- **WHEN** ruff linting runs
- **THEN** rule UP045 (non-pep604-annotation-optional) SHALL NOT be in the ignore list

#### Scenario: Existing code migrated
- **WHEN** `ruff check --fix` runs after removing UP007 and UP045 from ignore
- **THEN** all `Union[X, Y]` annotations SHALL be converted to `X | Y` and all `Optional[X]` SHALL be converted to `X | None`

### Requirement: datetime uses UTC constant

All references to `datetime.timezone.utc` SHALL be replaced with `datetime.UTC`. Ruff rule UP017 SHALL be enforced.

#### Scenario: ruff UP017 enabled
- **WHEN** ruff linting runs
- **THEN** rule UP017 (datetime-timezone-utc) SHALL NOT be in the ignore list

#### Scenario: Existing code migrated
- **WHEN** `ruff check --fix` runs after removing UP017 from ignore
- **THEN** all `datetime.timezone.utc` references SHALL be converted to `datetime.UTC`

### Requirement: StrEnum replaces string enum patterns

String enum classes SHALL use `enum.StrEnum` (available natively in 3.11+). Ruff rule UP042 SHALL be enforced.

#### Scenario: ruff UP042 enabled
- **WHEN** ruff linting runs
- **THEN** rule UP042 (replace-str-enum) SHALL NOT be in the ignore list

#### Scenario: Existing code migrated
- **WHEN** `ruff check --fix` runs after removing UP042 from ignore
- **THEN** string enum patterns SHALL be converted to `StrEnum` subclasses

### Requirement: zip uses strict parameter

Calls to `zip()` SHALL include the `strict=True` parameter where appropriate. Ruff rule B905 SHALL be enforced.

#### Scenario: ruff B905 enabled
- **WHEN** ruff linting runs
- **THEN** rule B905 (zip-without-explicit-strict) SHALL NOT be in the ignore list

#### Scenario: Existing code reviewed
- **WHEN** ruff reports B905 violations after enabling the rule
- **THEN** each `zip()` call SHALL be reviewed and `strict=True` added where the iterables must be equal length

### Requirement: itertools.pairwise replaces manual pairs

Adjacent-pair iteration SHALL use `itertools.pairwise()` (available in 3.10+). Ruff rule RUF007 SHALL be enforced.

#### Scenario: ruff RUF007 enabled
- **WHEN** ruff linting runs
- **THEN** rule RUF007 (zip-instead-of-pairwise) SHALL NOT be in the ignore list

#### Scenario: Existing code migrated
- **WHEN** `ruff check --fix` runs after removing RUF007 from ignore
- **THEN** `zip(xs, xs[1:])` patterns SHALL be converted to `itertools.pairwise(xs)`

### Requirement: Ruff ignore list comments updated

After removing the suppressed rules, the corresponding comments in `pyproject.toml` explaining why those rules were suppressed SHALL be removed entirely (not left as stale comments).

#### Scenario: No stale suppression comments
- **WHEN** `pyproject.toml` is read after migration
- **THEN** there SHALL be no comments referencing "Python 3.9", "Python 3.10", or "revisit post-migration" in the ruff ignore section
