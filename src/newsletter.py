#!/usr/bin/env python3
"""
Weekly Market & Crypto Newsletter sent to Discord via Webhook.
100% free: Yahoo Finance (yfinance) + Google News RSS + optional Gemini API summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

SF_TZ = ZoneInfo("America/Los_Angeles")
PARIS_TZ = ZoneInfo("Europe/Paris")

INDICES = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^FCHI", "CAC 40"),
]

US_TECH_GIANTS = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
    ("META", "Meta"),
    ("TSLA", "Tesla"),
    ("AVGO", "Broadcom"),
]

CAC40_TICKERS = {
    "MC.PA": "LVMH",
    "RMS.PA": "Hermès",
    "OR.PA": "L'Oréal",
    "TTE.PA": "TotalEnergies",
    "SAN.PA": "Sanofi",
    "AIR.PA": "Airbus",
    "SU.PA": "Schneider Elec.",
    "AI.PA": "Air Liquide",
    "BNP.PA": "BNP Paribas",
    "SAF.PA": "Safran",
    "EL.PA": "EssilorLuxottica",
    "CS.PA": "AXA",
    "DG.PA": "Vinci",
    "KER.PA": "Kering",
    "DSY.PA": "Dassault Syst.",
    "STMPA.PA": "STMicro",
    "CAP.PA": "Capgemini",
    "ORA.PA": "Orange",
    "SGO.PA": "Saint-Gobain",
    "RI.PA": "Pernod Ricard",
    "HO.PA": "Thales",
    "LR.PA": "Legrand",
    "ENGI.PA": "Engie",
    "VIE.PA": "Veolia",
    "ACA.PA": "Crédit Agricole",
    "GLE.PA": "Société Générale",
    "ML.PA": "Michelin",
    "CA.PA": "Carrefour",
    "BN.PA": "Danone",
    "PUB.PA": "Publicis",
    "EN.PA": "Bouygues",
    "ERF.PA": "Eurofins",
    "MT.AS": "ArcelorMittal",
    "RNO.PA": "Renault",
    "STLAP.PA": "Stellantis",
    "AC.PA": "Accor",
    "BVI.PA": "Bureau Veritas",
    "URW.PA": "Unibail",
    "TEP.PA": "Teleperformance",
    "EDEN.PA": "Edenred",
}

CRYPTOS = [
    ("BTC-USD", "Bitcoin (BTC)"),
    ("ETH-USD", "Ethereum (ETH)"),
    ("SOL-USD", "Solana (SOL)"),
]

HEADLINE_FEEDS = {
    "Nasdaq / Tech": [
        "https://news.google.com/rss/search?q=Nasdaq+OR+technology+stocks+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://www.cnbc.com/id/19854910/device/rss/rss.html",
        "https://finance.yahoo.com/news/rssindex",
    ],
    "US Macro": [
        "https://news.google.com/rss/search?q=Federal+Reserve+OR+inflation+OR+Wall+Street+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ],
    "CAC 40": [
        "https://news.google.com/rss/search?q=site:investir.lesechos.fr+CAC+40+when:2d&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=CAC+40+bourse+when:2d&hl=fr&gl=FR&ceid=FR:fr",
        "https://www.lefigaro.fr/rss/figaro_economie.xml",
    ],
    "Crypto": [
        "https://news.google.com/rss/search?q=Bitcoin+OR+Ethereum+cryptocurrency+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ],
}

HARDCODED_FALLBACKS = {
    "Nasdaq / Tech": {
        "title": "US Tech & Nasdaq Market Coverage",
        "link": "https://www.google.com/finance/quote/.IXIC:INDEXNASDAQ",
    },
    "US Macro": {
        "title": "US Economy, Fed & Wall Street Markets",
        "link": "https://www.google.com/finance/quote/.INX:INDEXSP",
    },
    "CAC 40": {
        "title": "Bourse de Paris et Actualités CAC 40 - Investir Les Echos",
        "link": "https://investir.lesechos.fr/cours/indices/cac-40-FR0003500008-PX1",
    },
    "Crypto": {
        "title": "Cryptocurrency & Bitcoin Market News",
        "link": "https://www.coindesk.com/price/bitcoin/",
    },
}


@dataclass
class QuotePerf:
    symbol: str
    name: str
    price: float
    day_pct: float
    week_pct: float
    currency: str = "$"
    available: bool = True


def fmt_pct(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    emoji = "🟢" if pct > 0.05 else ("🔴" if pct < -0.05 else "⚪")
    return f"{emoji} {sign}{pct:.2f}%"


def fmt_pct_compact(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def fmt_price(price: float, currency: str) -> str:
    if currency == "pts":
        return f"{price:,.0f} pts"
    if price >= 1000:
        return f"{currency}{price:,.0f}"
    if price >= 10:
        return f"{currency}{price:,.2f}"
    return f"{currency}{price:,.3f}"


def fetch_quotes(
    symbols: list[tuple[str, str]],
    *,
    is_crypto: bool = False,
    currency: str = "$",
) -> list[QuotePerf]:
    tickers = []
    name_map = {}
    for item in symbols:
        sym = item[0]
        name = item[1]
        tickers.append(sym)
        name_map[sym] = name

    use_threads = True
    if len(tickers) <= 5:
        use_threads = False

    raw = yf.download(
        tickers=tickers,
        period="1mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=use_threads,
    )

    results = []
    single_ticker = False
    if len(tickers) == 1:
        single_ticker = True

    now_sf = datetime.now(SF_TZ).date()
    weekday_number = now_sf.weekday()
    monday_this_week = now_sf - timedelta(days=weekday_number)

    if not raw.empty:
        for sym in tickers:
            try:
                df = raw
                if not single_ticker:
                    df = raw[sym]
                closes = df["Close"].dropna()
                if len(closes) < 2:
                    continue

                last_price = float(closes.iloc[-1])
                prev_day_price = float(closes.iloc[-2])
                day_ratio = last_price / prev_day_price
                day_pct = (day_ratio - 1.0) * 100.0

                if is_crypto:
                    idx = -8
                    if len(closes) < 8:
                        idx = 0
                    week_base = float(closes.iloc[idx])
                else:
                    prior_week = closes[closes.index.date < monday_this_week]
                    if not prior_week.empty:
                        week_base = float(prior_week.iloc[-1])
                    else:
                        idx = -6
                        if len(closes) < 6:
                            idx = 0
                        week_base = float(closes.iloc[idx])

                week_ratio = last_price / week_base
                week_pct = (week_ratio - 1.0) * 100.0
                quote_name = name_map[sym]
                perf = QuotePerf(
                    symbol=sym,
                    name=quote_name,
                    price=last_price,
                    day_pct=day_pct,
                    week_pct=week_pct,
                    currency=currency,
                    available=True,
                )
                results.append(perf)
            except Exception:
                continue

    found_symbols = set()
    for item in results:
        found_symbols.add(item.symbol)

    for item in symbols:
        sym = item[0]
        name = item[1]
        if sym not in found_symbols:
            try:
                single_raw = yf.download(
                    tickers=[sym],
                    period="1mo",
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
                closes = single_raw["Close"].dropna()
                if len(closes) >= 2:
                    last_price = float(closes.iloc[-1])
                    prev_day_price = float(closes.iloc[-2])
                    day_ratio = last_price / prev_day_price
                    day_pct = (day_ratio - 1.0) * 100.0

                    if is_crypto:
                        idx = -8
                        if len(closes) < 8:
                            idx = 0
                        week_base = float(closes.iloc[idx])
                    else:
                        prior_week = closes[closes.index.date < monday_this_week]
                        if not prior_week.empty:
                            week_base = float(prior_week.iloc[-1])
                        else:
                            idx = -6
                            if len(closes) < 6:
                                idx = 0
                            week_base = float(closes.iloc[idx])

                    week_ratio = last_price / week_base
                    week_pct = (week_ratio - 1.0) * 100.0
                    perf = QuotePerf(
                        symbol=sym,
                        name=name,
                        price=last_price,
                        day_pct=day_pct,
                        week_pct=week_pct,
                        currency=currency,
                        available=True,
                    )
                    results.append(perf)
                    found_symbols.add(sym)
            except Exception:
                continue

    for item in symbols:
        sym = item[0]
        name = item[1]
        if sym not in found_symbols:
            placeholder = QuotePerf(
                symbol=sym,
                name=name,
                price=0.0,
                day_pct=0.0,
                week_pct=0.0,
                currency=currency,
                available=False,
            )
            results.append(placeholder)

    order_map = {}
    for idx, item in enumerate(symbols):
        sym = item[0]
        order_map[sym] = idx

    results.sort(key=lambda q: order_map.get(q.symbol, 999))
    return results


def format_index_line(q: QuotePerf, is_friday: bool) -> str:
    if not q.available:
        return f"**{q.name}** : *Data temporarily unavailable*"
    price_str = fmt_price(q.price, q.currency)
    if is_friday:
        week_str = fmt_pct(q.week_pct)
        day_str = fmt_pct_compact(q.day_pct)
        return f"**{q.name}** : `{price_str}` · Weekly {week_str} *(1D {day_str})*"
    else:
        day_str = fmt_pct(q.day_pct)
        week_str = fmt_pct_compact(q.week_pct)
        return f"**{q.name}** : `{price_str}` · 1D {day_str} *(WTD {week_str})*"


def format_tech_line(q: QuotePerf, is_friday: bool) -> str:
    if not q.available:
        return f"**{q.name}** (`{q.symbol}`) : *Data temporarily unavailable*"
    price_str = fmt_price(q.price, "$")
    if is_friday:
        week_str = fmt_pct(q.week_pct)
        day_str = fmt_pct_compact(q.day_pct)
        return f"**{q.name}** (`{q.symbol}`) : `{price_str}` · Weekly {week_str} *(1D {day_str})*"
    else:
        day_str = fmt_pct(q.day_pct)
        week_str = fmt_pct_compact(q.week_pct)
        return f"**{q.name}** (`{q.symbol}`) : `{price_str}` · 1D {day_str} *(WTD {week_str})*"


def format_crypto_line(q: QuotePerf, is_friday: bool) -> str:
    if not q.available:
        return f"**{q.name}** : *Data temporarily unavailable*"
    price_str = fmt_price(q.price, "$")
    if is_friday:
        week_str = fmt_pct(q.week_pct)
        day_str = fmt_pct_compact(q.day_pct)
        return f"**{q.name}** : `{price_str}` · 7D {week_str} *(24h {day_str})*"
    else:
        day_str = fmt_pct(q.day_pct)
        week_str = fmt_pct_compact(q.week_pct)
        return f"**{q.name}** : `{price_str}` · 24h {day_str} *(7D {week_str})*"


def format_cac_section(
    cac_top3: list[QuotePerf],
    cac_flop3: list[QuotePerf],
    is_friday: bool,
) -> str:
    if not cac_top3 and not cac_flop3:
        return "*Data temporarily unavailable.*"

    lines = []
    if is_friday:
        lines.append("**Top 3 Gainers (Weekly)**")
        for q in cac_top3:
            price_str = fmt_price(q.price, "€")
            pct_str = fmt_pct(q.week_pct)
            lines.append(f"• **{q.name}** (`{price_str}`) : {pct_str}")
        if cac_flop3:
            lines.append("\n**Top 3 Losers (Weekly)**")
            for q in cac_flop3:
                price_str = fmt_price(q.price, "€")
                pct_str = fmt_pct(q.week_pct)
                lines.append(f"• **{q.name}** (`{price_str}`) : {pct_str}")
    else:
        lines.append("**Top 3 Gainers (Today)**")
        for q in cac_top3:
            price_str = fmt_price(q.price, "€")
            pct_str = fmt_pct(q.day_pct)
            lines.append(f"• **{q.name}** (`{price_str}`) : {pct_str}")
        if cac_flop3:
            lines.append("\n**Top 3 Losers (Today)**")
            for q in cac_flop3:
                price_str = fmt_price(q.price, "€")
                pct_str = fmt_pct(q.day_pct)
                lines.append(f"• **{q.name}** (`{price_str}`) : {pct_str}")

    return truncate_field(lines)


def fetch_candidates_for_category(category: str, limit: int = 4) -> list[dict]:
    urls = HEADLINE_FEEDS.get(category, [])
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    candidates = []
    for url in urls:
        items = []
        try:
            resp = requests.get(url, timeout=10, headers=headers)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for element in root.findall("./channel/item"):
                    raw_title = element.findtext("title")
                    raw_link = element.findtext("link")
                    title = ""
                    if raw_title:
                        title = raw_title.strip()
                    link = ""
                    if raw_link:
                        link = raw_link.strip()
                    if title and link:
                        item = {"title": title, "link": link}
                        items.append(item)
                    if len(items) >= limit:
                        break
        except Exception:
            pass

        if items:
            candidates = items
            break

    if not candidates:
        fallback = HARDCODED_FALLBACKS[category]
        candidates.append(fallback)

    return candidates


def select_headlines_with_gemini(
    tech_candidates: list[dict],
    macro_candidates: list[dict],
    cac_candidates: list[dict],
    crypto_candidates: list[dict],
    api_key: str,
) -> list[dict] | None:
    if not api_key:
        return None

    pool = {
        "Nasdaq / Tech": tech_candidates,
        "US Macro": macro_candidates,
        "CAC 40": cac_candidates,
        "Crypto": crypto_candidates,
    }

    prompt = (
        "You are a financial news editor formatting headlines for a mobile Discord newsletter.\n"
        "Given the candidate news articles below, select exactly 4 articles—one for each category in this exact order:\n"
        "1. category: 'Nasdaq / Tech' (best article on US Big Tech, AI, semiconductors, or Nasdaq)\n"
        "2. category: 'US Macro' (best article on the Federal Reserve, inflation, interest rates, or Wall Street broad markets)\n"
        "3. category: 'CAC 40' (best article on the Paris stock market, French blue chips, or European economy)\n"
        "4. category: 'Crypto' (best article on Bitcoin or cryptocurrency markets)\n\n"
        "Selection and Title Summarization Rules:\n"
        "- Choose the single most market-moving, impactful headline for each category from its candidate list.\n"
        "- You must keep the EXACT 'link' from the candidate object.\n"
        "- CRITICAL FOR MOBILE: Re-write/summarize the 'title' into a short, punchy headline (maximum 8 to 12 words, strictly under 65 characters) so it is effortless to read on a phone.\n"
        "- Output MUST be a valid JSON array of 4 objects with keys: 'category', 'title', 'link'.\n"
        "- Return ONLY the raw JSON array, without any markdown formatting or commentary.\n\n"
        f"Candidates:\n{json.dumps(pool, ensure_ascii=False)}"
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )

    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        candidates_field = data.get("candidates")
        if not candidates_field:
            return None

        first_cand = candidates_field[0]
        content_field = first_cand.get("content", {})
        parts_field = content_field.get("parts", [])
        if not parts_field:
            return None

        raw_text = parts_field[0].get("text", "").strip()
        if raw_text.startswith("```"):
            fence_lines = raw_text.split("\n")
            if fence_lines[0].startswith("```"):
                fence_lines = fence_lines[1:]
            if fence_lines and fence_lines[-1].startswith("```"):
                fence_lines = fence_lines[:-1]
            raw_text = "\n".join(fence_lines).strip()

        items = json.loads(raw_text)
        if isinstance(items, list) and len(items) == 4:
            valid_items = []
            for it in items:
                cat = str(it.get("category", "")).strip()
                title = str(it.get("title", "")).strip()
                link = str(it.get("link", "")).strip()
                if title and link:
                    valid_items.append({"category": cat, "title": title, "link": link})
            if len(valid_items) == 4:
                return valid_items
    except Exception:
        pass

    return None


def fetch_top_headlines(api_key: str = "") -> list[dict]:
    tech_candidates = fetch_candidates_for_category("Nasdaq / Tech", limit=4)
    macro_candidates = fetch_candidates_for_category("US Macro", limit=4)
    cac_candidates = fetch_candidates_for_category("CAC 40", limit=4)
    crypto_candidates = fetch_candidates_for_category("Crypto", limit=4)

    if api_key:
        gemini_result = select_headlines_with_gemini(
            tech_candidates,
            macro_candidates,
            cac_candidates,
            crypto_candidates,
            api_key,
        )
        if gemini_result and len(gemini_result) == 4:
            return gemini_result

    first_tech = tech_candidates[0]
    first_macro = macro_candidates[0]
    first_cac = cac_candidates[0]
    first_crypto = crypto_candidates[0]

    fallback_selected = [
        {
            "category": "Nasdaq / Tech",
            "title": first_tech["title"],
            "link": first_tech["link"],
        },
        {
            "category": "US Macro",
            "title": first_macro["title"],
            "link": first_macro["link"],
        },
        {
            "category": "CAC 40",
            "title": first_cac["title"],
            "link": first_cac["link"],
        },
        {
            "category": "Crypto",
            "title": first_crypto["title"],
            "link": first_crypto["link"],
        },
    ]
    return fallback_selected


def clean_and_shorten_title(title: str, max_chars: int = 65) -> str:
    cleaned = title.strip()
    if " - " in cleaned:
        parts = cleaned.rsplit(" - ", 1)
        if len(parts[0]) >= 15:
            cleaned = parts[0].strip()
    elif " | " in cleaned:
        parts = cleaned.rsplit(" | ", 1)
        if len(parts[0]) >= 15:
            cleaned = parts[0].strip()

    if len(cleaned) <= max_chars:
        return cleaned

    cutoff = max_chars - 3
    truncated = cleaned[:cutoff]
    last_space = truncated.rfind(" ")
    if last_space > 25:
        truncated = truncated[:last_space]
    return truncated + "..."


def shorten_url_if_needed(url: str) -> str:
    if len(url) <= 120:
        return url
    try:
        encoded_url = quote_plus(url)
        api_url = f"https://tinyurl.com/api-create.php?url={encoded_url}"
        resp = requests.get(api_url, timeout=3)
        if resp.status_code == 200:
            short_link = resp.text.strip()
            if short_link.startswith("http"):
                return short_link
    except Exception:
        pass
    return url


def format_headlines_field(items: list[dict], limit: int = 1024) -> str:
    """Format exactly 4 headlines as clickable markdown links within Discord's 1024-char limit."""
    if not items:
        return "No headlines available."

    lines = []
    for it in items:
        category_name = str(it.get("category", "")).strip()
        raw_title = str(it.get("title", "")).strip()
        raw_link = str(it.get("link", "")).strip()

        short_title = clean_and_shorten_title(raw_title, max_chars=65)
        clean_link = shorten_url_if_needed(raw_link)

        prefix = f"• **{category_name}** : "
        if clean_link:
            line = f"{prefix}[{short_title}]({clean_link})"
        else:
            line = f"{prefix}{short_title}"

        lines.append(line)

    return "\n".join(lines)


