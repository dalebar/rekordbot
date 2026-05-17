# rekordbot — Phase Completion Checklist

Use this checklist at the end of every phase to ensure nothing is left undone before moving on.

---

## Phase Close-Out

### 1. Verify acceptance criteria

Go through every acceptance criterion in the phase's feature brief (`docs/features/<phase>.md`). Each one should be checked off. If any are not met, the phase is not complete.

### 2. Confirm tests pass

```bash
cd ~/Documents/projects/rekordbot
source .venv/bin/activate
pytest                                 # all tests green
make lint                              # Ruff + mypy clean
```

### 3. Review for stale TODOs

```bash
grep -rn "TODO" backend/ --include="*.py" | grep -v __pycache__
grep -rn "FIXME" backend/ --include="*.py" | grep -v __pycache__
```

Any TODOs left in new code should either be resolved or explicitly tracked (added to CLAUDE.md Known Issues or a future phase's scope).

### 4. Update SESSIONS.md

Add a session entry covering the phase. Include:
- Date
- What was worked on (one-line summary)
- Summary of what was built (commits, test count, key files)
- Issues encountered and resolved
- Key decisions made during implementation
- What's next

### 5. Update CLAUDE.md

Update these sections:
- **Repo Structure** — add any new files/directories created in this phase
- **Current Status** — update phase number, state, and deliverables list
- **Phased Build Plan** — mark completed phases as bold, indicate next phase
- **Known Issues / Don't Touch** — add anything discovered during implementation
- **Key Design Decisions** — add any new decisions or patterns established
- **Configuration Management** — if new Settings fields were added, update the example

### 6. Mark feature brief as complete

In `docs/features/<phase>.md`, change the Status field at the top to "Complete ✅".

### 7. Commit the housekeeping

```bash
git add CLAUDE.md SESSIONS.md docs/features/<phase>.md
git commit -m "Update project docs for Phase <N> completion"   # substitute <N> with the phase number (e.g. 6c)
```

### 8. Merge to develop

```bash
git checkout develop
git merge feature/<phase-name> --no-ff   # preserve branch history
git log --oneline -5                      # verify merge looks right
```

The `--no-ff` flag creates a merge commit even if fast-forward is possible. This preserves the branch history in the git log, making it clear where each phase's work starts and ends.

### 9. Tag the merge commit

Tagging marks phase boundaries on `develop` and is the project convention — always apply a tag after merging. Substitute `<N>` with the actual phase number and `<phase-name>` with the phase title.

```bash
git tag -a phase-<N>-complete -m "Phase <N>: <phase name> complete"
```

Then push the tag to origin:

```bash
git push origin phase-<N>-complete
```

Tags let you quickly check out known-good states and provide a visible audit trail of phase landings on `develop`.

### 10. Review the project plan

Before moving on, review `docs/djapp-project-plan.md` against the current state of the project. Check for:
- Completed phases accurately reflected (deliverables, not unchecked boxes)
- Tech stack and architecture still match reality
- Feature map updated with anything built or changed during this phase
- Upcoming phases still make sense given what was learned during implementation
- No stale references (old names, resolved decisions still listed as open, etc.)

If anything needs updating, do it now and commit alongside the housekeeping changes.

### 11. Ready for next phase

At this point:
- `develop` has all Phase N work merged
- CLAUDE.md, SESSIONS.md, and the project plan reflect current state
- Feature brief is marked complete
- You're ready to follow the **Claude Code Session Checklist** (`docs/claude-code-session-checklist.md`) to start Phase N+1
