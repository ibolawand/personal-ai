---
name: aria-ship
description: Use when the user says commit, push, "ship it" or similar in this project. Handles the git root, the GitHub account switch, the attribution line and what to check first. Never commits or pushes unasked.
---

# Commit and push Aria (and MyNotion) changes

Only when the user asks. Commit/push is outward-facing: don't do it on your own.

## Where things live
- Aria: git root is `personal-ai/` (parent of `BetterAI/`), branch `aria-desk-assistant`, remote `ibolawand/personal-ai`. Paths in `git status` start with `BetterAI/`.
- MyNotion: separate repo `../../MyNotion` (`/home/lala/Desktop/school/personal/MyNotion`), branch `dark-green-refinement`, remote `ibolawand/MyNotion`.

## Before committing
1. `git status --short` and `git diff --stat`: look at what's actually changed; stage by name, not `git add -A` (`.idea`, caches, `aria_memory.db`, `Engines/.env` must never go in).
2. Fast tests: `.venv/bin/python -m pytest -q`. If prompt/tools/routing changed, the `aria-model-check` skill too. MyNotion: `npx ng test --watch=false --browsers=ChromeHeadless` in `note-frontend`.
3. `FEATURES.md` updated for any feature change (CLAUDE.md rule).

## Commit
- Small, clear message in the repo's style (`Organise a note: lines lined up with Tab become a table`): what the user gets, not how.
- End with the attribution line the session's system reminder gives (currently `Co-Authored-By: <current model> <noreply@anthropic.com>`); use the one from the latest reminder, don't copy an old one.
- One commit per coherent feature (columns, solution checker, big model…), not one giant commit.

## Push
- Two gh accounts exist: `ibolawand` (owns the remotes) and `lalaibo`. A 403 on push means the wrong one is active: `gh auth status`, then `gh auth switch --user ibolawand`.
- `git push` (set upstream if new). Report the pushed commits.
- Never force-push, never touch other branches, never use `git stash -u` here (the root-owned `BetterAI/MyNotion/note/noted` breaks it).
