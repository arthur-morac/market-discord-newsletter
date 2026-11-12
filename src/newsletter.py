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

    raw = yf.download(
        tickers=tickers,
        period="1mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )

    results: list[QuotePerf] = []
    if raw.empty:
        return results

    single_ticker = len(tickers) == 1
    now_sf = datetime.now(SF_TZ).date()
    monday_this_week = now_sf - timedelta(days=now_sf.weekday())

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

    return results


def fetch_rss_headlines(query: str, limit: int = 1) -> list[tuple[str, str]]:
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote_plus(query)}+when:7d&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items: list[tuple[str, str]] = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title:
                items.append((title, link))
        return items
    except Exception:
        return []


def format_headlines_field(items: list[tuple[str, str]], limit: int = 1024) -> str:
    """Format up to 3 headlines as clickable markdown links within Discord's 1024-char limit."""
    selected = items[:3]
    if not selected:
        return "No headlines available."

    # Reserve budget per item so all 3 clickable links always fit under 1024 chars
    max_per_item = (limit - (len(selected) - 1)) // len(selected)
    lines: list[str] = []
    for title, link in selected:
        if link:
            overhead = len("• []()") + len(link)
            max_title = max(25, max_per_item - overhead)
            short_title = (
                title if len(title) <= max_title else title[: max_title - 3] + "..."
            )
            candidate = f"• [{short_title}]({link})"
            # Fallback to plain title if link itself is unusually long
            if len(candidate) > max_per_item:
                candidate = f"• {title[: max_per_item - 5]}..."
            lines.append(candidate)
        else:
            lines.append(f"• {title[: max_per_item - 2]}")

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

    indices = fetch_quotes(INDICES, currency="pts")
    tech = fetch_quotes(US_TECH_GIANTS, currency="$")
    cac_stocks = fetch_quotes(list(CAC40_TICKERS.items()), currency="€")
    cryptos = fetch_quotes(CRYPTOS, is_crypto=True, currency="$")

    tech_sorted = sorted(tech, key=lambda q: q.week_pct, reverse=True)
    cac_sorted = sorted(cac_stocks, key=lambda q: q.week_pct, reverse=True)
    cac_top3 = cac_sorted[:3]
    cac_flop3 = list(reversed(cac_sorted[-3:])) if len(cac_sorted) >= 3 else []

    # Exactly 3 top headlines: 1 US Tech/Markets, 1 CAC 40/Europe, 1 Bitcoin/Crypto
    us_news = fetch_rss_headlines("Nasdaq Big Tech stock market", limit=1)
    fr_news = fetch_rss_headlines("CAC 40 Paris stocks", limit=1)
    crypto_news = fetch_rss_headlines("Bitcoin crypto market", limit=1)

    headline_items = (us_news + fr_news + crypto_news)[:3]
    headline_titles = [t for t, _ in headline_items]
    ai_summary = maybe_generate_ai_summary(
        indices, tech_sorted, cac_top3, cac_flop3, cryptos, headline_titles
    )

    # Short push notification preview text
    idx_map = {q.name: q for q in indices}
    btc = next((q for q in cryptos if q.symbol == "BTC-USD"), None)
    push_parts = []
    for label in ("S&P 500", "Nasdaq", "CAC 40"):
        if label in idx_map:
            push_parts.append(f"{label} {fmt_pct_compact(idx_map[label].week_pct)}")
    if btc:
        push_parts.append(f"BTC {fmt_price(btc.price, '$')} ({fmt_pct_compact(btc.week_pct)})")
    push_summary = "@everyone 📊 **Weekly Close** — " + " | ".join(push_parts)

    ref = idx_map.get("Nasdaq") or idx_map.get("S&P 500")
    embed_color = 0x2ECC71 if (ref and ref.week_pct >= 0) else 0xE74C3C

    fields = []

    if ai_summary:
        fields.append(
            {
                "name": "📝 Week in Brief",
                "value": ai_summary,
                "inline": False,
            }
        )

    if indices:
        idx_lines = [
            f"**{q.name}** : `{fmt_price(q.price, q.currency)}` · Weekly {fmt_pct(q.week_pct)} *(1D {fmt_pct_compact(q.day_pct)})*"
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
        tech_lines = [
            f"**{q.name}** (`{q.symbol}`) : `{fmt_price(q.price, '$')}` · Weekly {fmt_pct(q.week_pct)} *(1D {fmt_pct_compact(q.day_pct)})*"
            for q in tech_sorted
        ]
        fields.append(
            {
                "name": "🇺🇸 US Tech Giants (Weekly Ranking)",
                "value": truncate_field(tech_lines),
                "inline": False,
            }
        )

    if cac_top3 or cac_flop3:
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
        fields.append(
            {
                "name": "🇫🇷 CAC 40 — Weekly Top & Bottom 3",
                "value": truncate_field(cac_lines),
                "inline": False,
            }
        )

    if cryptos:
        crypto_lines = [
            f"**{q.name}** : `{fmt_price(q.price, '$')}` · 7D {fmt_pct(q.week_pct)} *(24h {fmt_pct_compact(q.day_pct)})*"
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
                "name": "📰 Top 3 Headlines of the Week",
                "value": format_headlines_field(headline_items),
                "inline": False,
            }
        )

    embed = {
        "title": f"📈 Weekly Market & Crypto Brief — {now_sf.strftime('%Y-%m-%d')}",
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
        "allowed_mentions": {"parse": ["everyone"]},
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
