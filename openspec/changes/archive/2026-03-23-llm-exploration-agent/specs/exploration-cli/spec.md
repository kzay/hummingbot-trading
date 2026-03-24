## ADDED Requirements

### Requirement: CLI entry point

The system SHALL provide a CLI at `hbot/controllers/research/explore_cli.py` executable as `python -m controllers.research.explore_cli` (with `PYTHONPATH=hbot`).

#### Scenario: Help output
- **WHEN** `python -m controllers.research.explore_cli --help` is run
- **THEN** it prints usage information listing all available flags and exits with code 0

### Requirement: CLI arguments

The CLI SHALL accept the following arguments via `argparse`:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--max-iterations` | int | 5 | Maximum exploration iterations |
| `--provider` | str | `"anthropic"` | LLM provider (`"anthropic"` or `"openai"`) |
| `--pair` | str | `"BTC-USDT"` | Trading pair |
| `--exchange` | str | `"bitget"` | Exchange name |
| `--instrument-type` | str | `"perp"` | Instrument type |
| `--temperature` | float | 0.7 | LLM sampling temperature |
| `--skip-sweep` | flag | False | Skip parameter sweep during evaluation |
| `--skip-walkforward` | flag | False | Skip walk-forward during evaluation |
| `--output-dir` | str | `"hbot/data/research/explorations"` | Base output directory |
| `--reports-dir` | str | `"hbot/data/research/reports"` | Evaluation reports directory |
| `--experiments-dir` | str | `"hbot/data/research/experiments"` | Experiment manifests directory |
| `--lifecycle-dir` | str | `"hbot/data/research/lifecycle"` | Lifecycle state directory |
| `-v` / `--verbose` | flag | False | Enable DEBUG-level logging |

#### Scenario: Default arguments
- **WHEN** the CLI is run with no arguments (and required env vars set)
- **THEN** a `SessionConfig` is created with all default values

#### Scenario: Custom arguments
- **WHEN** `--max-iterations 10 --provider openai --pair ETH-USDT --skip-sweep --reports-dir /tmp/reports` is passed
- **THEN** the `SessionConfig` reflects `max_iterations=10`, `llm_provider="openai"`, `pair="ETH-USDT"`, `skip_sweep=True`, `reports_dir="/tmp/reports"`

### Requirement: Session execution

The CLI SHALL:

1. Configure logging level based on `-v` flag (DEBUG if set, INFO otherwise).
2. Build a `SessionConfig` from parsed arguments.
3. Create an `ExplorationSession(config)`.
4. Call `session.run()` to execute the exploration loop.
5. Print a human-readable summary to stdout including: best candidate name and score, total iterations, total tokens used, and path to the session summary file.

#### Scenario: Successful run
- **WHEN** the exploration session completes without fatal errors
- **THEN** the CLI prints the summary and exits with code 0

#### Scenario: Missing API key
- **WHEN** the required API key env var is not set
- **THEN** the CLI prints an error message and exits with code 1

### Requirement: Iteration progress

The CLI SHALL log iteration progress at INFO level in the format:

```
Iteration {n}/{max}: generated {candidate_name} -> score={score:.3f} ({recommendation})
```

#### Scenario: Progress output
- **WHEN** a 3-iteration session runs
- **THEN** 3 progress lines are logged, each showing the iteration number, candidate name, score, and recommendation

### Requirement: Exit codes

| Code | Meaning |
|------|---------|
| 0 | Session completed (regardless of candidate quality) |
| 1 | Unrecoverable error (missing API key, invalid provider, filesystem error) |

#### Scenario: All candidates rejected
- **WHEN** all iterations produce rejected candidates
- **THEN** exit code is still 0 (session completed successfully; rejection is a valid outcome)
