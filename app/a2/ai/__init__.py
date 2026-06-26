"""A2.9 AI Foundation — advisory intelligence package.

Isolation boundary (A2.9 only):
- This package is ONE-WAY dependent on prior A2 phases. Prior phases must NEVER
  import from app.a2.ai.
- No code in this package may trigger execution, scheduling, dry run, or any
  write to a destination channel.
- The only output object is AdvisoryInsight. No executable domain objects are
  produced.
"""
