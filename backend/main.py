"""FastAPI app. Binds to localhost:7842 in dev and prod.

Electron launches this via PyInstaller; CORS allows the Vite dev server and
the production Electron `app://` scheme.
"""
from __future__ import annotations

import logging
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend import alerts, annual_report, db, excel_export, market_data, portfolio, profiles, rebalance, simulator, store, tax_report, tfsa
from backend._time import utcnow_naive as _now
from backend.models import (
    AppSettings,
    AttributionReport,
    BenchmarkPoint,
    CapitalGainsReport,
    CorrelationMatrix,
    DividendReport,
    HistoricalDataPoint,
    Holding,
    ImportResult,
    RebalanceRequest,
    RebalanceResponse,
    SimBuyRequest,
    SimSellRequest,
    SimLumpSumRequest,
    SimulationResult,
    ImportStatus,
    PortfolioData,
    PortfolioStats,
    PortfolioValuePoint,
    PriceAlert,
    PriceAlertCreate,
    PriceRefreshResult,
    PriceStatus,
    ResolvedTicker,
    UnresolvedTicker,
)
from backend.parser import UnknownFormatError, parse_file


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialise profile system + bind the engine to the active profile's DB on startup."""
    # Initialise profiles (auto-creates a default on first run) and bind the
    # engine to the active profile's DB.
    try:
        active = profiles.get_active_profile()
        db.set_db_path(profiles.profile_db_path(active.id))
        logger.info("Active profile %s (%s)", active.name, active.id)
    except Exception as e:
        logger.warning("Profile init failed, falling back to legacy DB path: %s", e)
    db.get_engine()  # ensure tables exist
    logger.info("DB ready at %s", db.resolve_db_path())
    # Surface bundled-vs-source parity: log every parser the registry sees.
    # If this list is shorter than 12 in a PyInstaller bundle, hiddenimports
    # are missing and imports will fall back to "generic" → KeyError.
    from backend.parsers import BROKER_PARSERS
    logger.info("Parsers registered (%d): %s", len(BROKER_PARSERS), sorted(BROKER_PARSERS.keys()))
    yield


app = FastAPI(title="Portfolio Dashboard", version="0.5.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "app://-",  # electron production scheme
        "file://",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _add_utf8_charset(request, call_next):
    """Stamp `charset=utf-8` on every JSON response.

    Without an explicit charset, some downstream consumers (Excel / certain
    PDF readers / older Windows clipboard sinks) interpret bytes as cp1252,
    which mojibakes the em-dashes, arrows, and Unicode symbols the simulator
    and rebalancer responses use ("→", "·", "×").
    """
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.exception_handler(Exception)
async def _global_error(request, exc: Exception):
    """Catch-all error handler that returns a structured JSON envelope instead of an HTML 500 page."""
    logger.exception("Unhandled: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": exc.__class__.__name__, "detail": str(exc), "timestamp": _now().isoformat()},
    )


# ---------- health ----------

@app.get("/health")
def health() -> dict:
    """Liveness probe used by Electron's startup health check. Returns DB path and size."""
    return {
        "status": "ok",
        "db_path": str(db.resolve_db_path()),
        "db_size_kb": db.db_size_kb(),
    }


# ---------- import status ----------

@app.get("/api/import/status", response_model=ImportStatus)
def import_status() -> ImportStatus:
    """Whether the active profile has imported transactions, with last-import metadata if so."""
    has = store.has_any_transactions()
    return ImportStatus(
        has_data=has,
        last_import=store.get_last_import_info() if has else None,
    )


# ---------- import ----------

