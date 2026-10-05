# Contributing to ASTRA

Thanks for looking. This project has one unusual rule that shapes everything
else, so please read the first section before writing code.

---

## The one rule: measure, don't assume

Almost every bug found in this project was found by **measuring**, and several
were *created* by assuming. A few real examples from the log:

- A threshold was believed to adapt to volatility. Measured: the median coin was
  already pinned to its hard ceiling, so the adaptation never did anything.
- A veto was labelled "no timeframe alignment". Measured: it fired exactly when
  one specific timeframe was neutral — it wasn't measuring alignment at all.
- A safety gate meant to block resets while the bot runs returned `False` *while
  the bot was running*, because PowerShell unwraps single-element arrays.

So: **if your PR claims a behaviour, show the measurement.** A command and its
output in the PR description is enough. "This should be faster" is not a claim
anyone can check; "100 signals took 4.2s, now 1.1s, here's the command" is.

---

## Tests

```bash
python testleri_calistir.py   # must print ✅ TÜM TESTLER BAŞARILI (554 tests)
```

### Every guard test needs a control test

A test that only asserts "X is blocked" is also passed by code that blocks
**everything**. For each veto test, add the opposite:

```python
def test_bad_signal_is_rejected():      # the guard
    assert gate(bad_signal) is False

def test_good_signal_is_ACCEPTED():     # the control — without this the guard is meaningless
    assert gate(good_signal) is True
```

### Prove your test can fail

After writing a guard, **deliberately break the protection** and confirm the
test turns red. Then undo the break. A test that cannot fail is worse than no
test, because it looks like coverage.

Also verify your *mutation* actually applied — a find-and-replace that silently
matched nothing produces a false "the test caught it" conclusion.

### Don't test source text

```python
assert "my_function" in source   # ← matches the import line too
```

A mutation that deletes the *call* still passes this. Drive the real code path
instead. If you must inspect source, search for the assignment
(`= my_function(`), and strip comment lines first — explanatory comments quoting
the old code will match.

### Register new test files

Add the path to the list in `testleri_calistir.py`. Unregistered files are
silently skipped — `tests/test_kosucu_kapsami.py` enforces this.

### Tests must not touch production state

Call `izole_et()` from `tests/izolasyon.py` **before importing project
modules** (`config.py` reads paths at import time). If you add a new persistent
file, make its path environment-overridable, add it to `URETIM_YOLLARI`, **and**
set its env var inside `izole_et()`. Doing only the first two leaves it exposed.

Tests must also not depend on the exchange. Mock `acik_futures_pozisyonlar` —
a test that passes only when the account happens to be empty is not a guard.

---

## Paper and live must stay identical

`engines/paper_trading.py` (simulation) and `main.py::_execution_isle` (live)
must apply the **same gates with the same thresholds**. If they diverge, the
collected sample stops representing live behaviour and the entire 100-trade
verdict becomes meaningless.

This broke repeatedly. When you add or change a gate, put the logic in a
**shared function** (see `engines/futures_trade_engine.py::sinyal_veto_zinciri`)
and call it from both paths. Don't copy it.

If your change alters entry or exit behaviour, say so in the PR — it implies a
counter reset for anyone collecting data.

---

## Don't tune thresholds to results

`karar_kurali.py` thresholds (100 trades, expectancy > 0.10%, t > 2.0) were
written before any data existed. Changing them because the result came out
unfavourable invalidates the test. Same for regime thresholds, R/R minimums and
position caps.

Finding that two components *structurally contradict* each other is different
and welcome — that's a logic bug, not threshold tuning. Show the measurement.

---

## Fail closed, not open

"I couldn't determine X" must never be treated as "X is fine":

```python
# wrong — an API error reads as "no open positions"
except Exception:
    return []

# right
def acik_pozisyonlar(strict=False):
    ...
    if strict:
        raise
```

Silent `except` blocks that swallow errors at `debug` level are how several bugs
survived for months. If something fails, make it visible.

---

## Pull requests

- One concern per PR. Refactor and bugfix in **separate** commits — if something
  breaks, nobody can tell which caused it.
- Include the measurement.
- Say whether behaviour changed.
- Comments explaining *why* are valued here, especially the non-obvious "we
  tried the simpler thing and it was wrong because…" kind.

Code comments and internal docs are largely Turkish. English PRs are fine;
translation contributions are very welcome.

---

## Good first issues

- **The open bug:** paper opens 0 trades while live opens 5. Both receive the
  same `sonuc` object in `main.py`, so the paper path has an early return the
  live path lacks. See `DEVAM_NOTLARI.md` §0.44.
- Translate `DEVAM_NOTLARI.md` sections to English.
- Dashboard shows `kaynak: None` and empty protection fields for *live*
  positions — the panel field mapping was written for the paper record schema.
- Increase coverage of `main.py` (the weakest area).

---

## Security

Found something sensitive? See [SECURITY.md](SECURITY.md) — please don't open a
public issue for it.
