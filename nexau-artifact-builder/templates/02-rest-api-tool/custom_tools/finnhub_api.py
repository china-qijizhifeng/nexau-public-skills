"""Finnhub API custom tools for NexAU Agent.

This module provides 18 tool functions that wrap the Finnhub REST API.
Each function accepts typed parameters matching its tool input_schema,
plus an ``api_token`` that is injected at runtime via ``extra_kwargs``
from the environment variable ``X_FINNHUB_SECRET``.

All functions return a JSON-formatted string suitable for LLM consumption.

Runtime note: custom_tools run **inside the agent-runtime process**, not inside
the sandbox. The agent-runtime image already ships httpx / requests, so using
them here is fine; stdlib ``urllib`` is used only to keep this file dependency-free
and portable (it also runs unchanged when you drive NexAU locally).
Only the 5 tools registered in agent.yaml are reachable by the model — the other
13 functions stay here as reference for the endpoints you may want to add back.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_BASE_URL = "https://finnhub.io/api/v1"


def _finnhub_get(path: str, params: dict, api_token: str) -> dict:
    """Send a GET request to the Finnhub API and return parsed JSON.

    Parameters
    ----------
    path:
        API path **without** the base URL, e.g. ``/quote``.
    params:
        Query parameters (empty-string values are filtered out).
    api_token:
        Finnhub API token – added as ``token`` query param.

    Returns
    -------
    dict
        Parsed JSON response, or ``{"error": "..."}`` on failure.
    """
    # Inject token & drop empty values
    filtered: dict[str, str] = {"token": api_token}
    for k, v in params.items():
        if v != "" and v is not None:
            filtered[k] = str(v)

    url = f"{_BASE_URL}{path}?{urllib.parse.urlencode(filtered)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.reason}"}
    except urllib.error.URLError as exc:
        return {"error": f"URL error: {exc.reason}"}
    except TimeoutError:
        return {"error": "Request timed out (10 s)"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _dumps(obj: object) -> str:
    """Serialize *obj* to a compact, LLM-friendly JSON string."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. Quote
# ---------------------------------------------------------------------------