@app.post("/api/import", response_model=ImportResult)
async def import_file(file: UploadFile = File(...)) -> ImportResult:
    """Multi-broker file upload handler. Auto-detects Questrade/Wealthsimple, parses, dedupes by SHA-256 hash, resolves tickers, returns counts."""
    started = time.time()
    suffix = Path(file.filename or "upload").suffix.lower() or ".xlsx"
    tmp = Path(tempfile.gettempdir()) / f"portfolio_upload_{int(time.time() * 1000)}{suffix}"
    try:
        with open(tmp, "wb") as f:
            f.write(await file.read())

        try:
            txs, fmt = parse_file(tmp)
        except UnknownFormatError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Resolve any tickers we haven't seen.
        # The parser already resolves common cases (`.TO` suffix, known description
        # patterns like APPLE INC → AAPL). For those we just persist the parser's
        # result into ticker_map. We only invoke yfinance.search() when the parser
        # couldn't resolve the symbol on its own — otherwise the search returns
        # wrong matches for Questrade internal IDs (e.g. A603109 → APC.DU).
        ticker_map = store.get_ticker_map()
        new_resolved: list[str] = []
        unresolved: list[str] = []
        seen_raws: set[str] = set()
        for t in txs:
            if not t.raw_symbol or t.raw_symbol in seen_raws:
                continue
            seen_raws.add(t.raw_symbol)
            existing = ticker_map.get(t.raw_symbol.upper())
            if existing and existing.status == "resolved" and existing.resolved_ticker:
                if not t.resolved_ticker:
                    t.resolved_ticker = existing.resolved_ticker
                continue

            if t.resolved_ticker:
                # Parser already resolved this — just persist the mapping.
                store.save_ticker_resolution(
                    ResolvedTicker(
                        raw_symbol=t.raw_symbol,
                        resolved_ticker=t.resolved_ticker,
                        security_name=None,
                        status="resolved",
                        resolved_from="pattern",
                    )
                )
                new_resolved.append(t.resolved_ticker)
                continue

            try:
                res = market_data.resolve_ticker(t.raw_symbol, t.description)
            except Exception as e:
                logger.warning("resolve_ticker failed for %s: %s", t.raw_symbol, e)
                res = ResolvedTicker(raw_symbol=t.raw_symbol, resolved_ticker=None, status="unresolved")
            if res.resolved_ticker:
                new_resolved.append(res.resolved_ticker)
                t.resolved_ticker = res.resolved_ticker
            else:
                unresolved.append(t.raw_symbol)

        upsert = store.upsert_transactions(txs)

        # Propagate any new resolved tickers back onto stored rows
        for raw in seen_raws:
            cached = store.get_ticker_map().get(raw.upper())
            if cached and cached.resolved_ticker:
                store.update_resolved_ticker(raw, cached.resolved_ticker)

        # Record import metadata
        store.set_state("last_import_filename", file.filename or "upload")
        store.set_state("last_import_at", _now().isoformat())
        # Stamp the active profile so the switcher can show "last import" dates.
        try:
            active = profiles.get_active_profile()
            profiles.mark_profile_imported(active.id)
        except Exception as e:
            logger.warning("Could not mark profile imported: %s", e)

        return ImportResult(
            inserted=upsert.inserted,
            skipped_duplicates=upsert.skipped_duplicates,
            total_in_db=upsert.total_in_db,
            new_tickers_resolved=sorted(set(new_resolved)),
            unresolved_tickers=sorted(set(unresolved)),
            import_duration_ms=int((time.time() - started) * 1000),
            detected_broker=fmt.broker,
            detected_format=fmt.fmt,
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ---------- portfolio aggregation ----------

@app.get("/api/portfolio", response_model=PortfolioData)
def get_portfolio(account: str | None = None, period: str | None = None) -> PortfolioData:
    """Full PortfolioData snapshot for the dashboard, optionally scoped to one account and/or time period."""
    return portfolio.build_portfolio(account=account, period=period)


@app.get("/api/holdings", response_model=list[Holding])
def get_holdings(account: str | None = None, period: str | None = None) -> list[Holding]:
    """Just the per-holding list, scoped by account/period."""
    return portfolio.build_portfolio(account=account, period=period).holdings


@app.get("/api/capital-gains", response_model=CapitalGainsReport)
def get_capital_gains(
    account: str | None = None,
    period: str | None = None,
    year: int | None = None,
) -> CapitalGainsReport:
    """Realized capital gains/losses for the active profile (or a single account).

    When `year` is supplied, the realized_gains list and the total_*_cad
    aggregates are filtered to that calendar year. This matches the
    Tax Report PDF endpoint's `?year=` parameter (previously the table view
    couldn't be year-scoped from the API, only from the frontend).
    """
    report = portfolio.build_portfolio(account=account, period=period).capital_gains
    if year is None:
        return report
    filtered = [g for g in report.realized_gains if g.transaction_date.year == year]
    total_taxable_cad = sum((g.total_gain_cad or g.total_gain) for g in filtered if g.taxable)
    total_non_taxable_cad = sum((g.total_gain_cad or g.total_gain) for g in filtered if not g.taxable)
    return type(report)(
        realized_gains=filtered,
        total_taxable_gain=round(sum(g.total_gain for g in filtered if g.taxable), 2),
        total_non_taxable_gain=round(sum(g.total_gain for g in filtered if not g.taxable), 2),
        total_taxable_gain_cad=round(total_taxable_cad, 2),
        total_non_taxable_gain_cad=round(total_non_taxable_cad, 2),
        total_superficial_loss_denied=report.total_superficial_loss_denied,
        total_superficial_loss_denied_cad=report.total_superficial_loss_denied_cad,
    )


@app.get("/api/history/{ticker}", response_model=list[HistoricalDataPoint])
def get_history(ticker: str) -> list[HistoricalDataPoint]:
    """Weekly close-price history for a single ticker, fetching from yfinance when the local cache is stale."""
    # Ensure history is populated; cheap if already there.
    try:
        market_data.ensure_history(ticker)
    except Exception as e:
        logger.warning("ensure_history failed: %s", e)
    return portfolio.history_for(ticker)


@app.get("/api/history/benchmark/spy", response_model=list[BenchmarkPoint])
def get_benchmark(start: str | None = None) -> list[BenchmarkPoint]:
    """Normalized SPY history. `start` filters to dates >= the given YYYY-MM-DD;
    the first kept date is renormalized to 100 so the curve overlays cleanly."""
    return portfolio.benchmark_history(start=start, ticker="SPY")


@app.get("/api/portfolio/value-history", response_model=list[PortfolioValuePoint])
def get_portfolio_value_history(
    account: str | None = None, period: str | None = None
) -> list[PortfolioValuePoint]:
    """Weekly reconstruction of total portfolio value in CAD, optionally scoped
    to a single account and/or time period."""
    return portfolio.portfolio_value_history(account=account, period=period)


@app.get("/api/attribution", response_model=AttributionReport)
def get_attribution(
    account: str | None = None, period: str | None = None
) -> AttributionReport:
    """Per-holding contribution to total portfolio return over the period."""
    try:
        return portfolio.attribution_report(account=account, period=period)
    except Exception as e:
        logger.exception("get_attribution failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not compute attribution: {e}")


@app.get("/api/dividends", response_model=DividendReport)
def get_dividend_report(account: str | None = None, period: str | None = None) -> DividendReport:
    """Dividend income breakdown — monthly history, upcoming projections,
    yield-on-cost per holding, and period-scoped total."""
    return portfolio.dividend_report(account=account, period=period)


@app.get("/api/correlation", response_model=CorrelationMatrix)
def get_correlation(account: str | None = None, period: str | None = None) -> CorrelationMatrix:
    """Pearson correlation matrix of weekly returns. Empty matrix returned on insufficient history rather than a 500."""
    try:
        return portfolio.correlation_matrix(account=account, period=period)
    except Exception as e:
        # The correlation matrix is a "nice to have" panel — never 500 the dashboard
        # over insufficient overlapping price history or a pandas edge case.
        logger.exception("get_correlation failed: %s", e)
        return CorrelationMatrix(tickers=[], matrix=[])


@app.get("/api/stats", response_model=PortfolioStats)
def get_stats(account: str | None = None, period: str | None = None) -> PortfolioStats:
    """Annualised volatility / Sharpe / total return computed from weekly holdings returns."""
    return portfolio.build_portfolio(account=account, period=period).stats


# ---------- prices ----------

@app.post("/api/prices/refresh", response_model=PriceRefreshResult)
def refresh_prices() -> PriceRefreshResult:
    """Force-refresh live prices and FX rates, then evaluate price alerts. Updates last_price_refresh_at."""
    started = time.time()
    txs = store.get_all_transactions()
    tickers = sorted({t.resolved_ticker for t in txs if t.resolved_ticker})
    market_data.clear_memo()
    results = market_data.refresh_quotes(tickers)
    refreshed = sum(1 for q in results.values() if q.price is not None and not q.stale)
    failed = [t for t, q in results.items() if q.price is None]
    # Refresh FX too
    market_data.get_fx("USDCAD", max_age_minutes=0)
    market_data.get_fx("CADUSD", max_age_minutes=0)
    store.set_state("last_price_refresh_at", _now().isoformat())
    # Evaluate alerts using the freshly-fetched prices.
    try:
        alerts.evaluate_alerts()
    except Exception as e:
        logger.warning("evaluate_alerts after refresh failed: %s", e)
    return PriceRefreshResult(
        refreshed=refreshed,
        failed=failed,
        took_ms=int((time.time() - started) * 1000),
    )


@app.get("/api/prices/status", response_model=PriceStatus)
def prices_status() -> PriceStatus:
    """Age of the most recent price refresh, with a stale flag at >30 minutes."""
    raw = store.get_state("last_price_refresh_at")
    if not raw:
        return PriceStatus(last_refresh=None, age_minutes=None, stale=True)
    last = datetime.fromisoformat(raw)
    age = int((_now() - last).total_seconds() / 60)
    return PriceStatus(last_refresh=last, age_minutes=age, stale=age > 30)


# ---------- unresolved tickers ----------

@app.get("/api/tickers/unresolved", response_model=list[UnresolvedTicker])
def unresolved_tickers() -> list[UnresolvedTicker]:
    """Raw symbols the parser couldn't map to a Yahoo Finance ticker; surfaced for manual mapping in the UI."""
    return portfolio.build_portfolio().unresolved_tickers


class ResolveRequest(BaseModel):
    raw_symbol: str
    resolved_ticker: str


@app.post("/api/tickers/resolve", response_model=ResolvedTicker)
def resolve_manual(req: ResolveRequest) -> ResolvedTicker:
    """User-supplied mapping for a previously-unresolved symbol. Updates every existing transaction row."""
    res = ResolvedTicker(
        raw_symbol=req.raw_symbol,
        resolved_ticker=req.resolved_ticker,
        status="resolved",
        resolved_from="manual",
    )
    store.save_ticker_resolution(res)
    store.update_resolved_ticker(req.raw_symbol, req.resolved_ticker)
    return res


# ---------- export ----------

@app.get("/api/export/xlsx")
def export_xlsx(period: str | None = None) -> StreamingResponse:
    """Stream the formatted 5-sheet xlsx export. With ?period= set, sheets reflect that window."""
    data = excel_export.build_xlsx_bytes(period=period)
    filename = excel_export.suggested_filename(period=period)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/annual-report")
def export_annual_report(year: int | None = None) -> StreamingResponse:
    """Year-in-review PDF — performance summary, holdings, transactions, dividends."""
    try:
        chosen = year if year is not None else date.today().year - 1
        if chosen < 2000 or chosen > date.today().year:
            raise HTTPException(status_code=400, detail=f"Invalid year: {chosen}")
        pdf = annual_report.build_annual_report_pdf(chosen)
        filename = annual_report.suggested_filename(chosen)
        return StreamingResponse(
            iter([pdf]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_annual_report failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not build report: {e}")


@app.get("/api/export/tax-report")
def export_tax_report(year: int | None = None) -> StreamingResponse:
    """CRA-style PDF for the selected tax year. Defaults to previous calendar year."""
    try:
        chosen = year if year is not None else date.today().year - 1
        if chosen < 2000 or chosen > date.today().year:
            raise HTTPException(status_code=400, detail=f"Invalid year: {chosen}")
        pdf_bytes = tax_report.build_tax_report_pdf(chosen)
        filename = tax_report.suggested_filename(chosen)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_tax_report failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not build report: {e}")


# ---------- settings ----------

@app.get("/api/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    """All persisted user settings for the active profile."""
    return store.get_settings()


@app.patch("/api/settings", response_model=AppSettings)
def patch_settings(req: AppSettings) -> AppSettings:
    """Update one or more settings; unspecified fields are unchanged."""
    store.save_settings(req)
    return store.get_settings()


# ---------- price alerts ----------

@app.get("/api/alerts", response_model=list[PriceAlert])
def get_alerts(include_dismissed: bool = False) -> list[PriceAlert]:
    """Every undismissed alert in the active profile, with the current cached price filled in for each."""
    try:
        return alerts.list_alerts(include_dismissed=include_dismissed)
    except Exception as e:
        logger.exception("get_alerts failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not list alerts: {e}")


@app.post("/api/alerts", response_model=PriceAlert)
def create_alert(req: PriceAlertCreate) -> PriceAlert:
    """Persist a new buy-below or sell-above price alert."""
    try:
        return alerts.create_alert(req)
    except Exception as e:
        logger.exception("create_alert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not create alert: {e}")


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int) -> dict:
    """Permanently remove an alert by id."""
    try:
        ok = alerts.delete_alert(alert_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("delete_alert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not delete alert: {e}")


@app.post("/api/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int) -> dict:
    """Acknowledge a triggered alert without deleting the row."""
    try:
        ok = alerts.dismiss_alert(alert_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("dismiss_alert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not dismiss alert: {e}")


@app.get("/api/alerts/triggered", response_model=list[PriceAlert])
def get_triggered_alerts() -> list[PriceAlert]:
    """Alerts that have fired but not been dismissed — drives the bell badge."""
    try:
        return [a for a in alerts.list_alerts() if a.triggered]
    except Exception as e:
        logger.exception("get_triggered_alerts failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not list alerts: {e}")


# ---------- what-if simulator ----------

@app.post("/api/simulate/buy", response_model=SimulationResult)
def post_simulate_buy(req: SimBuyRequest) -> SimulationResult:
    """What-If: project the impact of buying N shares of a ticker today. Read-only; nothing written to the DB."""
    try:
        return simulator.simulate_buy(req.ticker, req.shares, req.account_type)
    except Exception as e:
        logger.exception("simulate_buy failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Buy simulation failed: {e}")


@app.post("/api/simulate/sell", response_model=SimulationResult)
def post_simulate_sell(req: SimSellRequest) -> SimulationResult:
    """What-If: capital gain/loss + tax estimate for selling N shares today."""
    try:
        return simulator.simulate_sell(req.ticker, req.shares, req.account_type)
    except Exception as e:
        logger.exception("simulate_sell failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sell simulation failed: {e}")


@app.post("/api/simulate/lump-sum", response_model=SimulationResult)
def post_simulate_lump_sum(req: SimLumpSumRequest) -> SimulationResult:
    """What-If: what would `amount_cad` invested on `invest_date` be worth now?"""
    try:
        return simulator.simulate_lump_sum(req.ticker, req.amount_cad, req.invest_date)
    except Exception as e:
        logger.exception("simulate_lump_sum failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Lump-sum simulation failed: {e}")


# ---------- rebalancing advisor ----------

@app.post("/api/rebalance", response_model=RebalanceResponse)
def post_rebalance(req: RebalanceRequest) -> RebalanceResponse:
    """Compute buy/sell instructions to bring the portfolio to the given target allocation."""
    try:
        return rebalance.compute_rebalance(req)
    except Exception as e:
        logger.exception("rebalance failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Rebalance failed: {e}")


# ---------- TFSA contribution room ----------

@app.get("/api/tfsa/room", response_model=tfsa.TfsaRoomReport)
def get_tfsa_room(
    birth_year: int | None = None, resident_since: int | None = None
) -> tfsa.TfsaRoomReport:
    """Calculate TFSA contribution room. Reads birth_year/resident_since from
    settings if not supplied via query params."""
    try:
        settings = store.get_settings()
        by = birth_year if birth_year is not None else settings.tfsa_birth_year
        rs = resident_since if resident_since is not None else settings.tfsa_resident_since
        return tfsa.compute_tfsa_room(birth_year=by, resident_since=rs)
    except Exception as e:
        logger.exception("get_tfsa_room failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not compute TFSA room: {e}")


# ---------- data management (Settings → Data section) ----------

@app.post("/api/data/clear")
def clear_active_profile_data() -> dict:
    """Wipe ALL transactions/holdings/etc. in the active profile's database.

    Settings (preferred_currency, theme, etc.) are preserved. The profile itself
    is preserved — use DELETE /api/profiles/{id} to remove a profile.
    """
    try:
        # Save settings first so wipe_all_data doesn't clear them.
        kept = store.get_settings()
        store.wipe_all_data()
        store.save_settings(kept)
        return {"success": True, "detail": "Active profile data cleared."}
    except Exception as e:
        logger.exception("clear_active_profile_data failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not clear data: {e}")


@app.get("/api/data/export-json")
def export_data_as_json() -> StreamingResponse:
    """Stream a JSON backup of the active profile's transactions + ticker map.

    Intentionally narrow — only data the user created. Caches (price history,
    exchange rates, profile-level app_state) regenerate themselves.
    """
    import json

    try:
        txs = [t.model_dump(mode="json") for t in store.get_all_transactions()]
        ticker_map = {k: v.model_dump(mode="json") for k, v in store.get_ticker_map().items()}
        payload = {
            "exported_at": _now().isoformat(),
            "active_profile": profiles.get_active_profile().model_dump(mode="json"),
            "transactions": txs,
            "ticker_map": ticker_map,
        }
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        filename = f"portfolio_backup_{date.today().isoformat()}.json"
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("export_data_as_json failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not export data: {e}")


# ---------- profiles ----------

class CreateProfileRequest(BaseModel):
    name: str
    color: str = profiles.DEFAULT_PROFILE_COLOR


class RenameProfileRequest(BaseModel):
    name: str | None = None
    color: str | None = None


class ProfilesListResponse(BaseModel):
    active_profile_id: str
    profiles: list[profiles.Profile]


@app.get("/api/profiles", response_model=ProfilesListResponse)
def list_profiles() -> ProfilesListResponse:
    """All profiles known to the app, with the currently-active one's id."""
    state = profiles.load_profiles()
    return ProfilesListResponse(
        active_profile_id=state.active_profile_id,
        profiles=state.profiles,
    )


@app.get("/api/profiles/active", response_model=profiles.Profile)
def get_active_profile() -> profiles.Profile:
    """The profile whose database is currently bound to the engine."""
    return profiles.get_active_profile()


@app.post("/api/profiles", response_model=profiles.Profile)
def create_profile(req: CreateProfileRequest) -> profiles.Profile:
    """Create a new isolated portfolio with its own database file."""
    return profiles.create_profile(name=req.name, color=req.color)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict:
    """Remove a profile and its DB. Refuses to delete the last remaining profile."""
    state_before = profiles.load_profiles()
    was_active = state_before.active_profile_id == profile_id
    result = profiles.delete_profile(profile_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("detail", "Cannot delete"))
    # If we deleted the active profile, swap the engine to the new active one.
    if was_active and result.get("active_profile_id"):
        new_active_id = result["active_profile_id"]
        db.set_db_path(profiles.profile_db_path(new_active_id))
        db.get_engine()  # ensure tables exist on the new DB
    return result


@app.post("/api/profiles/{profile_id}/activate", response_model=profiles.Profile)
def activate_profile(profile_id: str) -> profiles.Profile:
    """Hot-swap the engine to a different profile's database — no app restart needed."""
    try:
        profile = profiles.activate_profile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
    # Hot-swap: dispose the old engine and rebind to the new profile's DB.
    db.set_db_path(profiles.profile_db_path(profile.id))
    db.get_engine()  # auto-creates tables in the new DB on first call
    # Drop process-local price memo so each profile starts clean
    market_data.clear_memo()
    return profile


@app.patch("/api/profiles/{profile_id}", response_model=profiles.Profile)
def patch_profile(profile_id: str, req: RenameProfileRequest) -> profiles.Profile:
    """Rename a profile or change its accent color."""
    p = profiles.rename_profile(profile_id, req.name or "", req.color)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
    return p


# ---------- graceful shutdown ----------

@app.post("/api/shutdown")
async def shutdown() -> dict:
    """Called by the Electron main process before app quit so the backend can
    checkpoint the SQLite WAL and exit cleanly.

    Without this hook, the previous behavior on Windows was a raw TerminateProcess
    from Electron, leaving multi-MB `.db-wal` files behind. The fix is two-step:
    Electron POSTs here first, we checkpoint WAL synchronously, then we schedule
    SIGTERM on this process from a daemon thread so the response can complete
    before the loop tears down.
    """
    import os
    import signal
    import threading

    try:
        stats = db.checkpoint_wal()
        logger.info("Shutdown checkpoint: %s", stats)
    except Exception as e:
        logger.warning("checkpoint_wal failed during shutdown: %s", e)
        stats = {"error": str(e)}

    def _terminate() -> None:
        # Short delay so the HTTP response flushes to the Electron caller.
        import time
        time.sleep(0.5)
        try:
            if hasattr(signal, "CTRL_BREAK_EVENT"):
                os.kill(os.getpid(), signal.CTRL_BREAK_EVENT)
            else:
                os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)

    threading.Thread(target=_terminate, daemon=True).start()
    return {"status": "shutting_down", "checkpoint": stats}


# ---------- entrypoint ----------

def main() -> None:
    """Console-script / PyInstaller entry point.

    NOTE: pass the `app` object directly rather than the "backend.main:app"
    import string. Inside a PyInstaller --onefile bundle, the module is loaded
    by the bootloader and is NOT re-importable by name (no sys.path entry for
    backend/). The string form would raise: 'Error loading ASGI app. Could not
    import module "backend.main".' The object form sidesteps the import.

    Port resolution: `PORTFOLIO_PORT` env var takes precedence so the Electron
    main process can pre-allocate a free port (avoiding the `[Errno 10048]
    address already in use` crash on a second-launch attempt).
    """
    import os
    port_str = os.environ.get("PORTFOLIO_PORT", "7842")
    try:
        port = int(port_str)
    except ValueError:
        port = 7842
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
