# Residual Alpha

A research engine for intraday factor-residual mean reversion. It estimates each stock's expected return from contemporaneous market and sector factors, trades extreme residuals, and projects the resulting portfolio away from dollar, market-beta, and sector-beta exposures.

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

Install the project and run it:

```sh
python3 -m pip install .
python3 -m residual_alpha.cli generate-demo demo.csv --bars 500
python3 -m residual_alpha.cli backtest demo.csv --output results
```

Refresh the current S&P 500 constituents and download the rolling Yahoo Finance intraday panel:

```sh
python3 scripts/refresh_sp500_universe.py --output data/sp500_universe.csv
python3 scripts/fetch_yfinance.py --universe data/sp500_universe.csv --output data/intraday.csv --period 5d --interval 5m --batch-size 50
```

Outputs:

- `metrics.json`: summary performance statistics
- `equity.csv`: timestamped net returns, equity, and turnover
- `weights.csv`: target portfolio weights
- `candidates.json`: latest ranked long/short model candidates for automation
- `latest_signals.csv`: human-readable latest candidates, residual z-scores, and neutral weights

Discord also highlights one single-name paper setup selected from current entry-threshold candidates. Signals beyond an absolute z-score of 5 are excluded from that featured slot as potential event or data outliers. The setup includes approximate SPY and sector-ETF hedges derived from the model coefficients, permits new paper entries only from 10:00 a.m. through 2:30 p.m. Eastern, and states convergence, 120-minute, and 3:50 p.m. exits. Yahoo is not a dependable real-time news/earnings safety source, so the report requires a manual company-news and earnings check before entry.

The locked single-name simulator matches the hourly deployment cadence: decisions use completed bars around 40 minutes past each hour, it permits at most one new position per trading day, and it checks convergence or widening at subsequent hourly decisions. It exits after two hours or at the final intraday decision before the close. This intentionally avoids pretending that an hourly GitHub workflow can monitor five-minute exits in real time. Each Discord report also shows up to five ranked alternative candidates as an observation-only watchlist. Watchlist names are not entered, managed, or included in the official strategy results.

## Validation status

The exact locked, hourly, one-entry-per-day specification was tested on one month of available five-minute data with actual SPY and sector-ETF hedge returns and one-basis-point entry/exit turnover costs. It lost 1.82% over 23 completed trades, with a 43.5% win rate, 0.43 profit factor, and 3.02% maximum drawdown. The result is stored in `config/validation.json` and the Discord report displays a failed validation gate. Model actions are observation-only until a genuinely out-of-sample specification passes a longer and more complete test.

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
4. Open **Actions → Hourly residual-alpha report → Run workflow** to test it manually.

The workflow checks New York time and performs scheduled data downloads only on weekdays between 9:30 a.m. and 3:55 p.m. Eastern. Runs occur near 47 minutes past each hour, producing about seven reports on a normal market day. Manual workflow runs bypass the time gate. Each active run installs the project, runs the tests, refreshes the current S&P 500 constituents and GICS sectors, downloads five days of five-minute data from Yahoo Finance in batches of 50, runs the backtest, and sends summary metrics plus the five largest long and short residual candidates to Discord. It retains output artifacts for 14 days. A failed run produces a separate Discord alert when the webhook is configured.

Market data and the refreshed S&P 500 snapshot are intentionally not committed: `data/*.csv` is ignored to avoid publishing downloaded datasets. The original 30-stock universe remains in `config/universe.csv` as a small local smoke-test fallback.

The hourly signal window is five trading days because the active model needs only 60 bars for beta estimation and 30 bars for residual normalization. This controls runtime and Yahoo request volume. It is not a substitute for a long-history, point-in-time constituent backtest: the refreshed list contains current constituents and would introduce survivorship bias if treated as a historical universe.

Every current constituent is requested, but a stock is excluded from that run if Yahoo omits it or its five-minute series fails the completeness check. Discord reports the number actually evaluated. This preserves signal integrity instead of manufacturing prices for the sake of claiming exactly 500 usable stocks.

The newest Yahoo interval is discarded before modeling because it may still be forming. Candidate signals therefore use the most recently completed five-minute bar rather than a partial bar whose tiny return could suppress every entry signal.

Yahoo Finance data is used only for personal research and educational purposes. yfinance is an unofficial client, and an hourly run may fail because of upstream availability or rate limiting. No order is submitted when data is missing or incomplete.

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
