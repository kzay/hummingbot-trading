# Trading Prompt Pack — Index

Prompts for the EPP v2.4 semi-pro trading desk (Hummingbot / Bitget / Paper Engine v2).

Paste the content of any prompt into an AI chat (Cursor, Claude, GPT) along with your repo/stats context.
Use `17_cursor_output_files_addon.md` when you want results written as separate files; it is compatible with loop prompts and preserves their mandatory sections.

---

## 🔁 loops/ — Recurring improvement loops (run these repeatedly)

Each loop prompt has a `MODE` field at the top. Set it before running.

| File | Cadence | Modes | Covers |
|---|---|---|---|
| `loops/strategy_loop.md` | Weekly | `INITIAL_AUDIT` / `ITERATION` | Strategy logic · finance/risk · execution quality · config tuning · parity gaps · BACKLOG output |
| `loops/tech_loop.md` | Monthly | `INITIAL_AUDIT` / `ITERATION` | Code quality · performance · reliability · test coverage · infra · deps · new tools · BACKLOG output |
| `loops/ops_loop.md` | Daily / Weekly | `DAILY_SCAN` / `WEEKLY_REVIEW` / `INITIAL_AUDIT` | Bot health · observability · alerting · service status · infrastructure · BACKLOG output |

**Every loop ends with mandatory BACKLOG entries** — copy-paste ready for `hbot/BACKLOG.md`.

## Default mindset (applies to all prompts)

- Continuous improvement: challenge previous decisions and keep iterating based on evidence.
- Non-blocking execution: if placeholders are known, fill them; if unknown, make explicit conservative assumptions and continue.
- Creative but bounded change: propose experiments with validation and rollback criteria.
- Repo-wide scope: file/folder lists are anchors, not hard limits; discover additional relevant paths.

---

## 🔭 explore/ — Creative and focused deep-work sessions

**No fixed cadence. No required output format. Run when you need to think deeply or work creatively.**  
These complement the loops — use them when inspiration strikes, when something feels wrong, or when you want to go deep on one thing without running a full monthly review.

| File | Use when |
|---|---|
| `explore/creative_brainstorm.md` | Free-form idea exploration — "what if", blue-sky thinking, evaluating radical options without commitment |
| `explore/focused_refactor.md` | Deep creative refactor of one specific file or component — propose splits, new boundaries, new patterns |
| `explore/restructure_architecture.md` | Thinking through a structural change to service boundaries, data flows, or component responsibilities |
| `explore/focused_test_session.md` | Writing a complete test suite for one specific module — edge cases, failure paths, regression tests |

> Ideas that survive an explore session → promote to BACKLOG via `ops/22_backlog_triage_prompt.md`

---

## 🎯 one-shot prompts — Run once or on specific events

### architecture/ — System design and platform decisions

| File | When to use |
|---|---|
| `01_master_decision_prompt.md` | Initial or quarterly architecture review (keep HB / migrate / hybrid) |
| `02_repo_inventory_architecture_audit.md` | Onboarding a new dev; before a major refactor |
| `10_migration_mapping_prompt.md` | If seriously considering migrating to Nautilus/Freqtrade |
| `12_bonus_adversarial_review_prompt.md` | After any major architecture decision — attack your own design |
| `15_global_audit_prompt_fr_notes_sur_10.md` | Full scored audit /10 per dimension (FR) — major milestone review |
| `16_multibot_desk_master_prompt.md` | Designing a new bot or major desk expansion (Think→Design→Build→Verify) |

### strategy/ — New strategy creation

| File | When to use |
|---|---|
| `20_new_strategy_design.md` | Designing a brand-new strategy from scratch — full production-grade spec |

### ops/ — Event-driven operational prompts

| File | When to use |
|---|---|
| `20_go_live_promotion_gates_prompt.md` | Before switching from paper to live trading — 6-gate evaluation |
| `21_incident_postmortem_prompt.md` | After any P0/P1 incident — structured 5-whys + action items |
| `22_backlog_triage_prompt.md` | Converting raw findings from any session into BACKLOG.md-ready items |

