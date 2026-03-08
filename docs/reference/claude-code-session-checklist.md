# rekordbot — Claude Code Session Checklist

A reference for starting Claude Code sessions. Follow this every time.

---

## Starting a New Phase

### 1. Git setup

```bash
cd ~/Documents/projects/rekordbot
git checkout develop
git pull                              # if working across machines
git checkout -b feature/<phase-name>  # e.g. feature/phase-1-converter
```

### 2. Environment

```bash
uv sync                               # ensure deps match lockfile
source .venv/bin/activate              # activate venv
```

### 3. Clean commit checkpoint

```bash
git status                             # should be clean
git log --oneline -3                   # confirm you're on the right branch
```

If there are uncommitted changes, commit or stash them first. A clean starting point means `git diff` shows exactly what Claude Code changed, and `git checkout .` is a safe full undo.

### 4. Start Claude Code

```bash
claude
```

### 5. Initial prompt

Paste the Claude Code prompt from the phase's feature brief (`docs/features/<phase>.md`). That prompt already tells Claude Code to read CLAUDE.md and the feature brief first.

---

## Continuing a Phase (New Session)

Use this when you're resuming work on a phase you already started — e.g. you stopped mid-phase yesterday and are picking up today.

### 1. Environment

```bash
cd ~/Documents/projects/rekordbot
git checkout feature/<phase-name>      # switch to the feature branch
uv sync
source .venv/bin/activate
```

### 2. Update SESSIONS.md

Before starting, make sure the latest session entry in SESSIONS.md reflects where you left off. If it doesn't, update it now.

### 3. Start Claude Code

```bash
claude
```

### 4. Continuation prompt

```
We are continuing Phase [N] ([phase name]) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/<phase-brief>.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## End of Session

Before closing Claude Code, make sure:

1. All work is committed with descriptive messages
2. Tests pass (`make test` or `pytest`)
3. Update SESSIONS.md with:
   - Date
   - What was worked on
   - Key decisions made
   - Unresolved questions or blockers
   - What the next step is
4. Flag if CLAUDE.md needs updating (new conventions, status change, known issues)