def maybe_generate_ai_summary(
    indices: list[QuotePerf],
    tech: list[QuotePerf],
    cac_top: list[QuotePerf],
    cac_flop: list[QuotePerf],
    cryptos: list[QuotePerf],
    headlines: list[str],
) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    facts = {
        "indices": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in indices
            if q.available
        ],
        "us_tech": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in tech
            if q.available
        ],
        "cac_top3": [
            {"name": q.name, "week_pct": round(q.week_pct, 2)}
            for q in cac_top
            if q.available
        ],
        "cac_bottom3": [
            {"name": q.name, "week_pct": round(q.week_pct, 2)}
            for q in cac_flop
            if q.available
        ],
        "crypto": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in cryptos
            if q.available
        ],
        "headlines": headlines,
    }

    prompt = (
        "You are a concise financial analyst. Using ONLY the JSON data below, write a crisp "
        "3-to-4 sentence editorial summary in English covering the week across US Tech, CAC 40, "
        "and Crypto. Direct, factual tone; never invent any numbers.\n\n"
        f"{json.dumps(facts, ensure_ascii=False)}"
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        candidates_field = data.get("candidates")
        if candidates_field:
            parts = candidates_field[0].get("content", {}).get("parts", [])
            if parts:
                text = parts[0].get("text", "").strip()
                if text:
                    return text[:1000]
    except Exception:
        pass

    return None


def truncate_field(lines: Iterable[str], limit: int = 1024) -> str:
    out = []
    total = 0
    for line in lines:
        add = len(line)
        if len(out) > 0:
            add = add + 1
        if total + add > limit:
            break
        out.append(line)
        total = total + add

    if len(out) == 0:
        return "Data unavailable."
    return "\n".join(out)


def build_discord_payload() -> dict:
    now_sf = datetime.now(SF_TZ)
    now_paris = now_sf.astimezone(PARIS_TZ)
    day_of_week = now_sf.weekday()
    is_friday = False
    if day_of_week == 4 or day_of_week == 5 or day_of_week == 6:
        is_friday = True

    indices = fetch_quotes(INDICES, currency="pts")
    tech = fetch_quotes(US_TECH_GIANTS, currency="$")
    cac_pairs = []
    for sym, name in CAC40_TICKERS.items():
        cac_pairs.append((sym, name))
    cac_stocks = fetch_quotes(cac_pairs, currency="€")
    cryptos = fetch_quotes(CRYPTOS, is_crypto=True, currency="$")

    available_tech = []
    for q in tech:
        if q.available:
            available_tech.append(q)
    if is_friday:
        available_tech.sort(key=lambda q: q.week_pct, reverse=True)
    else:
        available_tech.sort(key=lambda q: q.day_pct, reverse=True)

    tech_sorted = []
    tech_sorted.extend(available_tech)
    for q in tech:
        if not q.available:
            tech_sorted.append(q)

    available_cac = []
    for q in cac_stocks:
        if q.available:
            available_cac.append(q)
    if is_friday:
        available_cac.sort(key=lambda q: q.week_pct, reverse=True)
    else:
        available_cac.sort(key=lambda q: q.day_pct, reverse=True)

    cac_top3 = available_cac[:3]
    cac_flop3 = []
    if len(available_cac) >= 3:
        bottom_three = available_cac[-3:]
        cac_flop3 = list(reversed(bottom_three))

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    headline_items = fetch_top_headlines(api_key=api_key)
    headline_titles = []
    for it in headline_items:
        cat_name = it.get("category", "")
        t_text = it.get("title", "")
        headline_titles.append(f"{cat_name}: {t_text}")

    ai_summary = maybe_generate_ai_summary(
        indices, tech_sorted, cac_top3, cac_flop3, cryptos, headline_titles
    )

    idx_map = {}
    for q in indices:
        idx_map[q.name] = q

    btc = None
    for q in cryptos:
        if q.symbol == "BTC-USD":
            btc = q
            break

    push_parts = []
    labels = ["S&P 500", "Nasdaq", "CAC 40"]
    for label in labels:
        if label in idx_map:
            q = idx_map[label]
            if q.available:
                pct = q.day_pct
                if is_friday:
                    pct = q.week_pct
                pct_text = fmt_pct_compact(pct)
                push_parts.append(f"{label} {pct_text}")

    if btc and btc.available:
        btc_pct = btc.day_pct
        if is_friday:
            btc_pct = btc.week_pct
        price_text = fmt_price(btc.price, "$")
        pct_text = fmt_pct_compact(btc_pct)
        push_parts.append(f"BTC {price_text} ({pct_text})")

    prefix = "Market Close"
    if is_friday:
        prefix = "Weekly Close"
    user_id = os.getenv("DISCORD_USER_ID", "").strip()
    mention = ""
    if user_id:
        mention = f"<@{user_id}> "
    join_str = " | ".join(push_parts)
    push_summary = f"{mention}📊 **{prefix}** — {join_str}"

    allowed_mentions = {"parse": []}
    if user_id:
        allowed_mentions = {"users": [user_id]}

    ref = idx_map.get("Nasdaq")
    if not ref or not ref.available:
        ref = idx_map.get("S&P 500")
    ref_pct = 0.0
    if ref and ref.available:
        ref_pct = ref.day_pct
        if is_friday:
            ref_pct = ref.week_pct
    embed_color = 0x2ECC71
    if ref_pct < 0:
        embed_color = 0xE74C3C

    fields = []

    if ai_summary:
        summary_title = "📝 Market Brief"
        if is_friday:
            summary_title = "📝 Week in Brief"
        fields.append(
            {
                "name": summary_title,
                "value": ai_summary,
                "inline": False,
            }
        )

    # 1. Key Indices (Always 3 indices)
    idx_lines = []
    for q in indices:
        idx_lines.append(format_index_line(q, is_friday))
    fields.append(
        {
            "name": "🌍 Key Indices",
            "value": truncate_field(idx_lines),
            "inline": False,
        }
    )

    # 2. US Tech Giants (Always 8 stocks)
    tech_lines = []
    for q in tech_sorted:
        tech_lines.append(format_tech_line(q, is_friday))
    tech_title = "🇺🇸 US Tech Giants (Today's Ranking)"
    if is_friday:
        tech_title = "🇺🇸 US Tech Giants (Weekly Ranking)"
    fields.append(
        {
            "name": tech_title,
            "value": truncate_field(tech_lines),
            "inline": False,
        }
    )

    # 3. CAC 40 Top & Bottom 3 (Always Top 3 and Bottom 3)
    cac_title = "🇫🇷 CAC 40 — Today's Top & Bottom 3"
    if is_friday:
        cac_title = "🇫🇷 CAC 40 — Weekly Top & Bottom 3"
    cac_content = format_cac_section(cac_top3, cac_flop3, is_friday)
    fields.append(
        {
            "name": cac_title,
            "value": cac_content,
            "inline": False,
        }
    )

    # 4. Crypto (Always 3 cryptos)
    crypto_lines = []
    for q in cryptos:
        crypto_lines.append(format_crypto_line(q, is_friday))
    fields.append(
        {
            "name": "🪙 Crypto (24/7)",
            "value": truncate_field(crypto_lines),
            "inline": False,
        }
    )

    # 5. Top 4 Headlines (Always exactly 4 clickable articles)
    headline_title = "📰 Top 4 Headlines"
    if is_friday:
        headline_title = "📰 Top 4 Headlines of the Week"
    fields.append(
        {
            "name": headline_title,
            "value": format_headlines_field(headline_items),
            "inline": False,
        }
    )

    # Add blank line separator between fields for clean rendering on Discord
    total_fields = len(fields)
    for idx, field in enumerate(fields):
        if idx < total_fields - 1:
            val = field["value"]
            if len(val) <= 1022:
                field["value"] = val + "\n\u200b"

    date_str = now_sf.strftime("%Y-%m-%d")
    embed_title = f"📈 Market & Crypto Brief — {date_str}"
    if is_friday:
        embed_title = f"📈 Weekly Market & Crypto Brief — {date_str}"

    time_pt = now_sf.strftime("%I:%M %p")
    time_paris = now_paris.strftime("%H:%M")
    desc = f"US market close summary ({time_pt} PT / {time_paris} Paris)."

    embed = {
        "title": embed_title,
        "description": desc,
        "color": embed_color,
        "fields": fields[:25],
        "footer": {
            "text": "Source: Yahoo Finance & Google News · Automated via GitHub Actions"
        },
        "timestamp": now_sf.isoformat(),
    }

    payload = {
        "username": "Market Brief",
        "content": push_summary[:2000],
        "allowed_mentions": allowed_mentions,
        "embeds": [embed],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Send weekly market brief to Discord.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON payload without posting to Discord.",
    )
    args = parser.parse_args()

    payload = build_discord_payload()

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print(
            "Error: DISCORD_WEBHOOK_URL environment variable is not set.",
            file=sys.stderr,
        )
        return 1

    resp = requests.post(webhook_url, json=payload, timeout=15)
    if resp.status_code >= 400:
        print(
            f"Discord error ({resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        return 1

    print(f"Newsletter sent to Discord successfully (HTTP {resp.status_code}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
