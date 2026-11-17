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

# Major CAC 40 components (Yahoo Finance)
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


@dataclass
class QuotePerf:
    symbol: str
    name: str
    price: float
    day_pct: float
    week_pct: float
    currency: str = "$"


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
    tickers = [s for s, _ in symbols]
    name_map = dict(symbols)

    use_threads = False if len(tickers) <= 5 else True
    raw = yf.download(
        tickers=tickers,
        period="1mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=use_threads,
    )

    results: list[QuotePerf] = []
    single_ticker = len(tickers) == 1
    now_sf = datetime.now(SF_TZ).date()
    monday_this_week = now_sf - timedelta(days=now_sf.weekday())

    if not raw.empty:
        for sym in tickers:
            try:
                df = raw if single_ticker else raw[sym]
                closes = df["Close"].dropna()
                if len(closes) < 2:
                    continue

                last_price = float(closes.iloc[-1])
                prev_day_price = float(closes.iloc[-2])
                day_pct = ((last_price / prev_day_price) - 1.0) * 100.0

                if is_crypto:
                    idx = -8 if len(closes) >= 8 else 0
                    week_base = float(closes.iloc[idx])
                else:
                    prior_week = closes[closes.index.date < monday_this_week]
                    if not prior_week.empty:
                        week_base = float(prior_week.iloc[-1])
                    else:
                        idx = -6 if len(closes) >= 6 else 0
                        week_base = float(closes.iloc[idx])

                week_pct = ((last_price / week_base) - 1.0) * 100.0
                results.append(
                    QuotePerf(
                        symbol=sym,
                        name=name_map[sym],
                        price=last_price,
                        day_pct=day_pct,
                        week_pct=week_pct,
                        currency=currency,
                    )
                )
            except Exception:
                continue

    # Fallback retry for any missing symbol (e.g. CAC 40 database lock)
    found_symbols = {q.symbol for q in results}
    for sym, name in symbols:
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
                    day_pct = ((last_price / prev_day_price) - 1.0) * 100.0

                    if is_crypto:
                        idx = -8 if len(closes) >= 8 else 0
                        week_base = float(closes.iloc[idx])
                    else:
                        prior_week = closes[closes.index.date < monday_this_week]
                        if not prior_week.empty:
                            week_base = float(prior_week.iloc[-1])
                        else:
                            idx = -6 if len(closes) >= 6 else 0
                            week_base = float(closes.iloc[idx])

                    week_pct = ((last_price / week_base) - 1.0) * 100.0
                    results.append(
                        QuotePerf(
                            symbol=sym,
                            name=name,
                            price=last_price,
                            day_pct=day_pct,
                            week_pct=week_pct,
                            currency=currency,
                        )
                    )
            except Exception:
                continue

    # Keep original requested order
    order_map = {sym: idx for idx, (sym, _) in enumerate(symbols)}
    results.sort(key=lambda q: order_map.get(q.symbol, 999))

    return results


