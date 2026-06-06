# Portfolio Dashboard — Backlog

Durable list of known issues and deferred work captured but **not** scheduled into the
current plan. Each item should carry enough of a repro to act on later. This file is
permanent (unlike the temporary instruction drops in this folder).

---

## Open

### BUG — Some stocks calculate dividends incorrectly
- **Reported:** 2026-06-06, by the external clean-machine tester (same thread as Item A).
- **Severity:** Minor→Medium (does not break the app; produces wrong dividend figures for
  *some* tickers). **Explicitly out of scope for Item A** — captured here, not fixed there.
- **Status:** Awaiting a concrete repro before any fix is attempted.
- **Repro needed from tester (to fill in):**
  - Which ticker(s) show wrong dividend numbers.
  - Expected vs. actual dividend amount (and for which period / payment date).
  - The broker/source the affected rows were imported from.
  - Whether the ticker is foreign-currency (FX-converted) or CAD — the dividend tracker
    projects upcoming payments from observed cadence and converts at the trade-date FX rate,
    so the bug may be in cadence inference, FX-at-date, or yield-on-cost.
- **First places to look once a repro exists:** the dividend tracker / income aggregation in
  the portfolio computation (monthly history, trailing-12-month, projected-upcoming), and the
  per-row `net_cad` population for `DIVIDEND` actions.

### Item A follow-ups (pending tester artifact / clean machine)
- **A2 — backend fails to start on a clean box:** real root cause still undiagnosed; the dev
  box can't reproduce (Defender exclusions). 0.6.4 now surfaces the backend error instead of
  hanging — waiting on the tester's error-dialog text + `%APPDATA%\Portfolio Dashboard\backend.log`.
- **A1 — installer created no shortcut:** config was already correct in v0.5.3
  (`createDesktopShortcut`/`createStartMenuShortcut` true); real cause needs the clean-machine
  repro.
- **Location prompt wording:** our code has zero geolocation calls (git-grep confirmed); tester
  to capture the exact prompt text so we can identify the true source (SmartScreen / Defender /
  Firewall) and decide whether a README/installer note is warranted.
