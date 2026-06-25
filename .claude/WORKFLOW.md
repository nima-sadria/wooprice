# WooPrice — Implementation Workflow

This is the mandatory 9-step workflow for every WooPrice phase. No step may be skipped.

---

## Roles

| Role | Responsibility |
|---|---|
| CHAT2 | Architecture and Governance reviewer; provides specs; reviews phase exit |
| Claude | Developer and self-reviewer; implements, reviews, remediates, reports |
| Owner | Final decision authority for phase exit, deployment, and protected systems |
| Codex | Optional external auditor (not a required workflow step) |

---

## Step 1 — CHAT2: Phase Specification

CHAT2 provides the phase specification before any implementation begins.

Gate: Claude must not start Step 2 without a CHAT2 specification.

---

## Step 2 — Claude: Implementation

Claude implements according to the approved specification.

Requirements:
- All work must be within the approved scope
- No protected systems may be modified without explicit Owner approval (see GOVERNANCE.md)
- No A2 phase logic (Apply, Dry Run, Safety Engine, Change Set, Execution, WooCommerce write logic) may be introduced outside its approved phase

---

## Step 3 — Claude: Independent Review

Claude reviews the implementation as if written by another engineer.

Review must cover:
- Architecture Review
- Security Review
- Production Safety Review
- Governance Review
- Scope Review — detect and report any scope creep
- Documentation Review
- Test Review
- Build Status — `npm run build` must pass (if frontend changes present)
- Test Status — `pytest` must pass (all tests)

Claude must list all findings before proceeding. If no findings, state "No findings."

---

## Step 4 — Claude: Remediation

If any findings exist from Step 3:
- Claude must produce a remediation plan listing all findings
- Claude must implement all fixes
- Claude must re-run all tests and builds after remediation
- Claude must not proceed to Step 5 while any finding remains unresolved

---

## Step 5 — Claude: Phase Completion Report

Claude produces the Phase Completion Report. This report is required before CHAT2 review.

The report must contain:
- Implementation Status
- Architecture Compliance
- Governance Compliance
- Production Safety
- Build Status (pass/fail + output summary)
- Test Status (pass/fail + count)
- Documentation Status
- Known Risks
- Technical Debt
- Phase Exit Recommendation

Claude must not declare a phase complete without this report.

---

## Step 6 — CHAT2: Architecture and Governance Review

CHAT2 reviews the Phase Completion Report and the implementation.

CHAT2 review covers:
- Architecture Review
- Governance Review
- Roadmap Tracking
- Technical Debt Review
- Phase Exit Validation
- Production Safety Validation

CHAT2 returns one of:
- **APPROVE** — proceed to Step 7 (Owner Decision)
- **REVISE** — Claude must return to Step 4 (Remediation) and produce a new Phase Completion Report
- **HOLD** — stop; escalate to Owner before any further action

---

## Step 7 — Owner: Decision

Owner makes the final phase exit decision.

Owner approvals cover:
- Business Approval
- Architecture Approval
- Phase Exit Approval
- Production Deployment Approval (if applicable)

Gate: Claude must not proceed to Step 8 without explicit Owner approval.

---

## Step 8 — GitHub: Commit and Push

After Owner approval:
- Stage only the files that were intentionally changed (never `git add -A` or `git add .`)
- Commit with a message following the commit policy in `docs/WORKFLOW.md`
- Push to the approved branch
- Tag optional

---

## Step 9 — Phase Closed / Next Phase Begins

Phase is formally closed. Next phase may begin only when:
- Owner has approved phase exit (Step 7)
- Step 8 commit is complete
- CHAT2 has provided the next phase specification (Step 1 of next cycle)

---

## Rules

- Claude must never skip Independent Review Mode (Step 3).
- Claude must never start remediation without listing findings first.
- Claude must never declare a phase complete before the Phase Completion Report (Step 5).
- Claude must never start the next phase without Owner approval (Step 7).
- If CHAT2 returns REVISE or HOLD, Claude must return to Step 4 before any further progress.
- If scope creep is detected at any step, Claude must stop and report to Owner immediately.
