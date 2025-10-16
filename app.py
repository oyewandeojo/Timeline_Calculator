import datetime
import streamlit as st
import pandas as pd
import numpy as np
from datetime import timedelta
import plotly.express as px
import plotly.figure_factory as ff

# --------------------------
# Timeline Calculator (existing app)
# --------------------------
def subtract_business_days(end_date, business_days):
    current = end_date
    days_remaining = business_days
    while days_remaining > 0:
        current -= datetime.timedelta(days=1)
        if current.weekday() < 5:  # Mon–Fri
            days_remaining -= 1
    return current

stage_colors = {
    "Shipment→Split Gap": "lightblue",
    "Splitting": "orange",
    "Split→Lab Gap": "yellow",
    "Lab": "green"
}

def create_gantt_df(shipment_gap, core_depth, split_rate, split_lab_gap, lab_days, cutoff_date_str):
    try:
        cutoff_date = datetime.datetime.strptime(cutoff_date_str, "%Y-%m-%d")
    except:
        cutoff_date = datetime.datetime.today() + datetime.timedelta(days=100)

    split_days = int(core_depth / split_rate)
    stages = [
        ("Shipment→Split Gap", shipment_gap, "workweek"),
        ("Splitting", split_days, "workweek"),
        ("Split→Lab Gap", split_lab_gap, "workweek"),
        ("Lab", lab_days, "calendar")
    ]

    df = []
    end = cutoff_date
    for task, duration, mode in reversed(stages):
        if mode == "calendar":
            start = end - datetime.timedelta(days=duration - 1)
        else:  # workweek
            start = subtract_business_days(end, duration - 1)
        df.append({
            "Task": task,
            "Start": start.strftime("%Y-%m-%d"),
            "Finish": end.strftime("%Y-%m-%d"),
            "Resource": stage_colors[task]
        })
        end = start - datetime.timedelta(days=1)
    return list(reversed(df))

def update_timeline_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
    df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
    fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
    fig.update_layout(title="Timeline Gantt", height=350)
    return fig, df[0]["Start"]

# --------------------------
# Drilling Gantt Helpers
# --------------------------
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

def to_date_safe(val):
    if val is None or val == "" or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (datetime.datetime, pd.Timestamp)):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except:
        return None

def compute_drilling_gantt(df, drilling_rate=DEFAULT_DRILL_RATE):
    df = df.copy().reset_index(drop=True)
    for col in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                "Current Depth","Progress","Dependencies"]:
        if col not in df.columns:
            df[col] = ""

    df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
    df["Current Depth"] = pd.to_numeric(df["Current Depth"], errors="coerce").fillna(0.0)

    # Duration calculation
    df["Duration_calc"] = df["Planned Depth"] / drilling_rate

    # Parse dates
   
