# Incident Playbook 10 — Misconfiguration Rollback

**Scenario:** A config change (YAML, .env, docker-compose, alert rules) caused unexpected behavior — wrong parameters, bot crash, missing env vars, or incorrect alert thresholds.

---

## Trigger Indicators

- Bot fails to start: `BOT1_PASSWORD/CONFIG_PASSWORD missing`, `Config file not found`, or Python/YAML parse error
- Bot enters unexpected state after config change (e.g. wrong spread, wrong pair)
- Alert storm: too many or too few alerts from `hbot/infra/monitoring/prometheus/alert_rules.yml`
- Missing env vars: services fail with "required env X not set"
- Docker compose fails: `docker compose config` or `up` errors

---

## Immediate Actions (< 2 minutes)

1. **Identify which config changed:**
   ```bash
   git status
   git diff hbot/data/bot1/conf/ hbot/infra/env/.env hbot/infra/compose/docker-compose.yml hbot/infra/monitoring/prometheus/alert_rules.yml
   git log -1 --format="%ci %s" -- hbot/data/bot1/conf/controllers/
   ```

2. **Check recent file modifications:**
   ```bash
   ls -la hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml
   ls -la hbot/infra/env/.env
   stat hbot/infra/compose/docker-compose.yml
   ```

3. **Immediate rollback (if change is clearly wrong):**
   ```bash
   git checkout HEAD~1 -- hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml
   # Or restore from backup if not in git
   ```

4. **Restart affected services:**
   ```bash
   docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
   ```

---

## Diagnosis Steps

| Symptom | Likely Cause | Check |
|---|---|---|
| Bot crash on startup | Invalid YAML, wrong key, missing script config | `docker logs bot1 --tail 50` |
| Wrong trading params | YAML typo, wrong value in epp_v2_4_bot_a.yml | `cat hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml` |
| Missing env var | .env not loaded, var removed or renamed | `diff hbot/infra/env/.env.template hbot/infra/env/.env` |
| Alert storm / no alerts | Alert rule syntax error, wrong threshold | `promtool check rules hbot/infra/monitoring/prometheus/alert_rules.yml` |
| Compose error | Invalid YAML, wrong service name, missing env | `docker compose -f hbot/infra/compose/docker-compose.yml config` |
| Config not applied | Bot not restarted after change | `docker compose ... restart bot1` |

---

## Resolution Steps

### 1. Immediate rollback

```bash
# Rollback specific file to previous commit
git checkout HEAD~1 -- hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml

# Or restore from backup
cp /path/to/backup/epp_v2_4_bot_a.yml hbot/data/bot1/conf/controllers/
```

### 2. Docker service restart after config rollback

```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml restart bot1
# For env changes, may need full recreate
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml up -d --force-recreate bot1
```

### 3. Verifying rollback took effect

```bash
# Container logs
docker logs bot1 --tail 30 2>&1

# Bot state in minute.csv
tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv

# Confirm config loaded
docker exec bot1 cat /home/hummingbot/conf/controllers/epp_v2_4_bot_a.yml | head -30
```

### 4. Environment variable verification

```bash
# Compare .env vs template (ensure no required vars missing)
diff hbot/infra/env/.env.template hbot/infra/env/.env

# Check critical vars are set
grep -E "BOT1_PASSWORD|CONFIG_PASSWORD|REDIS_HOST|BOT_MODE" hbot/infra/env/.env
```

### 5. Config validation before applying changes

```bash
# Python compile (catches syntax errors in controller)
python -m py_compile hbot/controllers/epp_v2_4.py

# YAML lint (if yamllint installed)
yamllint hbot/data/bot1/conf/controllers/epp_v2_4_bot_a.yml 2>/dev/null || true

# Pytest (strategy isolation, config loading)
PYTHONPATH=hbot python -m pytest hbot/tests/controllers/test_strategy_isolation_contract.py -q
```

### 6. Alert rule validation

```bash
promtool check rules hbot/infra/monitoring/prometheus/alert_rules.yml
# No output = valid
```

### 7. Compose validation

```bash
docker compose --env-file hbot/infra/env/.env -f hbot/infra/compose/docker-compose.yml config
# Validates YAML and resolves variables
```

---

## Post-Resolution Verification

- [ ] `docker compose config` succeeds
- [ ] `promtool check rules hbot/infra/monitoring/prometheus/alert_rules.yml` passes
- [ ] Bot starts and minute.csv updates: `tail -3 hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv`
- [ ] No unexpected alerts in Alertmanager
- [ ] Config values match intended (spread, pair, limits)

---

## Prevention / Long-term

- Always run `docker compose config` before `up` or `restart`
- Validate YAML and alert rules in CI before merge
- Keep `.env` changes minimal; document in `hbot/infra/env/.env.template`
- Use `git diff` before applying config changes to production
- Consider config review checklist: py_compile, pytest, promtool, compose config
