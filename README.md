# Residual Alpha

A dependency-free research engine for intraday factor-residual mean reversion. It estimates each stock's expected return from contemporaneous market and sector factors, trades extreme residuals, and projects the resulting portfolio away from dollar, market-beta, and sector-beta exposures.

This is a backtesting and paper-trading research tool, not live order-routing software.

## Method

For each bar and security, the engine fits a rolling ridge regression using only earlier observations:

```text
stock return = intercept + market beta × market return
             + sector beta × sector return + residual
```

The current residual is standardized against its trailing history. Extreme positive residuals are short candidates; extreme negative residuals are long candidates. Raw signals are projected onto the factor-neutral subspace and normalized to a configured gross exposure.

Signals calculated at the close of bar `t` first earn the return of bar `t+1`. Turnover costs are charged when target weights change. Positions are flattened before the final bar of each trading day.

## Input data

Supply a complete long-form CSV with one row per symbol and bar:

```csv
timestamp,symbol,close,sector
2025-01-02T09:30:00,AAPL,243.12,Technology
2025-01-02T09:30:00,MSFT,421.50,Technology
```

All symbols must have a price at every timestamp in this initial version. Use split- and dividend-adjusted intraday prices, a survivorship-bias-free universe, and point-in-time sector classifications for serious research.

## Quick start

Run directly from the repository without installing anything:

```sh
python3 -m residual_alpha.cli generate-demo demo.csv --bars 500
python3 -m residual_alpha.cli backtest demo.csv --output results
```

Outputs:

- `metrics.json`: summary performance statistics
- `equity.csv`: timestamped net returns, equity, and turnover
- `weights.csv`: target portfolio weights

Run the tests:

```sh
python3 -m unittest discover -s tests -v
```

## GitHub and hourly Discord reporting

The repository includes `.github/workflows/hourly-research.yml`. GitHub Actions runs it at minute 17 of every hour; scheduled execution times can be delayed during periods of heavy GitHub Actions demand.

Before enabling it:

1. Push this directory to a GitHub repository.
2. In the repository, open **Settings → Secrets and variables → Actions**.
3. Create a repository secret named `DISCORD_WEBHOOK_URL` containing your Discord webhook URL.
4. Arrange for a fresh, complete input file to exist at `data/intraday.csv` before each run, or replace the input step with your market-data download command.
5. Open **Actions → Hourly residual-alpha report → Run workflow** to test it manually.

The workflow runs the tests, validates that real input data exists, runs the backtest, sends summary metrics to Discord, and retains output artifacts for 14 days. A failed run produces a separate Discord alert when the webhook is configured.

Market data is intentionally not committed: `data/*.csv` is ignored to avoid publishing licensed or sensitive datasets. For production, retrieve it during the workflow from a provider using a GitHub secret rather than storing credentials in code.

## Controls that should precede live deployment

- Replace equal-weighted in-universe factor proxies with independently tradable market and sector benchmarks.
- Estimate fills from quotes, not bar closes, and model latency, spread, impact, partial fills, and rejected orders.
- Add liquidity, price, volatility, news, halt, earnings, borrow, and short-sale filters.
- Use point-in-time membership data and delisted securities.
- Add per-name, sector, gross, turnover, drawdown, and stale-data kill switches.
- Validate parameters using purged walk-forward tests rather than selecting them on the full sample.
- Paper trade through the intended broker before enabling any live orders.

## Important modeling limitation

The current market and sector factors are cross-sectional averages computed from the same universe. This makes the package useful for validating the residual-trading architecture, but it is not yet an institutional-quality factor model. The next production step is to feed point-in-time market and sector benchmark returns and hedge instruments into the model explicitly.
