# Project Notes for Codex

## Git Handoff

- After implementation and verification are complete, commit the finished work and push the current branch to its remote before handing off.
- If pushing is not possible because the branch has no remote, authentication is unavailable, or the user explicitly asks not to push, report the reason and the exact unpushed status.

## Claude Code / Codex Messaging (agmsg)

- Use the local `agmsg` scripts for Claude Code <-> Codex handoffs. Full workflow: `/Users/takeshi.origuchi/Documents/Codex/github-dev/docs/agmsg-claude-codex-workflow.md`.
- From this project root, register or verify project-scoped identities:

```bash
PROJECT_PATH="$(pwd)"
PROJECT_NAME="$(basename "$PROJECT_PATH")"
TEAM="${PROJECT_NAME}-agents"
CODEX_AGENT="codex-main"
CLAUDE_AGENT="claude-main"

~/.agents/skills/agmsg/scripts/join.sh "$TEAM" "$CODEX_AGENT" codex "$PROJECT_PATH"
~/.agents/skills/agmsg/scripts/join.sh "$TEAM" "$CLAUDE_AGENT" claude-code "$PROJECT_PATH"
~/.agents/skills/agmsg/scripts/delivery.sh set turn codex "$PROJECT_PATH"
~/.agents/skills/agmsg/scripts/team.sh "$TEAM"
```

- Launch Claude Code from the same project root with `claude`, then tell it to act as `claude-main` in the `${PROJECT_NAME}-agents` team and to use only `~/.agents/skills/agmsg/scripts/` for inbox/send actions.
- Send Codex -> Claude with `~/.agents/skills/agmsg/scripts/send.sh "$TEAM" "$CODEX_AGENT" "$CLAUDE_AGENT" "<message>"`.
- Check Codex replies with `~/.agents/skills/agmsg/scripts/inbox.sh "$TEAM" "$CODEX_AGENT"`.
- For non-interactive smoke tests from Codex, prefer `claude -p --model haiku --no-session-persistence` with narrowly allowed `inbox.sh` and `send.sh` Bash tools.