def finnhub_quote(symbol: str, api_token: str = "") -> str:
    """Get real-time quote for a stock symbol.

    Returns current price, change, percent change, high, low, open,
    previous close, and Unix timestamp.

    GET /api/v1/quote?symbol={symbol}
    """
    data = _finnhub_get("/quote", {"symbol": symbol}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 2. Symbol Lookup
# ---------------------------------------------------------------------------

def finnhub_symbol_lookup(query: str, exchange: str = "", api_token: str = "") -> str:
    """Search for a stock symbol by name or keyword.

    Returns up to 10 matching symbols with description, display symbol,
    and type.

    GET /api/v1/search?q={query}&exchange={exchange}
    """
    data = _finnhub_get("/search", {"q": query, "exchange": exchange}, api_token)
    if "error" in data:
        return _dumps(data)

    results = data.get("result", [])[:10]
    return _dumps({
        "count": data.get("count", len(results)),
        "result": results,
        "note": "Showing first 10 results." if data.get("count", 0) > 10 else None,
    })


# ---------------------------------------------------------------------------
# 3. Company Profile
# ---------------------------------------------------------------------------

def finnhub_company_profile(symbol: str, api_token: str = "") -> str:
    """Get company profile information.

    Returns company name, ticker, country, currency, exchange, IPO date,
    market capitalisation, share outstanding, industry, logo, and more.

    GET /api/v1/stock/profile2?symbol={symbol}
    """
    data = _finnhub_get("/stock/profile2", {"symbol": symbol}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 4. Peers
# ---------------------------------------------------------------------------

def finnhub_peers(symbol: str, api_token: str = "") -> str:
    """Get a list of peer company symbols for a given stock.

    GET /api/v1/stock/peers?symbol={symbol}
    """
    data = _finnhub_get("/stock/peers", {"symbol": symbol}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 5. Basic Financials
# ---------------------------------------------------------------------------

def finnhub_basic_financials(symbol: str, api_token: str = "") -> str:
    """Get key financial metrics for a stock.

    Includes P/E, P/B, dividend yield, 52-week high/low, market cap, and
    many more.  Only the ``metric`` dict and a summary of ``series`` keys
    are returned to keep the payload LLM-friendly.

    GET /api/v1/stock/metric?symbol={symbol}&metric=all
    """
    data = _finnhub_get("/stock/metric", {"symbol": symbol, "metric": "all"}, api_token)
    if "error" in data:
        return _dumps(data)

    result: dict = {
        "symbol": data.get("symbol", symbol),
        "metric": data.get("metric", {}),
    }

    # Summarise the (potentially huge) series block
    series = data.get("series", {})
    if series:
        annual = series.get("annual", {})
        quarterly = series.get("quarterly", {})
        result["series_summary"] = {
            "annual_keys": list(annual.keys()) if isinstance(annual, dict) else [],
            "quarterly_keys": list(quarterly.keys()) if isinstance(quarterly, dict) else [],
            "note": "Series data available. Request specific series if needed.",
        }

    return _dumps(result)


# ---------------------------------------------------------------------------
# 6. Earnings Surprises
# ---------------------------------------------------------------------------

def finnhub_earnings_surprises(symbol: str, limit: int = 4, api_token: str = "") -> str:
    """Get earnings surprises (actual vs estimate EPS).

    GET /api/v1/stock/earnings?symbol={symbol}&limit={limit}
    """
    data = _finnhub_get("/stock/earnings", {"symbol": symbol, "limit": limit}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 7. Financials Reported
# ---------------------------------------------------------------------------

def finnhub_financials_reported(symbol: str, freq: str = "annual", api_token: str = "") -> str:
    """Get financials as reported to the SEC.

    Because the raw data is very large, only the first 2 reports are
    returned in summary form: year, quarter, form, filedDate, and the
    top-level keys of the ``report`` object (bs, ic, cf, etc.).

    GET /api/v1/stock/financials-reported?symbol={symbol}&freq={freq}
    """
    data = _finnhub_get(
        "/stock/financials-reported",
        {"symbol": symbol, "freq": freq},
        api_token,
    )
    if "error" in data:
        return _dumps(data)

    raw_reports = data.get("data", [])[:2]
    summaries = []
    for r in raw_reports:
        report_obj = r.get("report", {})
        summaries.append({
            "year": r.get("year"),
            "quarter": r.get("quarter"),
            "form": r.get("form"),
            "filedDate": r.get("filedDate"),
            "startDate": r.get("startDate"),
            "endDate": r.get("endDate"),
            "report_sections": list(report_obj.keys()) if isinstance(report_obj, dict) else [],
        })

    return _dumps({
        "symbol": data.get("symbol", symbol),
        "total_reports": len(data.get("data", [])),
        "showing": len(summaries),
        "reports": summaries,
        "note": (
            "Only the first 2 reports are shown in summary form. "
            "Each report contains detailed line items under keys like bs (balance sheet), "
            "ic (income statement), cf (cash flow). Ask for a specific report or section "
            "if you need full details."
        ),
    })


# ---------------------------------------------------------------------------
# 8. ESG Scores
# ---------------------------------------------------------------------------

def finnhub_esg(symbol: str, api_token: str = "") -> str:
    """Get ESG (Environmental, Social, Governance) scores for a company.

    GET /api/v1/stock/esg?symbol={symbol}
    """
    data = _finnhub_get("/stock/esg", {"symbol": symbol}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 9. Recommendation Trends
# ---------------------------------------------------------------------------

def finnhub_recommendation(symbol: str, api_token: str = "") -> str:
    """Get analyst recommendation trends.

    Returns monthly breakdown of buy, hold, sell, strongBuy, and
    strongSell counts.

    GET /api/v1/stock/recommendation?symbol={symbol}
    """
    data = _finnhub_get("/stock/recommendation", {"symbol": symbol}, api_token)
    return _dumps(data)


# ---------------------------------------------------------------------------
# 10. Insider Transactions
# ---------------------------------------------------------------------------

def finnhub_insider_transactions(
    symbol: str,
    from_date: str = "",
    to_date: str = "",
    api_token: str = "",
) -> str:
    """Get insider transactions for a company.

    Returns the most recent 20 transactions to keep output concise.

    GET /api/v1/stock/insider-transactions?symbol={symbol}&from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/stock/insider-transactions",
        {"symbol": symbol, "from": from_date, "to": to_date},
        api_token,
    )
    if "error" in data:
        return _dumps(data)

    all_txns = data.get("data", [])
    limited = all_txns[:20]
    result: dict = {
        "symbol": data.get("symbol", symbol),
        "total_transactions": len(all_txns),
        "showing": len(limited),
        "data": limited,
    }
    if len(all_txns) > 20:
        result["note"] = "Only the 20 most recent transactions are shown."
    return _dumps(result)


# ---------------------------------------------------------------------------
# 11. Insider Sentiment
# ---------------------------------------------------------------------------

def finnhub_insider_sentiment(
    symbol: str,
    from_date: str,
    to_date: str,
    api_token: str = "",
) -> str:
    """Get monthly insider sentiment (MSPR and change).

    GET /api/v1/stock/insider-sentiment?symbol={symbol}&from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/stock/insider-sentiment",
        {"symbol": symbol, "from": from_date, "to": to_date},
        api_token,
    )
    return _dumps(data)


# ---------------------------------------------------------------------------
# 12. Company News
# ---------------------------------------------------------------------------

def finnhub_company_news(
    symbol: str,
    from_date: str,
    to_date: str,
    api_token: str = "",
) -> str:
    """Get company news articles for a date range.

    Returns the first 10 articles with headline, source, datetime,
    summary (truncated to 200 chars), and URL.

    GET /api/v1/company-news?symbol={symbol}&from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/company-news",
        {"symbol": symbol, "from": from_date, "to": to_date},
        api_token,
    )
    if isinstance(data, dict) and "error" in data:
        return _dumps(data)

    articles = []
    for item in (data if isinstance(data, list) else [])[:10]:
        summary = item.get("summary", "") or ""
        articles.append({
            "headline": item.get("headline"),
            "source": item.get("source"),
            "datetime": item.get("datetime"),
            "summary": summary[:200] + ("…" if len(summary) > 200 else ""),
            "url": item.get("url"),
        })

    return _dumps({
        "total_available": len(data) if isinstance(data, list) else 0,
        "showing": len(articles),
        "articles": articles,
    })


# ---------------------------------------------------------------------------
# 13. Market News
# ---------------------------------------------------------------------------

def finnhub_market_news(category: str = "general", api_token: str = "") -> str:
    """Get general market news.

    Category can be: general, forex, crypto, merger.
    Returns the first 15 articles.

    GET /api/v1/news?category={category}
    """
    data = _finnhub_get("/news", {"category": category}, api_token)
    if isinstance(data, dict) and "error" in data:
        return _dumps(data)

    articles = []
    for item in (data if isinstance(data, list) else [])[:15]:
        summary = item.get("summary", "") or ""
        articles.append({
            "headline": item.get("headline"),
            "source": item.get("source"),
            "datetime": item.get("datetime"),
            "summary": summary[:200] + ("…" if len(summary) > 200 else ""),
            "url": item.get("url"),
        })

    return _dumps({
        "category": category,
        "showing": len(articles),
        "articles": articles,
    })


# ---------------------------------------------------------------------------
# 14. SEC Filings
# ---------------------------------------------------------------------------

def finnhub_sec_filings(
    symbol: str = "",
    form: str = "",
    from_date: str = "",
    to_date: str = "",
    api_token: str = "",
) -> str:
    """Get SEC filings for a company.

    Returns the first 20 filings.

    GET /api/v1/stock/filings?symbol={symbol}&form={form}&from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/stock/filings",
        {"symbol": symbol, "form": form, "from": from_date, "to": to_date},
        api_token,
    )
    if isinstance(data, dict) and "error" in data:
        return _dumps(data)

    filings = (data if isinstance(data, list) else [])[:20]
    result: dict = {
        "total_available": len(data) if isinstance(data, list) else 0,
        "showing": len(filings),
        "filings": filings,
    }
    if isinstance(data, list) and len(data) > 20:
        result["note"] = "Only the first 20 filings are shown."
    return _dumps(result)


# ---------------------------------------------------------------------------
# 15. Lobbying
# ---------------------------------------------------------------------------

def finnhub_lobbying(
    symbol: str,
    from_date: str,
    to_date: str,
    api_token: str = "",
) -> str:
    """Get Senate lobbying data for a company.

    GET /api/v1/stock/lobbying?symbol={symbol}&from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/stock/lobbying",
        {"symbol": symbol, "from": from_date, "to": to_date},
        api_token,
    )
    return _dumps(data)


# ---------------------------------------------------------------------------
# 16. Earnings Calendar
# ---------------------------------------------------------------------------

def finnhub_earnings_calendar(
    from_date: str = "",
    to_date: str = "",
    symbol: str = "",
    api_token: str = "",
) -> str:
    """Get upcoming earnings dates.

    GET /api/v1/calendar/earnings?from={from_date}&to={to_date}&symbol={symbol}
    """
    data = _finnhub_get(
        "/calendar/earnings",
        {"from": from_date, "to": to_date, "symbol": symbol},
        api_token,
    )
    return _dumps(data)


# ---------------------------------------------------------------------------
# 17. IPO Calendar
# ---------------------------------------------------------------------------

def finnhub_ipo_calendar(
    from_date: str,
    to_date: str,
    api_token: str = "",
) -> str:
    """Get IPO calendar for a date range.

    GET /api/v1/calendar/ipo?from={from_date}&to={to_date}
    """
    data = _finnhub_get(
        "/calendar/ipo",
        {"from": from_date, "to": to_date},
        api_token,
    )
    return _dumps(data)


# ---------------------------------------------------------------------------
# 18. Market Status
# ---------------------------------------------------------------------------

def finnhub_market_status(exchange: str, api_token: str = "") -> str:
    """Check whether a stock exchange is currently open or closed.

    Returns market status and session information.

    GET /api/v1/stock/market-status?exchange={exchange}
    """
    data = _finnhub_get(
        "/stock/market-status",
        {"exchange": exchange},
        api_token,
    )
    return _dumps(data)
