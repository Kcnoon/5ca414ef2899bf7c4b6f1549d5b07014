from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class PlannerInputs:
    brand_name: str
    brand_tag: str  # Old/New
    comcat: str
    objective_reach_weight: float
    objective_roas_weight: float
    budget: float
    start_date: pd.Timestamp
    duration_days: int


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [c.strip().lower().replace(" ", "_") for c in normalized.columns]
    return normalized


def _coerce_datetime(df: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    for col in candidates:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _safe_col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index)


def prepare_tables(
    forecast_df: pd.DataFrame,
    campaigns_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    forecast_df = _normalize_columns(forecast_df)
    campaigns_df = _normalize_columns(campaigns_df)
    mapping_df = _normalize_columns(mapping_df)

    forecast_df = _coerce_datetime(forecast_df, ["date"])
    campaigns_df = _coerce_datetime(campaigns_df, ["date", "campaign_date"])

    if "campaign_date" in campaigns_df.columns and "date" not in campaigns_df.columns:
        campaigns_df = campaigns_df.rename(columns={"campaign_date": "date"})

    # Standardize key naming.
    rename_map = {
        "forecast": "forecast_impressions",
        "impressions_forecast": "forecast_impressions",
        "booking": "booked_impressions",
        "bookings": "booked_impressions",
        "delivered": "delivered_impressions",
        "campaign": "campaign_code",
        "campaign_id": "campaign_code",
    }
    forecast_df = forecast_df.rename(columns={k: v for k, v in rename_map.items() if k in forecast_df.columns})
    campaigns_df = campaigns_df.rename(columns={k: v for k, v in rename_map.items() if k in campaigns_df.columns})
    mapping_df = mapping_df.rename(columns={k: v for k, v in rename_map.items() if k in mapping_df.columns})

    required_forecast = {"date", "page", "slot", "forecast_impressions"}
    missing_forecast = required_forecast - set(forecast_df.columns)
    if missing_forecast:
        raise ValueError(f"Forecast table missing required columns: {sorted(missing_forecast)}")

    required_campaigns = {"date", "campaign_code", "slot"}
    missing_campaigns = required_campaigns - set(campaigns_df.columns)
    if missing_campaigns:
        raise ValueError(f"Campaign table missing required columns: {sorted(missing_campaigns)}")

    required_mapping = {"campaign_code", "page", "slot"}
    missing_mapping = required_mapping - set(mapping_df.columns)
    if missing_mapping:
        raise ValueError(f"Mapping table missing required columns: {sorted(missing_mapping)}")

    return forecast_df, campaigns_df, mapping_df


def build_media_plan(
    forecast_df: pd.DataFrame,
    campaigns_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    inputs: PlannerInputs,
) -> pd.DataFrame:
    forecast_df, campaigns_df, mapping_df = prepare_tables(forecast_df, campaigns_df, mapping_df)

    end_date = inputs.start_date + pd.Timedelta(days=max(inputs.duration_days - 1, 0))

    f_window = forecast_df[(forecast_df["date"] >= inputs.start_date) & (forecast_df["date"] <= end_date)].copy()
    if f_window.empty:
        raise ValueError("No forecast inventory found for the selected date range.")

    # Join campaign performance with slot/page mapping.
    history = campaigns_df.merge(mapping_df, on="campaign_code", how="left", suffixes=("", "_map"))
    history["booked_impressions"] = _safe_col(history, "booked_impressions", 0.0)
    history["delivered_impressions"] = _safe_col(history, "delivered_impressions", 0.0)

    delivery_ratio = np.where(history["booked_impressions"] > 0, history["delivered_impressions"] / history["booked_impressions"], 0)
    history["delivery_ratio"] = np.clip(delivery_ratio, 0, 3)

    if "underdelivered" in history.columns:
        ud = history["underdelivered"].astype(str).str.lower().isin(["1", "true", "yes", "y"])
    else:
        ud = pd.Series(False, index=history.index)

    history["efficiency_score"] = history["delivery_ratio"] * np.where(ud, 0.7, 1.0)

    # Segment selection according to brand tag.
    brand_is_old = inputs.brand_tag.strip().lower() == "old"
    filtered_hist = history.copy()

    if brand_is_old and "brand_name" in filtered_hist.columns:
        filtered_hist = filtered_hist[filtered_hist["brand_name"].astype(str).str.lower() == inputs.brand_name.strip().lower()]

    if (not brand_is_old or filtered_hist.empty) and "comcat" in filtered_hist.columns:
        filtered_hist = history[history["comcat"].astype(str).str.lower() == inputs.comcat.strip().lower()]

    # Aggregate performance at slot-page level.
    perf = (
        filtered_hist.groupby(["page", "slot"], dropna=False)
        .agg(
            hist_campaigns=("campaign_code", "nunique"),
            avg_delivery_ratio=("delivery_ratio", "mean"),
            avg_efficiency_score=("efficiency_score", "mean"),
            total_delivered=("delivered_impressions", "sum"),
        )
        .reset_index()
    )

    inv = (
        f_window.groupby(["page", "slot"], as_index=False)["forecast_impressions"]
        .sum()
        .rename(columns={"forecast_impressions": "forecast_impressions_window"})
    )

    plan = inv.merge(perf, on=["page", "slot"], how="left")
    plan["hist_campaigns"] = plan["hist_campaigns"].fillna(0)
    plan["avg_delivery_ratio"] = plan["avg_delivery_ratio"].fillna(0.8)
    plan["avg_efficiency_score"] = plan["avg_efficiency_score"].fillna(0.8)

    # Objective scoring.
    reach_score = plan["forecast_impressions_window"] / max(plan["forecast_impressions_window"].max(), 1)
    roas_score = plan["avg_efficiency_score"] / max(plan["avg_efficiency_score"].max(), 1e-6)

    total_weight = max(inputs.objective_reach_weight + inputs.objective_roas_weight, 1e-6)
    wr = inputs.objective_reach_weight / total_weight
    wo = inputs.objective_roas_weight / total_weight

    plan["final_score"] = wr * reach_score + wo * roas_score
    score_sum = max(plan["final_score"].sum(), 1e-9)

    plan["budget_allocation"] = inputs.budget * (plan["final_score"] / score_sum)
    # Use forecast and allocation as dual constraints for planned impressions.
    plan["planned_impressions"] = plan["forecast_impressions_window"] * (plan["budget_allocation"] / max(inputs.budget, 1e-9))

    plan = plan.sort_values("budget_allocation", ascending=False).reset_index(drop=True)
    plan.insert(0, "brand_name", inputs.brand_name)
    plan.insert(1, "brand_tag", inputs.brand_tag)
    plan.insert(2, "comcat", inputs.comcat)
    plan["plan_start_date"] = inputs.start_date.date()
    plan["plan_end_date"] = end_date.date()

    output_cols = [
        "brand_name",
        "brand_tag",
        "comcat",
        "plan_start_date",
        "plan_end_date",
        "page",
        "slot",
        "forecast_impressions_window",
        "hist_campaigns",
        "avg_delivery_ratio",
        "avg_efficiency_score",
        "final_score",
        "budget_allocation",
        "planned_impressions",
    ]
    return plan[output_cols]