---

## 📄 Utilities (root)

| File | Purpose |
|---|---|
| `17_cursor_output_files_addon.md` | Append to any prompt to make the AI write results as separate named files |

---

## Continuous improvement calendar

| Cadence | Prompt | Mode | Input needed |
|---|---|---|---|
| **Daily** | `loops/ops_loop.md` | `DAILY_SCAN` | Bot state, container status, Redis ping |
| **Weekly** | `loops/strategy_loop.md` | `ITERATION` | `minute.csv`, `fills.csv`, Prometheus metrics |
| **Weekly** | `loops/ops_loop.md` | `WEEKLY_REVIEW` | 7-day trend data, alert log, service reports |
| **Monthly** | `loops/tech_loop.md` | `ITERATION` | Freeze count, tick latency, coverage %, dep versions |
| **After incident** | `ops/21_incident_postmortem_prompt.md` | — | Logs, timeline, metrics |
| **After any session** | `ops/22_backlog_triage_prompt.md` | — | Raw findings from any loop or one-shot |
| **Quarterly** | `architecture/02` → `architecture/12` | — | Full repo |
| **Before go-live** | `loops/strategy_loop.md` (ITERATION) → `ops/20_go_live_promotion_gates_prompt.md` | — | 7+ days paper stats |
| **New strategy** | `strategy/20_new_strategy_design.md` | — | Market thesis, exchange constraints |
| **On demand** | `explore/creative_brainstorm.md` | — | The idea or question you want to explore |
| **On demand** | `explore/focused_refactor.md` | — | Target file + pain description |
| **On demand** | `explore/restructure_architecture.md` | — | The architectural concern |
| **On demand** | `explore/focused_test_session.md` | — | Target module + existing coverage |

> **First run?** Use `INITIAL_AUDIT` mode on all 3 loops to establish your baseline.
> After that, switch to `ITERATION` — each run compares vs the last and tracks progress.

---

## The closed improvement loop

```
paper stats / logs / metrics          inspiration / something feels wrong
        ↓                                         ↓
loops/strategy_loop.md            explore/creative_brainstorm.md
loops/tech_loop.md          OR    explore/focused_refactor.md
loops/ops_loop.md                 explore/restructure_architecture.md
                                  explore/focused_test_session.md
        ↓                                         ↓
Section: BACKLOG entries              ops/22_backlog_triage_prompt.md
(built into every loop)                    (converts ideas → items)
        └──────────────────────────────────────────┘
                                  ↓
                        hbot/BACKLOG.md  ← paste entries here
                                  ↓
                        Cursor AI implements the item
                                  ↓
                  bot/system runs → collect next cycle's inputs
                                  ↓
                               (repeat)
```

---

## Removed prompts (absorbed into loops)

| Removed | Absorbed into |
|---|---|
| `strategy/05_strategy_logic_audit.md` | `loops/strategy_loop.md` |
| `strategy/06_finance_risk_audit.md` | `loops/strategy_loop.md` |
| `strategy/07_execution_exchange_reliability_audit.md` | `loops/strategy_loop.md` |
| `strategy/08_backtest_paper_live_parity_audit.md` | `loops/strategy_loop.md` |
| `strategy/18_strategy_iteration_loop.md` | `loops/strategy_loop.md` |
| `strategy/19_config_param_tuning_prompt.md` | `loops/strategy_loop.md` |
| `code/03_code_quality_audit.md` | `loops/tech_loop.md` |
| `code/04_performance_latency_audit.md` | `loops/tech_loop.md` |
| `code/13_bonus_file_by_file_refactor_prompt.md` | `loops/tech_loop.md` |
| `code/14_bonus_test_strategy_prompt.md` | `loops/tech_loop.md` |
| `code/23_tech_improvement_loop.md` | `loops/tech_loop.md` |
| `ops/09_observability_ops_audit.md` | `loops/ops_loop.md` |
| `ops/18_daily_ops_monitoring_prompt.md` | `loops/ops_loop.md` |
| `11_final_decision_prompt.md` | `architecture/01` + `architecture/16` |
