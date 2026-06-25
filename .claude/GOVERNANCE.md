# WooPrice — Governance Rules

## Protected Systems

The following systems require explicit Owner approval before any modification:

- Apply Workflow
- Dry Run Workflow
- Emergency Apply
- JWT/Auth
- Pricing Validation
- WooCommerce Write Path
- Database Migrations
- Maintenance Mode
- Production Deployment
- Rollback / Undo

## Rules

- Protected systems require explicit Owner approval before modification.
- Database migrations require explicit Owner approval.
- Production deployment requires explicit Owner approval.
- A2 work must remain additive until reconciliation and parity verification pass.
- No production cutover without Owner approval.
- No Apply, Dry Run, Safety Engine, Change Set, Execution, or WooCommerce write logic may be introduced outside its approved phase.
- If scope creep is detected, stop and report to Owner immediately.
