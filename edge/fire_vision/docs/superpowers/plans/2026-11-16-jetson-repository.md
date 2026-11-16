# Jetson prototype repository implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Package existing Fire Vision experiments for transfer to Jetson and document board/camera setup.

**Architecture:** Preserve existing Python implementation and experiment records. Add Korean setup documentation, a separate candidate hardware profile, and a self-contained Git bundle if GitHub publication is unavailable.

**Tech Stack:** Git, Markdown, JSON; existing Python package and pytest suite.

**Spec:** User request on 2026-11-16: configure/create a repository for later remote retrieval on Jetson; inspect and save subsequent experiment environment and board setup as Markdown. Existing scope: `Orin_RGBD_IMU_Experiment_Plan.md`.

## Global constraints

- Existing E0 code and original experiment plan remain intact.
- Actual Jetson, camera, and live bag are unavailable; mark hardware values unverified.
- Ubuntu 22.04 / ROS Humble / system Python 3.10 are conditional candidates.
- Never claim E1–E5 or live camera integration already works.
- GitHub publication is authorized; default to a private repository.

## Review focus

- Project `.git` write restriction: preserve a complete repository in an allowed temporary directory and deliver a bundle.
- GitHub connectivity/authentication failure: record failure; provide explicit publication commands without claiming success.
- ARM64/system Python versus macOS lock: document separate environment creation and NumPy ABI constraint.
- Different Gemini model or firmware: inspect exact model, firmware, launch arguments and topics before capture.
- Raw IMU/depth metadata differences: do not present the D435i E0 config as a working Gemini 2 configuration.

## Task 1: Setup documentation and candidate profile

- [x] Add README entry points, setup guide, board checklist, repository transfer guide, and candidate JSON profile.
- [x] Check official NVIDIA, ROS 2, and Orbbec sources and cite them beside relevant claims.
- [x] Parse JSON, check local Markdown links and shell syntax, run the existing pytest suite. No new product code or implementation-mirroring tests.

## Task 2: Repository delivery

- [x] Initialize and commit an allowed temporary repository containing project source and docs, excluding data/results/caches/credentials.
- [x] Attempt private GitHub creation; if unavailable, save a Git bundle and SHA256 into ignored `delivery/`.
- [x] Verify bundle by cloning it locally and running the suite from the clone.
- [x] Report actual deliverables and any publication blocker.

## Execution evidence

- Project-root `.git` write: denied by the execution environment. Temporary delivery repository initialization succeeded.
- GitHub private repository creation: attempted; blocked by API connectivity. CLI authentication check also failed. Browser access was unavailable. No remote repository or URL is claimed.
- Markdown QA: 6 files, 13 local links, 27 bash blocks; shell syntax and JSON parsing passed.
- Initial source suite: 35 passed. A bundle clone exposed an existing test assumption that commit must always be null.
- Updated the test to isolate real Git/non-Git work directories and verify recorded commit provenance; no production code changed.
- Updated clone suite: 36 passed. Final bundle is verified separately in delivery/SHA256SUMS and by cloning.
