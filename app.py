import datetime
import streamlit as st
import pandas as pd
import numpy as np
import math
import plotly.express as px
import plotly.figure_factory as ff
from datetime import timedelta

# --------------------------
# Tab setup
# --------------------------
st.title("Integrated App: Timeline + Drilling Gantt")
tab1, tab2 = st.tabs(["Timeline Calculator", "Drilling Gantt"])

# ==========================
# Tab 1: Timeline Calculator
# ==========================
with tab1:
    st.markdown(
        "<h2 style='text-align: center; font-style:bold; font-size:24px;'>Timeline Calculator</h3>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<div style='background-color:lightgray; padding:6px; font-style:italic;'>"
        "Against a set cut-off date (when assay results are returned).<br>"
        "The core samples have to be shipped by the date specified below if all variables are met.<br>"
        "Green = safe; Yellow = within 3 weeks; Red = past due."
        "</div>",
        unsafe_allow_html=True
    )

    # Stage colors
    stage_colors = {
        "Shipment→Split Gap": "lightblue",
        "Splitting": "orange",
        "Split→Lab Gap": "yellow",
        "Lab": "green"
    }

    # Helper: subtract business days
    def subtract_business_days(end_date, business_days):
        current = end_date
        days_remaining = business_days
        while days_remaining > 0:
            current -= datetime.timedelta(days=1)
            if current.weekday() < 5:  # Mon–Fri
                days_remaining -= 1
        return current

    # Create Gantt DF
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
            else:
                start = subtract_business_days(end, duration - 1)
            df.append({
                "Task": task,
                "Start": start.strftime("%Y-%m-%d"),
                "Finish": end.strftime("%Y-%m-%d"),
                "Resource": stage_colors[task]
            })
            end = start - datetime.timedelta(days=1)
        return list(reversed(df))

    def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
        df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
        fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
        fig.update_layout(title="Gantt Chart", height=350)
        return fig, df[0]["Start"]

    # Inputs
    col1, col2 = st.columns(2)
    with col1:
        cutoff_date = st.text_input("Cut-off Date", "2025-12-01")
    with col2:
        core_depth = st.number_input("Core Footage (ft)", value=5000, step=1)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        shipment_gap = st.number_input("Shipment→Split Gap (days)", value=2, step=1)
    with col2:
        splitting_rate = st.slider("Splitting Rate (ft/day)", 50, 750, 150, step=5)
    with col3:
        split_to_lab_gap = st.number_input("Split→Lab Gap (days)", value=3, step=1)
    with col4:
        lab_days = st.slider("Lab Processing Time (days)", 10, 100, 50, step=5)

    fig, start_date = update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days)
    st.plotly_chart(fig, use_container_width=True)

    # Shipment date highlight
    shipment_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.datetime.today()
    if shipment_dt < today:
        color = "red"
    elif shipment_dt <= today + datetime.timedelta(weeks=3):
        color = "yellow"
    else:
        color = "lightgreen"
    st.markdown(
        f"<div style='background-color:{color}; padding:6px; text-align:center; font-size:14px;'>"
        f"<b>Shipment Date: {shipment_dt.strftime('%Y-%m-%d')}</b>"
        "</div>",
        unsafe_allow_html=True
    )

# ==========================
# Tab 2: Drilling Gantt
# ==========================
with tab2:
    st.header("Drilling Gantt (Dependency-aware)")

    DATE_FMT = "%Y-%m-%d"
    DEFAULT_DRILL_RATE = 10.0

    def to_date_safe(val):
        if val is None or val == "" or (isinstance(val, float) and math.isnan(val)):
            return None
        if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
            return val.date()
        try:
            return pd.to_datetime(val).date()
        except:
            return None

    def compute_table_logic(df_raw, drilling_rate=DEFAULT_DRILL_RATE):
        df = df_raw.copy().reset_index(drop=True)
        for col in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                    "Current Depth","Progress","Dependencies"]:
            if col not in df.columns:
                df[col] = ""
        df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
        df["Current Depth"] = pd.to_numeric(df["Current Depth"], errors="coerce").fillna(0.0)
        df["Duration_calc"] = df["Planned Depth"] / drilling_rate
        df["Start_parsed"] = df["Start Date"].apply(to_date_safe)
        df["End_parsed"] = df["End Date"].apply(to_date_safe)

        # Resolve dependencies iteratively
        max_passes = max(5, len(df))
        for _ in range(max_passes):
            changed = False
            for idx, row in df.iterrows():
                dep_hole = str(row.get("Dependencies","") or "").strip()
                if dep_hole == "":
                    continue
                dep_idx = df.index[df["HoleID"].astype(str) == dep_hole].tolist()
                if not dep_idx:
                    continue
                dep_idx = dep_idx[0]
                dep_end = df.at[dep_idx,"End_parsed"]
                if dep_end is None:
                    continue
                rig_src = str(row.get("Rigs","")).strip()
                rig_dep = str(df.at[dep_idx,"Rigs"] or "").strip()
                if rig_src != "" and rig_src == rig_dep:
                    new_start = dep_end + timedelta(days=1)
                    if df.at[idx,"Start_parsed"] != new_start:
                        df.at[idx,"Start_parsed"] = new_start
                        df.at[idx,"End_parsed"] = new_start + timedelta(days=math.ceil(df.at[idx,"Duration_calc"]))
                        changed = True
            if not changed:
                break

        for idx, row in df.iterrows():
            if row["Start_parsed"] is None:
                rig = str(row.get("Rigs","")).strip()
                if rig == "":
                    continue
                prev_rows = df.loc[:idx-1]
                same_rig_ends = prev_rows[prev_rows["Rigs"].astype(str) == rig]["End_parsed"].dropna()
                if not same_rig_ends.empty:
                    df.at[idx,"Start_parsed"] = same_rig_ends.max() + timedelta(days=1)

        for idx, row in df.iterrows():
            if df.at[idx,"Start_parsed"] is not None:
                df.at[idx,"End_parsed"] = df.at[idx,"Start_parsed"] + timedelta(days=math.ceil(df.at[idx,"Duration_calc"]))

        df["Start Date"] = df["Start_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
        df["End Date"] = df["End_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
        df["Duration"] = df["Duration_calc"].apply(lambda v: round(v,2) if not pd.isna(v) else "")
        df["Progress"] = df.apply(lambda r: round(100*r["Current Depth"]/r["Planned Depth"],2) if r["Planned Depth"]>0 else 0, axis=1)

        return df[["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                   "Current Depth","Progress","Dependencies"]].replace({np.nan:""})

    uploaded_file = st.file_uploader("Upload Drilling CSV", type=["csv"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.DataFrame({
            "HoleID":["H1","H2"], "Planned Depth":[100,120], "Rigs":["RigA","RigA"],
            "Current Depth":[0,0], "Dependencies":["",""]
        })

    drill_rate = st.number_input("Global Drilling Rate (m/day)", value=DEFAULT_DRILL_RATE)
    
    # Editable table
    hole_options = [""] + df["HoleID"].tolist()
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Dependencies": st.column_config.SelectboxColumn("Dependencies", options=hole_options)
        }
    )

    df_calc = compute_table_logic(edited_df, drilling_rate=drill_rate)
    
    fig = px.timeline(df_calc,
                      x_start="Start Date",
                      x_end="End Date",
                      y="HoleID",
                      color="Rigs",
                      text=df_calc["Progress"].astype(str) + "%")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)
