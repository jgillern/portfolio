# ADR 0004: ETF proxy benchmarks

Status: accepted

Phase one uses configurable accumulating UCITS ETF proxies rather than licensed index total-return series.

The defaults are IE00B5BMR087 for S&P 500, IE00B4L5Y983 for MSCI World and IE00B6R52259 for MSCI ACWI. The selected listing is configured by available price coverage.

UI and API output call these series ETF proxy benchmarks and disclose TER, tracking, tax, market-hours and currency differences. Comparison starts at 100 and uses the same reporting currency as the portfolio.