def fetch_feed_candidates(url: str, limit: int = 5) -> list[dict]:
    items: list[dict] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                items.append({"title": title, "link": link})
    except Exception:
        pass
    return items


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
        "tech_candidates": tech_candidates,
        "macro_candidates": macro_candidates,
        "cac_candidates": cac_candidates,
        "crypto_candidates": crypto_candidates,
    }

    prompt = (
        "You are a chief financial editor. Given the candidate news articles below, select exactly 4 articles—one for each category:\n"
        "1. category: 'Nasdaq / Tech' (best article on US Big Tech, AI, semiconductors, or Nasdaq)\n"
        "2. category: 'US Macro' (best article on the Federal Reserve, inflation, interest rates, or Wall Street broad markets)\n"
        "3. category: 'CAC 40' (best article on the Paris stock market, French blue chips, or European economy)\n"
        "4. category: 'Crypto' (best article on Bitcoin or cryptocurrency markets)\n\n"
        "Selection Rules:\n"
        "- Choose the single most market-moving, impactful headline for each category from its candidate list.\n"
        "- You must keep the EXACT 'link' from the candidate object.\n"
        "- You may keep or lightly refine the 'title' for crispness.\n"
        "- Output MUST be a valid JSON array of 4 objects with keys: 'category', 'title', 'link'.\n"
        "- Return ONLY the raw JSON array, without any markdown formatting or commentary.\n\n"
        f"Candidates:\n{json.dumps(pool, ensure_ascii=False)}"
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )

    try:
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        if raw_text.startswith("```"):
            fence_lines = raw_text.split("\n")
            if fence_lines[0].startswith("```"):
                fence_lines = fence_lines[1:]
            if fence_lines and fence_lines[-1].startswith("```"):
                fence_lines = fence_lines[:-1]
            raw_text = "\n".join(fence_lines).strip()

        items = json.loads(raw_text)
        if isinstance(items, list) and len(items) == 4:
            valid_items: list[dict] = []
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
    tech_candidates = fetch_feed_candidates(
        "https://www.cnbc.com/id/19854910/device/rss/rss.html", limit=4
    )
    macro_candidates = fetch_feed_candidates(
        "https://www.cnbc.com/id/20910258/device/rss/rss.html", limit=4
    )
    cac_candidates = fetch_feed_candidates(
        "https://news.google.com/rss/search?q=site:investir.lesechos.fr+CAC+40+when:2d&hl=fr&gl=FR&ceid=FR:fr",
        limit=4,
    )
    crypto_candidates = fetch_feed_candidates(
        "https://www.coindesk.com/arc/outboundfeeds/rss/", limit=4
    )

    if not tech_candidates:
        tech_candidates = fetch_feed_candidates(
            "https://www.cnbc.com/id/100003114/device/rss/rss.html", limit=4
        )
    if not macro_candidates:
        macro_candidates = fetch_feed_candidates(
            "https://www.cnbc.com/id/100003114/device/rss/rss.html", limit=4
        )
    if not cac_candidates:
        cac_candidates = fetch_feed_candidates(
            "https://www.lefigaro.fr/rss/figaro_economie.xml", limit=4
        )
    if not crypto_candidates:
        crypto_candidates = fetch_feed_candidates(
            "https://cointelegraph.com/rss", limit=4
        )

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

    fallback_selected: list[dict] = []
    if tech_candidates:
        first_tech = tech_candidates[0]
        fallback_selected.append(
            {
                "category": "Nasdaq / Tech",
                "title": first_tech["title"],
                "link": first_tech["link"],
            }
        )
    if macro_candidates:
        first_macro = macro_candidates[0]
        fallback_selected.append(
            {
                "category": "US Macro",
                "title": first_macro["title"],
                "link": first_macro["link"],
            }
        )
    if cac_candidates:
        first_cac = cac_candidates[0]
        fallback_selected.append(
            {
                "category": "CAC 40",
                "title": first_cac["title"],
                "link": first_cac["link"],
            }
        )
    if crypto_candidates:
        first_crypto = crypto_candidates[0]
        fallback_selected.append(
            {
                "category": "Crypto",
                "title": first_crypto["title"],
                "link": first_crypto["link"],
            }
        )

    return fallback_selected


def format_headlines_field(items: list[dict], limit: int = 1024) -> str:
    """Format up to 4 headlines as clickable markdown links within Discord's 1024-char limit."""
    if not items:
        return "No headlines available."

    selected = items[:4]
    lines: list[str] = []
    max_per_item = (limit - 10) // len(selected)

    for it in selected:
        cat = str(it.get("category", "")).strip()
        title = str(it.get("title", "")).strip()
        link = str(it.get("link", "")).strip()

        prefix = f"• **{cat}** : " if cat else "• "
        overhead = len(prefix) + len("[]()") + len(link)
        max_title = max(25, max_per_item - overhead)

        if len(title) > max_title:
            short_title = title[: max_title - 3] + "..."
        else:
            short_title = title

        if link:
            line = f"{prefix}[{short_title}]({link})"
        else:
            line = f"{prefix}{short_title}"

        lines.append(line)

    return truncate_field(lines, limit=limit)


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
        ],
        "us_tech": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in tech
        ],
        "cac_top3": [
            {"name": q.name, "week_pct": round(q.week_pct, 2)} for q in cac_top
        ],
        "cac_bottom3": [
            {"name": q.name, "week_pct": round(q.week_pct, 2)} for q in cac_flop
        ],
        "crypto": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in cryptos
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
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text[:1000] if text else None
    except Exception:
        return None


