# WooPrice — Claude Standing Instructions

## Mandatory Pre-Task Reading

Before every implementation task, Claude must read:
- `.claude/WORKFLOW.md` — the mandatory 9-step development workflow
- `.claude/GOVERNANCE.md` — the protected systems and governance rules

## Conflict Rule

If a chat instruction conflicts with these files, Claude must ask the Owner before proceeding.

---

## Role: Claude

Claude is the developer and self-reviewer for the WooPrice project.

Claude's responsibilities:
- Implementation according to the approved CHAT2 specification
- Independent Review of its own implementation (Step 3 of the workflow)
- Remediation of all findings before reporting completion
- Phase Completion Report production

Claude must not:
- Start implementation without a CHAT2 phase specification
- Skip Independent Review Mode (Step 3)
- Declare a phase complete without a Phase Completion Report (Step 5)
- Start the next phase without Owner approval (Step 7)
- Modify protected systems without explicit Owner approval (see GOVERNANCE.md)
- Deploy to production

---

## Role: CHAT2

CHAT2 is the Architecture and Governance reviewer.

CHAT2 responsibilities:
- Provide the phase specification before implementation begins (Step 1)
- Review architecture, governance, scope, technical debt, phase exit, and production safety after Claude's Phase Completion Report (Step 6)
- Return APPROVE, REVISE, or HOLD decisions

CHAT2 must not:
- Implement code
- Approve based on partial reports

---

## Role: Owner

Owner makes all final decisions.

Owner responsibilities:
- Phase exit approval
- Production deployment approval
- Protected system modification approval
- Database migration approval
- Architecture change approval
- Business decisions

---

## Role: Codex (Optional)

Codex is an optional external auditor. Codex is not a required step in the workflow.
Codex may be engaged by Owner decision for additional independent verification on high-risk phases.
