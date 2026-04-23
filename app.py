from __future__ import annotations

import pandas as pd
import streamlit as st

from planner import PlannerInputs, build_media_plan


st.set_page_config(page_title="Automated Media Planner", layout="wide")
st.title("Automated Media Planner")
st.caption("Upload the 3 input tables, fill brand brief inputs, and generate a slot-level media plan.")

with st.sidebar:
    st.header("1) Upload tables")
    forecast_file = st.file_uploader("Forecast table (date x page x slot x forecast)", type=["csv", "xlsx"])
    campaigns_file = st.file_uploader("Campaign performance table", type=["csv", "xlsx"])
    mapping_file = st.file_uploader("Campaign mapping table", type=["csv", "xlsx"])


def _read_file(file) -> pd.DataFrame:
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


st.header("2) Brand brief input sheet")
with st.form("planner_inputs"):
    c1, c2, c3 = st.columns(3)
    with c1:
        brand_name = st.text_input("Brand name", placeholder="Example: Brand A")
        brand_tag = st.selectbox("Brand tag", ["Old", "New"], index=1)
    with c2:
        comcat = st.text_input("Comcat", placeholder="Example: FMCG / Auto / BFSI")
        budget = st.number_input("Budget", min_value=0.0, value=100000.0, step=1000.0)
    with c3:
        start_date = st.date_input("Start date")
        duration_days = st.number_input("Duration (days)", min_value=1, value=7, step=1)

    st.subheader("Objective weights")
    wc1, wc2 = st.columns(2)
    with wc1:
        w_reach = st.slider("Reach weight", min_value=0, max_value=100, value=60)
    with wc2:
        w_roas = st.slider("ROAS weight", min_value=0, max_value=100, value=40)

    submitted = st.form_submit_button("Generate media plan")

if submitted:
    if not (forecast_file and campaigns_file and mapping_file):
        st.error("Please upload all 3 tables first.")
    elif not brand_name.strip() or not comcat.strip():
        st.error("Brand name and Comcat are required.")
    elif (w_reach + w_roas) == 0:
        st.error("At least one objective weight must be greater than 0.")
    else:
        try:
            forecast_df = _read_file(forecast_file)
            campaigns_df = _read_file(campaigns_file)
            mapping_df = _read_file(mapping_file)

            planner_inputs = PlannerInputs(
                brand_name=brand_name.strip(),
                brand_tag=brand_tag,
                comcat=comcat.strip(),
                objective_reach_weight=float(w_reach),
                objective_roas_weight=float(w_roas),
                budget=float(budget),
                start_date=pd.Timestamp(start_date),
                duration_days=int(duration_days),
            )

            plan = build_media_plan(forecast_df, campaigns_df, mapping_df, planner_inputs)
            st.success("Media plan generated.")
            st.dataframe(plan, use_container_width=True)

            st.subheader("Allocation summary")
            left, right = st.columns(2)
            with left:
                st.metric("Total allocated budget", f"{plan['budget_allocation'].sum():,.2f}")
                st.metric("Projected impressions", f"{plan['planned_impressions'].sum():,.0f}")
            with right:
                st.metric("Slots selected", f"{plan.shape[0]}")
                st.metric("Average historical efficiency", f"{plan['avg_efficiency_score'].mean():.2f}")

            csv_bytes = plan.to_csv(index=False).encode("utf-8")
            st.download_button("Download plan as CSV", data=csv_bytes, file_name="media_plan.csv", mime="text/csv")

        except Exception as exc:
            st.exception(exc)

st.markdown("---")
st.markdown(
    """
### Expected columns in tables
1. **Forecast table**: `date`, `page`, `slot`, `forecast_impressions` (or `forecast`).
2. **Campaign performance table**: `date`, `campaign_code`, `slot`, plus `booked_impressions` and `delivered_impressions`.
3. **Mapping table**: `campaign_code`, `country`, `audience_tag`, `start_time_tag`, `page`, `slot`,
   `creatives`, `creative_tag`, `underdelivered`, and optionally `brand_name`, `comcat`.
"""
)
