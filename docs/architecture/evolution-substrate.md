# Evolution Substrate

The evolution substrate design is now documented in [docs/EVOLUTION_CORE.md](../EVOLUTION_CORE.md),
which is the single source of truth for the current implementation: core objects, run flow,
prompt contract, experience solidification, validation, and memory boundary.

This file is kept as a directory-level pointer only. The historical design motivation behind
the substrate concept was: keep improvement loops inside the product boundary by making
targets, signals, strategies, selector decisions, and experiences first-class runtime
objects rather than external optimizer state.
