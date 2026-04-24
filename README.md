# BMW X3 sDrive20i — Sell or Keep?

Self-updating valuation dashboard for a BMW X3 sDrive20i (Reg. 23 Jun 2021), tracking Singapore used-car market prices on sgCarMart to help decide whether to sell before the 5-year PARF cutoff.

## What it does

- **`update.py`** — scrapes sgCarMart for all active 2021 BMW X3 sDrive20i listings and writes `data.json` (Python stdlib only, no deps).
- **`index.html`** — dashboard that fetches `data.json` on load: KPI cards, price range viz, sell-before-vs-after-June PARF comparison, sortable/filterable listings table, and verdict.
- **`.github/workflows/update-data.yml`** — runs `update.py` daily at 02:00 UTC and auto-commits `data.json` if anything changed.

## Local use

```bash
python3 update.py   # writes data.json
open index.html     # view dashboard (or serve with `python3 -m http.server`)
```

## Deploy (auto-update daily)

1. `git init && git add . && git commit -m "initial"`
2. Create a GitHub repo and push.
3. In repo **Settings → Pages**, enable GitHub Pages from `main` branch.
4. The workflow runs daily; `data.json` is auto-committed and the dashboard stays current.

Manual trigger: **Actions → Update BMW X3 valuation data → Run workflow**.

## Configuration

Edit `YOUR_CAR` at the top of `update.py` to change car model, reg date, or PARF cutoff. The search URLs in `LISTING_URLS` can be adjusted for a different model/year.

## Data source

sgCarMart listings (extracted from Next.js RSC flight payload embedded in the HTML). No API key needed.
