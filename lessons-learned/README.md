# lessons-learned

A standing **training-pair set** for this repo. Every entry ties a concrete model
output to its corrective pair, so mistakes found while building or reviewing this
codebase become reusable supervision instead of being silently patched.

## Format

`training_pairs.jsonl` — one JSON object per line. Schema:

| field | meaning |
|-------|---------|
| `id` | stable slug for the lesson |
| `source_model` | the model that produced `model_output` (e.g. `kimi-k2.5`) |
| `repo` | originating repository |
| `file` | path(s) the lesson came from |
| `severity` | `high` / `medium` / `low` |
| `pattern` | one-line label for the recurring failure mode |
| `prompt` | the task/instruction the model was given |
| `model_output` | **what the model actually produced** (the rejected side) |
| `correction` | the corrected output (the chosen side) |
| `rationale` | why `model_output` is wrong and `correction` is right |

This maps directly onto common training setups:
- **SFT** — train on `prompt` → `correction`.
- **Preference / DPO** — `correction` is *chosen*, `model_output` is *rejected*, for the same `prompt`.

## How to add a lesson

When you fix a real bug in this repo (or catch one in review), append a record that
pairs the exact buggy output with the fix and names the pattern. Keep `model_output`
faithful to what was actually generated — the value is in tying output to correction,
not in idealized examples. Keep snippets minimal but runnable-in-context.

## Current set

`kimidoesitlikethis` pairs are drawn from bugs in the Kimi K2.5-authored integration
tools. The dominant pattern is *"plausible surface, dropped follow-through"*: the right
inputs are set up (a header is fetched, a parameter is accepted, an intent is stated in
a comment) and then never used or contradicted.
