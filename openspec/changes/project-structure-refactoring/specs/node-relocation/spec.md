## ADDED Requirements

### Requirement: No Node.js package management files at `hbot/` root
The `hbot/` root SHALL NOT contain `package.json`, `package-lock.json`, or `node_modules/`. All Node.js dependencies SHALL be managed within `apps/realtime_ui_v2/`.

#### Scenario: Clean hbot root
- **WHEN** a contributor runs `ls` at `hbot/` root
- **THEN** no `package.json`, `package-lock.json`, or `node_modules/` entries appear

#### Scenario: Playwright available in apps/realtime_ui_v2
- **WHEN** `npm install` is run from `apps/realtime_ui_v2/`
- **THEN** both `playwright` and `@playwright/test` are installed as devDependencies

### Requirement: Screenshot scripts resolve Playwright from app directory
The `screenshot-dashboard.js` script SHALL resolve the `playwright` import from `apps/realtime_ui_v2/node_modules/` without requiring a root-level install.

#### Scenario: Screenshot script runs from app directory
- **WHEN** `node screenshot-dashboard.js` is run from `apps/realtime_ui_v2/`
- **THEN** Playwright launches and takes screenshots without import errors

### Requirement: node_modules excluded from git tracking
The `.gitignore` SHALL include a `node_modules/` entry to prevent accidental commits of Node.js dependencies regardless of location.

#### Scenario: gitignore blocks node_modules
- **WHEN** a contributor runs `npm install` anywhere under `hbot/`
- **THEN** `git status` does not show `node_modules/` as untracked
