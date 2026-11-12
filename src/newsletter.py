#!/usr/bin/env python3
"""
Newsletter hebdomadaire Bourse & Crypto envoyée sur Discord via Webhook.
100 % gratuit : données Yahoo Finance (yfinance) + actualités RSS + résumé IA Gemini optionnel.
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

# Principaux composants du CAC 40 (Yahoo Finance .PA)
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
        return f"{price:,.0f}".replace(",", " ") + " pts"
    if price >= 1000:
        return f"{currency}{price:,.0f}".replace(",", " ")
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
                # Dernière clôture strictement avant le lundi de la semaine en cours
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


def fetch_rss_headlines(query: str, lang: str = "fr", limit: int = 2) -> list[str]:
    hl = "fr" if lang == "fr" else "en-US"
    gl = "FR" if lang == "fr" else "US"
    ceid = "FR:fr" if lang == "fr" else "US:en"
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote_plus(query)}+when:7d&hl={hl}&gl={gl}&ceid={ceid}"
    )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items: list[str] = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            if title:
                short_title = title if len(title) <= 130 else title[:127] + "..."
                items.append(f"• {short_title}")
        return items
    except Exception:
        return []


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
        "cac_flop3": [
            {"name": q.name, "week_pct": round(q.week_pct, 2)} for q in cac_flop
        ],
        "crypto": [
            {"name": q.name, "price": round(q.price, 2), "week_pct": round(q.week_pct, 2)}
            for q in cryptos
        ],
        "headlines": headlines,
    }

    prompt = (
        "Tu es un analyste financier francophone. À partir UNIQUEMENT des données JSON ci-dessous, "
        "rédige un court paragraphe éditorial de 3 à 4 phrases maximum résumant l'ambiance de la semaine "
        "(Tech US, CAC 40, Crypto). Style direct, clair, factuel, sans inventer aucun chiffre.\n\n"
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
    return "\n".join(out) if out else "Données indisponibles."


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

    us_news = fetch_rss_headlines("Nasdaq Big Tech AI stock market", lang="en", limit=3)
    fr_news = fetch_rss_headlines("CAC 40 Bourse de Paris", lang="fr", limit=2)
    crypto_news = fetch_rss_headlines("Bitcoin crypto marché", lang="fr", limit=2)

    all_headlines = us_news + fr_news + crypto_news
    ai_summary = maybe_generate_ai_summary(
        indices, tech_sorted, cac_top3, cac_flop3, cryptos, all_headlines
    )

    # Texte court affiché dans la notification push sur téléphone
    idx_map = {q.name: q for q in indices}
    btc = next((q for q in cryptos if q.symbol == "BTC-USD"), None)
    push_parts = []
    for label in ("S&P 500", "Nasdaq", "CAC 40"):
        if label in idx_map:
            push_parts.append(f"{label} {fmt_pct_compact(idx_map[label].week_pct)}")
    if btc:
        push_parts.append(f"BTC {fmt_price(btc.price, '$')} ({fmt_pct_compact(btc.week_pct)})")
    push_summary = "📊 **Clôture Hebdo** — " + " | ".join(push_parts)

    # Couleur de l'embed selon la perf hebdo du Nasdaq / S&P 500
    ref = idx_map.get("Nasdaq") or idx_map.get("S&P 500")
    embed_color = 0x2ECC71 if (ref and ref.week_pct >= 0) else 0xE74C3C

    fields = []

    if ai_summary:
        fields.append(
            {
                "name": "📝 L'essentiel de la semaine",
                "value": ai_summary,
                "inline": False,
            }
        )

    if indices:
        idx_lines = [
            f"**{q.name}** : `{fmt_price(q.price, q.currency)}` · Hebdo {fmt_pct(q.week_pct)} *(Jour {fmt_pct_compact(q.day_pct)})*"
            for q in indices
        ]
        fields.append(
            {
                "name": "🌍 Indices Clés",
                "value": truncate_field(idx_lines),
                "inline": False,
            }
        )

    if tech_sorted:
        tech_lines = [
            f"**{q.name}** (`{q.symbol}`) : `{fmt_price(q.price, '$')}` · Hebdo {fmt_pct(q.week_pct)} *(Jour {fmt_pct_compact(q.day_pct)})*"
            for q in tech_sorted
        ]
        fields.append(
            {
                "name": "🇺🇸 Géants de la Tech US (classés sur la semaine)",
                "value": truncate_field(tech_lines),
                "inline": False,
            }
        )

    if cac_top3 or cac_flop3:
        cac_lines = ["**Top 3 hausses (hebdo)**"]
        cac_lines.extend(
            f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.week_pct)}"
            for q in cac_top3
        )
        if cac_flop3:
            cac_lines.append("\n**Top 3 baisses (hebdo)**")
            cac_lines.extend(
                f"• **{q.name}** (`{fmt_price(q.price, '€')}`) : {fmt_pct(q.week_pct)}"
                for q in cac_flop3
            )
        fields.append(
            {
                "name": "🇫🇷 CAC 40 — Top & Flop de la semaine",
                "value": truncate_field(cac_lines),
                "inline": False,
            }
        )

    if cryptos:
        crypto_lines = [
            f"**{q.name}** : `{fmt_price(q.price, '$')}` · 7j {fmt_pct(q.week_pct)} *(24h {fmt_pct_compact(q.day_pct)})*"
            for q in cryptos
        ]
        fields.append(
            {
                "name": "🪙 Crypto (24/7)",
                "value": truncate_field(crypto_lines),
                "inline": False,
            }
        )

    if all_headlines:
        fields.append(
            {
                "name": "📰 Actus marquantes de la semaine",
                "value": truncate_field(all_headlines),
                "inline": False,
            }
        )

    embed = {
        "title": f"📈 Newsletter Bourse & Crypto — {now_sf.strftime('%d/%m/%Y')}",
        "description": (
            f"Clôture hebdomadaire des marchés américains "
            f"({now_sf.strftime('%H:%M')} SF / {now_paris.strftime('%H:%M')} Paris)."
        ),
        "color": embed_color,
        "fields": fields[:25],
        "footer": {
            "text": "Source : Yahoo Finance & Google News · Automatisation GitHub Actions"
        },
        "timestamp": now_sf.isoformat(),
    }

    return {
        "username": "Market Brief",
        "content": push_summary[:2000],
        "embeds": [embed],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Envoie la newsletter hebdo sur Discord.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le payload JSON sans l'envoyer sur Discord.",
    )
    args = parser.parse_args()

    payload = build_discord_payload()

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print(
            "Erreur : la variable d'environnement DISCORD_WEBHOOK_URL est manquante.",
            file=sys.stderr,
        )
        return 1

    resp = requests.post(webhook_url, json=payload, timeout=15)
    if resp.status_code >= 400:
        print(
            f"Erreur Discord ({resp.status_code}) : {resp.text}",
            file=sys.stderr,
        )
        return 1

    print(f"Newsletter envoyée sur Discord avec succès (HTTP {resp.status_code}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
