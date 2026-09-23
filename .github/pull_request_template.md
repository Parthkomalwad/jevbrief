## What this changes

<!-- One or two sentences. Link the issue: "Closes #12". -->

## Checklist

- [ ] `pytest -q` passes
- [ ] No change to the core API, or the change is discussed in an issue first

### For a new adapter (see ADAPTERS.md)

- [ ] Extractor, rules, question pack, reason codes (`<adapter>.<code>`) with descriptions
- [ ] `check_adapter` passes, plus one test per reason code
- [ ] Benchmark tasks and `results.md` with honest caveats
- [ ] Example in `examples/` and docs in `docs/adapters/<name>.md`
- [ ] README adapter table updated
- [ ] Optional dependencies in an extra, imported lazily
