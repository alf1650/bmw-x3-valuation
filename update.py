#!/usr/bin/env python3
"""Scrape sgCarMart for BMW X3 sDrive20i listings and write data.json.

Configured for a 23-Jun-2021 registered BMW X3 sDrive20i.
Runs daily via GitHub Actions (see .github/workflows/update-data.yml).
Uses stdlib only — no external dependencies.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────
YOUR_CAR = {
    "model": "BMW X3 sDrive20i",
    "reg_date": "23-Jun-2021",
    "parf_cutoff": "23-Jun-2026",  # 5-yr mark; PARF drops 75% → 70%
}

# Filtered (2021) and unfiltered (all years) listings
LISTING_URLS = [
    "https://www.sgcarmart.com/used-cars/listing?avl=a&q=BMW+X3+sDrive20i&fr=2021&to=2021",
    "https://www.sgcarmart.com/used-cars/listing?avl=a&q=BMW+X3+sDrive20i",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-SG,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

OUT_FILE = Path(__file__).parent / "data.json"


# ── SCRAPER ─────────────────────────────────────────────────────────────
# Optional Cloudflare Worker proxy (sgCarMart blocks GitHub Actions IPs).
# When SGCARMART_PROXY_URL is set, requests are routed through it.
PROXY_URL = os.environ.get("SGCARMART_PROXY_URL", "").rstrip("/")
PROXY_TOKEN = os.environ.get("SGCARMART_PROXY_TOKEN", "")


def fetch(url: str) -> str:
    import gzip
    import time
    import zlib

    if PROXY_URL:
        request_url = f"{PROXY_URL}/?url={urllib.parse.quote(url, safe='')}"
        headers = {**HEADERS, "x-proxy-token": PROXY_TOKEN}
    else:
        request_url = url
        headers = HEADERS

    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(request_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                enc = resp.headers.get("Content-Encoding", "").lower()
                if enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    raw = zlib.decompress(raw)
                return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise last_err  # type: ignore[misc]


# sgCarMart embeds listings in Next.js RSC payload as escaped JSON:
#   \"car_model\":\"BMW X3 sDrive20i M-Sport\",\"price\":142800,...
# Anchor on car_model (unique string) and extract all fields from surrounding
# window independently — robust to field reordering / optional fields.
CAR_MODEL_RE = re.compile(
    r'\\"car_model\\":\\"(?P<car_model>BMW X3 sDrive20i[^\\]*)\\"'
)

DEALER_RE = re.compile(r'\\"dealer_code\\":(\d+),\\"name\\":\\"([^\\]+)\\"')


def _field(block: str, name: str, *, str_val: bool = True):
    """Extract a single JSON field from an escaped-quote block."""
    if str_val:
        m = re.search(rf'\\"{name}\\":\\"([^\\]*)\\"', block)
        return m.group(1) if m else None
    m = re.search(rf'\\"{name}\\":(\d+|null)', block)
    if not m:
        return None
    return None if m.group(1) == "null" else int(m.group(1))


def classify_trim(variant_text: str) -> str:
    t = variant_text.lower()
    if "m-sport" in t or "msport" in t:
        return "msport"
    if "xline" in t or "x-line" in t:
        return "xline"
    return "standard"


def parse_coe_months(s: str) -> int:
    m = re.match(r"(\d+)y\s*(\d+)m", (s or "").strip())
    return int(m.group(1)) * 12 + int(m.group(2)) if m else 0


def parse_int(s):
    if s is None or s == "null":
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def parse_owners(s: str) -> int:
    m = re.match(r"(\d+)", s or "")
    return int(m.group(1)) if m else 0


def clean_url(u: str) -> str:
    u = u.replace("\\u0026", "&")
    return u.split("?")[0].rstrip("/")


def parse_listings(html: str) -> list[dict]:
    dealers = {code: name.strip() for code, name in DEALER_RE.findall(html)}

    # Strip script tags so cross-chunk regex works (Next.js splits pushes).
    flat = re.sub(r"</?script[^>]*>", "", html)

    out: list[dict] = []
    seen: set[str] = set()
    seen_ids: set[int] = set()
    for m in CAR_MODEL_RE.finditer(flat):
        # Window: 800 chars before (to capture id/link) and 3000 after (fields)
        start = max(0, m.start() - 800)
        end = min(len(flat), m.end() + 3000)
        block = flat[start:end]

        id_m = re.search(r'\\"id\\":(\d+),\\"link\\":\\"(https://www\.sgcarmart\.com/used-cars/info/.+?)\\"', block)
        if not id_m:
            continue
        listing_id = int(id_m.group(1))
        if listing_id in seen_ids:
            continue

        url = clean_url(id_m.group(2))
        if url in seen:
            continue

        price = _field(block, "price", str_val=False)
        if price is None:
            continue

        reg_date = _field(block, "registration_date") or ""
        coe_left = _field(block, "coeLeft") or ""
        mileage = _field(block, "mileage", str_val=False)
        owners_str = _field(block, "owners") or ""
        depr = _field(block, "depreciation", str_val=False)

        # nearest dealer_code in the block
        dc = re.search(r'\\"dealer_code\\":(\d+)', block)
        dealer_name = dealers.get(dc.group(1), "—") if dc else "—"

        car_model = m.group("car_model")
        seen.add(url)
        seen_ids.add(listing_id)
        out.append({
            "id": listing_id,
            "variant": car_model,
            "trim": classify_trim(car_model),
            "price": price,
            "reg_date": reg_date,
            "reg_year": int(reg_date.split("-")[-1]) if "-" in reg_date else None,
            "coe_left": coe_left,
            "coe_months": parse_coe_months(coe_left),
            "mileage": mileage,
            "owners": parse_owners(owners_str),
            "depr_per_year": depr,
            "dealer": dealer_name,
            "url": url,
        })
    return out


# ── STATS ───────────────────────────────────────────────────────────────
def compute_stats(listings: list[dict]) -> dict:
    if not listings:
        return {}
    prices = [l["price"] for l in listings if l["price"]]
    deprs = [l["depr_per_year"] for l in listings if l["depr_per_year"]]
    jun = [l for l in listings if "-Jun-2021" in l["reg_date"]]
    jun_prices = [l["price"] for l in jun]
    ref = [l for l in jun if l["trim"] == "standard"] or jun or listings
    ref_prices = [l["price"] for l in ref]

    return {
        "count": len(listings),
        "price_min": min(prices),
        "price_max": max(prices),
        "price_avg": round(sum(prices) / len(prices)),
        "depr_avg": round(sum(deprs) / len(deprs)) if deprs else None,
        "jun_count": len(jun),
        "jun_price_min": min(jun_prices) if jun_prices else None,
        "jun_price_max": max(jun_prices) if jun_prices else None,
        "jun_price_avg": round(sum(jun_prices) / len(jun_prices)) if jun_prices else None,
        "est_your_car_low": min(ref_prices) if ref_prices else None,
        "est_your_car_high": max(ref_prices) if ref_prices else None,
    }


# ── MAIN ────────────────────────────────────────────────────────────────
def main() -> None:
    print(f"[{datetime.now().isoformat()}] Scraping sgCarMart…")
    all_listings: list[dict] = []
    seen: set[str] = set()
    for url in LISTING_URLS:
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  WARN: fetch failed for {url}: {e}")
            continue
        listings = parse_listings(html)
        q = url.split("?", 1)[1] if "?" in url else url
        print(f"  {q[:60]}… → {len(listings)} listings")
        for l in listings:
            if l["url"] not in seen:
                seen.add(l["url"])
                all_listings.append(l)

    # Keep only 2021 regs (user's year of interest)
    listings_2021 = sorted(
        (l for l in all_listings if l["reg_year"] == 2021),
        key=lambda x: x["price"],
    )

    if not all_listings:
        print(
            "ERROR: 0 listings parsed from sgCarMart. "
            "Likely IP-blocked or page structure changed. "
            "Preserving existing data.json and failing the job.",
            file=sys.stderr,
        )
        sys.exit(1)

    stats = compute_stats(listings_2021)

    cutoff = datetime.strptime(YOUR_CAR["parf_cutoff"], "%d-%b-%Y").date()
    days_to_cutoff = (cutoff - date.today()).days

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "your_car": YOUR_CAR,
        "days_to_parf_cutoff": days_to_cutoff,
        "stats": stats,
        "listings": listings_2021,
        "all_listings_count": len(all_listings),
        "source": "sgCarMart",
        "source_urls": LISTING_URLS,
    }

    OUT_FILE.write_text(json.dumps(payload, indent=2))
    print(
        f"Wrote {OUT_FILE.name}: {len(listings_2021)} × 2021 listings "
        f"(of {len(all_listings)} total) · {days_to_cutoff}d to PARF cutoff"
    )


if __name__ == "__main__":
    main()
