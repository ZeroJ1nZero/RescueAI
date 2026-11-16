# RescueAI Migration Implementation Plan

> **For agentic workers:** Execute this migration inline, using superpowers:executing-plans and verification-before-completion. The user requested a local result requiring only push.

**Goal:** Preserve RescueAI history and backend while bringing the current Fire Vision source, pending changes, and Python setup into a push-ready commit.

**Architecture:** Keep the standalone Python project under `edge/fire_vision/`. Keep the backend dependency file, app, and API specification untouched; add only a short root README link. Clone the existing target into temporary storage for preparation, then fast-forward its local embedded after verification.

**Tech Stack:** Python >=3.10, setuptools, pytest, Bash, Git. Existing macOS lock uses Python 3.13; Jetson uses system Python matching ROS Humble.

**Spec:** User request in this session: transfer current files to `~/IdeaProjects/RescueAI`, preserve Python environment setup, minimize merge conflicts, leave only push.

## Global Constraints

- Preserve source checkout and target backend files.
- Exclude `.git`, virtual environments, credentials, data, results, caches, and delivery bundles.
- Keep backend and edge dependency installation separate.
- Do not push; finish with a clean target embedded ahead of origin/embedded.

## Review Focus

- Paths containing spaces: existing transfer test uses real local Git bundles.
- Existing modified checkout: transfer must retain board edits.
- Missing bundle or existing non-repository directory: reject before clone.
- Clone root differs from package root: Python step uses `edge/fire_vision`.
- Historical verification files: preserve as historical records and add a new migration report.

### Task 1: Transfer and adapt the standalone project

**Files:** `edge/fire_vision/**`, root `README.md`.
**Interfaces:** `FV_REPO_DIR` selects the RescueAI checkout; `FV_PROJECT_DIR` selects the independent Python project.

- [x] Copy all tracked and unignored pending files into the temporary RescueAI clone.
- [x] Adapt bundle fixture to RescueAI nested layout; verify it fails before script changes.
- [x] Point clone to RescueAI, preserve repository/module path distinction, then run script tests.
- [x] Update active setup guides and add a concise root README link.
- [x] Install and verify from the macOS lock in a fresh temporary venv; run the entire edge test suite and CLI smoke checks.
- [x] Record file preservation, dependency isolation, and hardware validation limits.
- [x] Review only the new subtree and root README link; independent review found no Critical/Important/Minor issues. Commit this verified result.
- [ ] Final delivery gate (run after committing): verify target and remote base are unchanged; fast-forward target embedded; verify clean state and ahead count. The final session response records this external checkout result.

## Execution notes

Preparation used a temporary local clone rather than altering the source checkout. The user requested a push-ready local RescueAI result, so execution continued without an additional plan approval. The independent reviewer checked migration adaptations; inherited scientific algorithms and actual ROS/camera behavior remain outside the migration validation scope.
