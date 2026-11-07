# GridPulse Australia

GridPulse Australia is a compact electricity-demand forecasting demonstrator
for analysts, data engineers and research collaborators. It asks a practical
question: how much can transparent seasonal benchmarks reveal about regional
demand patterns when the source contract, evaluation population and metric
denominators are made explicit?

The project covers the five National Electricity Market (NEM) regions and
keeps Western Australian WEM/SWIS data under its native five-minute contract.
The software validates source files, constructs reproducible rolling-origin
folds, evaluates Python baselines, runs a base-R ARIMA comparison and exposes
the local results through a dependency-free dashboard.

The project site is available at
`https://josephnjiru.github.io/Gridpulse-electricity-demand-forecasting/` once
the GitHub Pages deployment has completed. The site itself contains software
documentation and a clearly labelled synthetic interaction. It does not
redistribute AEMO archives, extracted observations or target-level forecasts.

## What is included

- Safe inspection of official NEM operational-demand ZIP archives.
- Schema, cadence, ordering, duplicate-key, provenance and negative-observation
  checks.
- Previous-day and previous-week seasonal-naive baselines in Python.
- A shared rolling-origin manifest for Python and base-R comparison.
- Canonical MAE, RMSE, sMAPE, WAPE, MASE, RMSSE and bias calculations with
  eligibility counts.
- Independent fixture tests that run without electricity data.
- A local historical dashboard for an owner-held evaluation workspace.

The public tree contains the implementation and independent tests only. Raw
source files and locally generated evaluation outputs remain outside the
repository.

## Run the fixture tests

Python 3.12 or newer is required. From a fresh checkout:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The fixture suite exercises metrics, monitoring decisions, synthetic WA
records, archive safety and rolling-origin behaviour. It does not download
data and it does not require R, Spark or MLflow. The expected result is a
passing suite, with any test that requires an owner-held archive skipped when
that archive is absent.

To check Python syntax separately:

```powershell
.venv\Scripts\python.exe -m compileall -q src tests
```

## Run the local empirical path

The empirical path is intentionally separate from the public fixture check.
Obtain official source files directly from AEMO under the current terms and
keep them in a local `data\raw` directory. Do not commit them. The canonical
project's local commands are:

```powershell
.venv\Scripts\python.exe src\gridpulse.py validate-nem --input data\raw\PUBLIC_ACTUAL_OPERATIONAL_DEMAND_DAILY_20260901.zip
.venv\Scripts\python.exe src\pipeline.py --root .
.venv\Scripts\python.exe src\dashboard.py
```

The pipeline validates the retained NEM collection, evaluates development
folds, invokes a validated Rscript, checks shared region/fold/horizon keys and
target values, and promotes derived outputs only after the checks pass. Use
`--rscript` or the `GRIDPULSE_RSCRIPT` environment variable when Rscript is
not discoverable. R 4.5.2 is needed for the comparison. Spark and MLflow are
optional local extensions and are not required for the fixture suite.

## Forecast design and metrics

For the verified local development study, NEM source coverage spans 365
trading dates, 48 half-hour intervals per date and five regions. The shared
manifest contains 250 development folds, 50 per region. A fold uses 336
historical intervals, forecasts 48 intervals and advances by 336 intervals.
The final 672 intervals per region are reserved and are not scored.

Operational demand is measured in MW using the source market contract. MAE is
the mean absolute error and RMSE weights larger errors more heavily. MAPE is
calculated only for strictly positive actuals. sMAPE and WAPE retain their
documented denominators. MASE and RMSSE use a training-only seasonal scale.
The dashboard reports validity counts rather than converting undefined values
to zero.

This is a retrospective source-order hindcast. Source timestamps are retained
verbatim; public issue-time availability, live dispatch suitability and a
universal UTC conversion are not established. The reserved segment remains
outside development scoring.

## Software structure

```text
src/gridpulse.py       NEM archive validation and loading
src/forecasting.py     seasonal baselines and fold manifests
src/metrics.py         canonical metric definitions
src/wa.py              native WA parser and checks
src/monitoring.py      explicit monitoring decisions
src/dashboard.py       local loopback dashboard
src/pipeline.py        local end-to-end execution
R/forecast.R           base-R ARIMA comparison
tests/                 data-independent regression fixtures
site/                  static project website
```

The static website is separate from the Python dashboard. GitHub Pages serves
HTML, CSS, JavaScript and SVG only; it does not run the local Python server.

## Data access and attribution

The source references are listed in APA 7 style below. Review the current
source-specific terms before obtaining, transforming or redistributing official
records. This repository does not grant permission to redistribute AEMO data.

Australian Energy Market Operator. (n.d.). *Copyright permissions*. Retrieved
November 7, 2026, from
https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions

Australian Energy Market Operator. (n.d.). *Operational demand data*.
Retrieved November 7, 2026, from
https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/operational-demand-data

## Licence and discussion

No software licence is included in this repository. Public visibility should
not be read as a grant of reuse rights. For technical discussion, open an
issue in the [GitHub
repository](https://github.com/JosephNjiru/Gridpulse-electricity-demand-forecasting).

GridPulse is maintained by Joseph Njiru. It is a development evaluation and
working research demonstrator, not a production forecasting service or a
journal publication.
