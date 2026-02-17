---
description: Docker Compose conventions for this project
globs: compose/docker-compose.yml
alwaysApply: false
---

# Docker Compose Rules

- Image versions MUST be pinned (never `:latest` in production)
- Current Hummingbot image: `hummingbot/hummingbot:version-2.12.0`
- All monitoring ports bind to `${MONITORING_BIND_IP:-127.0.0.1}` (never 0.0.0.0)
- Bot services use YAML anchor `*hbot-base` for shared config
- Bot2+ use `profiles: [multi]` so they don't start by default
- Bind mount a single .py file for custom controllers (don't replace the directory)
- Env file path from compose dir: `--env-file ../env/.env`
- Logging rotation via `x-logging` anchor: json-file driver, 50m max, 5 files
