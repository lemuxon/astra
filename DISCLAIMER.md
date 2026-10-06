# Disclaimer — Financial Risk

**Read this before running any part of this software.**

This software places **leveraged** orders on cryptocurrency exchanges.
Leveraged trading can result in the total loss of deposited funds and, on some
venues, in losses exceeding the initial deposit.

## This software has not been shown to be profitable

As of the last measurement:

| | |
|---|---|
| Mode | Binance **testnet** (play money) |
| Closed paper trades | 0 / 100 required for a verdict |
| Strategy hypotheses tested | **9** |
| Hypotheses rejected | **9** |
| Demonstrated statistical edge | **none** |

The order pipeline works end to end — signal → veto chain → order on the
exchange → stop-loss and take-profit placed. **Profitability is a separate
claim, and it has not been established.**

`karar_kurali.py` requires 100 closed trades, expectancy above 0.10% and
t > 2.0 before the project will state any verdict. Those thresholds were
written before any data existed. A verdict of "no edge" is a possible and
legitimate outcome.

## No financial advice

Nothing in this repository is financial, investment or trading advice. The
authors are not licensed advisors. You alone are responsible for any funds you
risk and for complying with the laws and exchange rules that apply to you.

## Liability

The software is provided "as is", without warranty of any kind. The authors
accept no liability for trading losses, missed trades, incorrect orders,
exchange outages, data errors or any other damages, as stated in the warranty
disclaimer of the [MIT License](LICENSE).

## If you intend to run it anyway

- Keep `FUTURES_BASE_URL` pointing at `https://testnet.binancefuture.com`.
- Keep `LIVE_TRADING=false` until you have deliberately decided otherwise and
  have read `CANLI_GECIS_PROTOKOLU.md`.
- Never give the API key withdrawal permission. See [SECURITY.md](SECURITY.md).
- Risk only money whose total loss would not affect you.