def truncate_field(lines: Iterable[str], limit: int = 1024) -> str:
    out: list[str] = []
    total = 0
    for line in lines:
        add = len(line) + (1 if out else 0)
        if total + add > limit:
            break
        out.append(line)
        total += add
    return "\n".join(out) if out else "Data unavailable."


def build_discord_payload() -> dict:
    now_sf = datetime.now(SF_TZ)
    now_paris = now_sf.astimezone(PARIS_TZ)
    day_of_week = now_sf.weekday()
    is_friday = False
    if day_of_week == 4 or day_of_week == 5 or day_of_week == 6:
        is_friday = True
    news_days = 7 if is_friday else 3

    indices = fetch_quotes(INDICES, currency="pts")
    tech = fetch_quotes(US_TECH_GIANTS, currency="$")
    cac_stocks = fetch_quotes(list(CAC40_TICKERS.items()), currency="€")
    cryptos = fetch_quotes(CRYPTOS, is_crypto=True, currency="$")

    sort_key = (lambda q: q.week_pct) if is_friday else (lambda q: q.day_pct)
    tech_sorted = sorted(tech, key=sort_key, reverse=True)
    cac_sorted = sorted(cac_stocks, key=sort_key, reverse=True)
    cac_top3 = cac_sorted[:3]
    cac_flop3 = list(reversed(cac_sorted[-3:])) if len(cac_sorted) >= 3 else []

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    headline_items = fetch_top_headlines(api_key=api_key)
    headline_titles = [
        f"{it.get('category', '')}: {it.get('title', '')}" for it in headline_items
    ]
    ai_summary = maybe_generate_ai_summary(
        indices, tech_sorted, cac_top3, cac_flop3, cryptos, headline_titles
    )

    # Short push notification preview text
    idx_map = {q.name: q for q in indices}
    btc = next((q for q in cryptos if q.symbol == "BTC-USD"), None)
    push_parts = []
    for label in ("S&P 500", "Nasdaq", "CAC 40"):
        if label in idx_map:
            pct = idx_map[label].week_pct if is_friday else idx_map[label].day_pct
            push_parts.append(f"{label} {fmt_pct_compact(pct)}")
    if btc:
        btc_pct = btc.week_pct if is_friday else btc.day_pct
        push_parts.append(f"BTC {fmt_price(btc.price, '$')} ({fmt_pct_compact(btc_pct)})")
    prefix = "Weekly Close" if is_friday else "Market Close"
    user_id = os.getenv("DISCORD_USER_ID", "").strip()
    mention = f"<@{user_id}> " if user_id else ""
    push_summary = f"{mention}📊 **{prefix}** — " + " | ".join(push_parts)
    allowed_mentions = {"users": [user_id]} if user_id else {"parse": []}

    ref = idx_map.get("Nasdaq") or idx_map.get("S&P 500")
    ref_pct = (ref.week_pct if is_friday else ref.day_pct) if ref else 0.0
    embed_color = 0x2ECC71 if ref_pct >= 0 else 0xE74C3C

    fields = []

    if ai_summary:
        fields.append(
            {
                "name": "📝 Week in Brief" if is_friday else "📝 Market Brief",
                "value": ai_summary,
                "inline": False,
            }
        )

    if indices:
        if is_friday:
            idx_lines = [
                f"**{q.name}** : `{fmt_price(q.price, q.currency)}` · Weekly {fmt_pct(q.week_pct)} *(1D {fmt_pct_compact(q.day_pct)})*"
                for q in indices
            ]
        else:
            idx_lines = [
                f"**{q.name}** : `{fmt_price(q.price, q.currency)}` · 1D {fmt_pct(q.day_pct)} *(WTD {fmt_pct_compact(q.week_pct)})*"
                for q in indices
            ]
        fields.append(
            {
                "name": "🌍 Key Indices",
                "value": truncate_field(idx_lines),
                "inline": False,
            }
        )

    if tech_sorted:
        if is_friday:
            tech_lines = [
                f"**{q.name}** (`{q.symbol}`) : `{fmt_price(q.price, '$')}` · Weekly {fmt_pct(q.week_pct)} *(1D {fmt_pct_compact(q.day_pct)})*"
                for q in tech_sorted
            ]
            tech_title = "🇺🇸 US Tech Giants (Weekly Ranking)"
        else:
            tech_lines = [
                f"**{q.name}** (`{q.symbol}`) : `{fmt_price(q.price, '$')}` · 1D {fmt_pct(q.day_pct)} *(WTD {fmt_pct_compact(q.week_pct)})*"
                for q in tech_sorted
            ]
            tech_title = "🇺🇸 US Tech Giants (Today's Ranking)"
        fields.append(
            {
                "name": tech_title,
                "value": truncate_field(tech_lines),
                "inline": False,
            }
        )

    if cac_top3 or cac_flop3:
        if is_friday:
            cac_lines = ["**Top 3 Gainers (Weekly)**"]
            cac_lines.extend(
                f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.week_pct)}"
                for q in cac_top3
            )
            if cac_flop3:
                cac_lines.append("\n**Top 3 Losers (Weekly)**")
                cac_lines.extend(
                    f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.week_pct)}"
                    for q in cac_flop3
                )
            cac_title = "🇫🇷 CAC 40 — Weekly Top & Bottom 3"
        else:
            cac_lines = ["**Top 3 Gainers (Today)**"]
            cac_lines.extend(
                f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.day_pct)}"
                for q in cac_top3
            )
            if cac_flop3:
                cac_lines.append("\n**Top 3 Losers (Today)**")
                cac_lines.extend(
                    f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.day_pct)}"
                    for q in cac_flop3
                )
            cac_title = "🇫🇷 CAC 40 — Today's Top & Bottom 3"
        fields.append(
            {
                "name": cac_title,
                "value": truncate_field(cac_lines),
                "inline": False,
            }
        )

    if cryptos:
        if is_friday:
            crypto_lines = [
                f"**{q.name}** : `{fmt_price(q.price, '$')}` · 7D {fmt_pct(q.week_pct)} *(24h {fmt_pct_compact(q.day_pct)})*"
                for q in cryptos
            ]
        else:
            crypto_lines = [
                f"**{q.name}** : `{fmt_price(q.price, '$')}` · 24h {fmt_pct(q.day_pct)} *(7D {fmt_pct_compact(q.week_pct)})*"
                for q in cryptos
            ]
        fields.append(
            {
                "name": "🪙 Crypto (24/7)",
                "value": truncate_field(crypto_lines),
                "inline": False,
            }
        )

    if headline_items:
        fields.append(
            {
                "name": "📰 Top 4 Headlines" if not is_friday else "📰 Top 4 Headlines of the Week",
                "value": format_headlines_field(headline_items),
                "inline": False,
            }
        )

    # Add a visible blank line between sections in Discord
    for field in fields[:-1]:
        val = field["value"]
        if len(val) <= 1022:
            field["value"] = val + "\n\u200b"

    embed = {
        "title": (
            f"📈 Weekly Market & Crypto Brief — {now_sf.strftime('%Y-%m-%d')}"
            if is_friday
            else f"📈 Market & Crypto Brief — {now_sf.strftime('%Y-%m-%d')}"
        ),
        "description": (
            f"US market close summary "
            f"({now_sf.strftime('%I:%M %p')} PT / {now_paris.strftime('%H:%M')} Paris)."
        ),
        "color": embed_color,
        "fields": fields[:25],
        "footer": {
            "text": "Source: Yahoo Finance & Google News · Automated via GitHub Actions"
        },
        "timestamp": now_sf.isoformat(),
    }

    return {
        "username": "Market Brief",
        "content": push_summary[:2000],
        "allowed_mentions": allowed_mentions,
        "embeds": [embed],
    }


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
