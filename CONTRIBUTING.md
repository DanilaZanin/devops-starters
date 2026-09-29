# Contributing

A new module or a fix is welcome if it comes with a trap test:

1. Describe the trap in the module README: the symptom, a link to a real issue or question, and the fix.
2. Add a broken variant that reproduces it. `make test` must fail if the broken variant passes.
3. Keep the module self-contained: its own Makefile with `up`, `test`, `down`, `reset`, `check-prereqs`, and no references outside the folder.
4. Pin every image, chart and tool version. No `latest`.
5. Add `.github/workflows/<module>.yml` with the path filter, the weekly schedule and the copy-test step.
