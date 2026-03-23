# OpenSpec skills and agent tooling (triple copy)

Cursor, Claude Code, and GitHub Copilot prompts each carry copies of the same OpenSpec-oriented skills and slash commands:

- `.cursor/commands/` and `.cursor/skills/`
- `.claude/commands/` and `.claude/skills/`
- `.github/prompts/` and `.github/skills/`

**Convention:** When you change an OpenSpec skill, command, or prompt text, update **all three trees in the same change** (or open a follow-up task immediately) so agents in different environments stay aligned. Intentionally no single “source” symlink — portability is the goal.
