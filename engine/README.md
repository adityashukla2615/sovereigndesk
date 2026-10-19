# sovereign-engine

The pure quant core of SovereignDesk. Every public function is a pure computation (no I/O, no clocks, no global state) with its formula written out in an `Equation:` docstring section and a unit test against a textbook or closed-form anchor.

Subpackages arrive phase by phase (see [docs/PLAN.md](../docs/PLAN.md)): `bonds`, `curves`, `rates`, `us`, `india`, `linkage`, `predict`, `replay`.
