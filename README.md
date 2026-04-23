# Automated Media Planner (Slot-Level)

This app creates a slot-level media plan based on:
- inventory forecast (`date x page x slot x forecast_impressions`),
- past campaign outcomes (`date x campaign x slot x booking/delivered`), and
- campaign metadata mapping.

## What the planner does
1. Takes **brand brief inputs**: brand name, old/new tag, comcat, objective weights (reach/ROAS), budget, start date, and duration.
2. Chooses historical baseline:
   - **Old brand**: uses same-brand history if available.
   - **New brand**: falls back to same-comcat history.
3. Scores each page-slot by:
   - forecasted inventory (reach proxy), and
   - historical delivery efficiency (ROAS proxy).
4. Allocates budget across slots and estimates planned impressions.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Input schemas
### 1) Forecast table
Required columns:
- `date`
- `page`
- `slot`
- `forecast_impressions` (or `forecast`)

### 2) Campaign performance table
Required columns:
- `date`
- `campaign_code`
- `slot`

Recommended columns:
- `booked_impressions` (or `booking`)
- `delivered_impressions` (or `delivered`)

### 3) Campaign mapping table
Required columns:
- `campaign_code`
- `page`
- `slot`

Recommended columns:
- `country`
- `audience_tag`
- `start_time_tag`
- `creatives`
- `creative_tag`
- `underdelivered`
- `brand_name`
- `comcat`

## Notes
- If no brand-level history exists for an old brand, the planner automatically uses comcat-level history.
- Objective weight sliders can be tuned for reach-heavy or ROAS-heavy planning.
