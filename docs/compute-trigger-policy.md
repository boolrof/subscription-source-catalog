# Catalog Compute trigger policy

Catalog Compute v2 normally runs after a successful `Scheduled Discovery` workflow and can also be invoked manually through `workflow_dispatch`.

For code changes to the compute implementation itself, the workflow may also run on pushes to `main` that modify only the compute workflow or compute implementation/test files. Generated catalog/data commits are deliberately excluded from those push path filters so the compute job cannot trigger itself recursively.

This code-change trigger provides an immediate operational smoke of the passive pre-admission pipeline after reviewed changes are merged.
