# 9. Headless CLI — batch automation

Every workflow the desktop app runs is also exposed as a
``magnadesign`` CLI subcommand. Use the CLI for:

- **Continuous integration** — verify every checkpoint of
  your customer's spec sheet builds a feasible design.
- **Batch sweeps** — DOE / what-if studies across a parameter
  space without clicking through 100 GUI runs.
- **Regression testing** — pin a `.pfc` reference design to a
  CI gate so an engine-side refactor can't silently change
  the L_actual or P_total.
- **Headless servers** — Linux / macOS without an X display.
  All CLI subcommands work on a headless box (FEA included,
  if ONELAB is installed).

```console
$ magnadesign --help
Usage: magnadesign [OPTIONS] COMMAND [ARGS]...

  MagnaDesign CLI — design / sweep / cascade / report / validate.

Commands:
  design       Run the engine on a single .pfc file.
  sweep        Catalogue sweep against the spec.
  cascade      Multi-tier optimiser with FEA cross-check.
  report       Generate the datasheet / project report PDF.
  compare      Build a comparison PDF / HTML / CSV.
  validate     Run FEA validation on a single design.
  worst-case   DOE corner sweep + yield estimate.
```

## 9.1 ``magnadesign design``

Runs the engine on a single project file:

```console
$ magnadesign design examples/600W_boost_reference.pfc --pretty
project      600W boost reference
topology     boost_ccm
material     60_HighFlux
core         C058777A2
wire         AWG14
L_target_uH  747.45
L_actual_uH  762.81
N_turns      61
B_pk_mT      269.2
B_sat_pct    27.1
T_winding_C  103.4
T_rise_C     63.4
P_total_W    3.36
status       FEASIBLE
```

Add `--json` instead of `--pretty` for machine-parseable output.

## 9.2 ``magnadesign sweep``

Closed-form sweep across the catalogue (Tier 1 only). Fast
(~1 s) and good for "is anything feasible" questions:

```console
$ magnadesign sweep examples/600W_boost_reference.pfc \
    --top-n 10 --output ranking.csv
```

Outputs a sorted CSV of `material,core,wire,L_actual_uH,
P_total_W,T_winding_C,B_pk_mT,status`.

## 9.3 ``magnadesign cascade``

Full multi-tier optimiser (Tier 0 → Tier 4). Same engine the
GUI's Optimizer page runs:

```console
$ magnadesign cascade examples/600W_boost_reference.pfc \
    --top-n 30 --top-k 5 --fea \
    --output sweep.json
```

The ``--fea`` flag enables Tier 3 / Tier 4 FEA cross-checking
(slow — 30 s per top-k candidate). Skip for a sub-minute run;
turn on for the definitive ranking.

## 9.4 ``magnadesign report``

Generates either the datasheet or the project report PDF
from a `.pfc`:

```console
$ magnadesign report examples/600W_boost_reference.pfc \
    --kind datasheet \
    --output datasheets/600W_boost.pdf
$ magnadesign report examples/600W_boost_reference.pfc \
    --kind project \
    --output reports/600W_boost.pdf
```

`--kind` accepts `datasheet`, `project`, or `both` (writes
two files alongside the path).

## 9.5 ``magnadesign compare``

Builds a comparison artefact from N `.pfc` files:

```console
$ magnadesign compare *.pfc --output compare.pdf
```

`--output` extension picks the format (`.pdf`, `.html`, `.csv`).

## 9.6 ``magnadesign validate``

Runs FEA on a single design:

```console
$ magnadesign validate examples/600W_boost_reference.pfc \
    --backend femmt \
    --keep-files \
    --output-dir /tmp/fea-debug
```

`--keep-files` preserves the gmsh `.geo` and getdp `.pos`
artefacts so you can open the FE result manually in gmsh's GUI.

## 9.7 ``magnadesign worst-case``

DOE corner sweep — runs the engine across the spec's tolerance
corners (Vin range, T_amb range, fsw range) and reports the
yield (fraction of corners where the design stays feasible):

```console
$ magnadesign worst-case examples/600W_boost_reference.pfc \
    --corners 27 \
    --output yield.json
```

27 = 3 × 3 × 3 corners (Vin / T_amb / fsw, each at min /
nominal / max). Higher corner counts give finer yield
resolution.

## 9.8 Exit codes

All subcommands follow the standard:

- ``0`` — success.
- ``1`` — feasibility failure (the engine ran but the design
  didn't meet the spec's constraints).
- ``2`` — usage error (bad arguments, file not found).
- ``3`` — engine error (crash inside the engine, not a design
  feasibility issue).

CI gates can `exit-on-failure` against ``$? -ne 0`` to catch
both engine breakage and feasibility regressions.

## 9.9 Combining with other tools

The CLI's stdout is structured (JSON or table) so it composes
with shell tools:

```console
# Check if any catalogue core gives < 50 °C ΔT for a spec
$ magnadesign sweep my-spec.pfc --json | \
    jq '[.[] | select(.T_rise_C < 50)] | length'
```

```console
# Re-run validation across every project in a folder, gate on
# any FEA error > 10 %.
$ for f in projects/*.pfc; do
    magnadesign validate "$f" --json | \
        jq -e '.L_pct_error | abs < 10' || \
        echo "FAIL: $f" >> validation-fails.log
done
```

For more complex pipelines, the CLI is implemented on top of
the Python API in ``pfc_inductor.cli`` — drop into the API
directly if shell-piping gets unwieldy.
