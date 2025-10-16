# app.py
import datetime
import math
import io
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.figure_factory as ff
from datetime import timedelta

# -------------------------
# Config / defaults
# -------------------------
st.set_page_config(page_title="Timeline + Drilling Gantt", layout="wide")
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

# -------------------------
# Helpers
# -------------------------
def to_date_safe(val):
    if val is None or val == "" or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        # convert datetimes to date
        return val.date() if isinstance(val, datetime.datetime) else val
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None

def get_template_csv_bytes():
    cols = ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
            "Current Depth","Progress","Dependencies"]
    tmpl = pd.DataFrame(columns=cols).to_csv(index=False)
    return tmpl.encode("utf-8")

def compute_drilling_logic(df_raw, drilling_rate=DEFAULT_DRILL_RATE):
    """
    Compute Duration, Start, End, Progress.
    Behavior:
      - Duration = Planned Depth / drilling_rate
      - If user provided Start Date, respect it.
      - If Dependencies is set and dependency's End is known and rigs match:
          if Start is empty -> Start = dep.End + 1
      - If no dependency and Start empty -> set Start = last End of same rig (previous rows) +1
      - End = Start + ceil(Duration) days
      - Progress = CurrentDepth / PlannedDepth * 100
    """
    df = df_raw.copy().reset_index(drop=True)

    # ensure expected columns
    for col in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                "Current Depth","Progress","Dependencies"]:
        if col not in df.columns:
            df[col] = ""

    # preserve editable columns (including Start Date so user entries are respected)
    editable_cols = ["HoleID","Rigs","Current Depth","Dependencies","Planned Depth","Start Date"]
    df_edit = df[editable_cols].copy()

    # numeric conversions
    df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
    df["Current Depth"] = pd.to_numeric(df["Current Depth"], errors="coerce").fillna(0.0)

    # Duration (float days)
    rate = drilling_rate if (drilling_rate and drilling_rate > 0) else DEFAULT_DRILL_RATE
    df["Duration_calc"] = df["Planned Depth"] / rate

    # initialize Start/End from user's typed Start/End (so manual Start is respected)
    df["Start_parsed"] = df_edit["Start Date"].apply(to_date_safe)
    # If End Date typed by user, parse it; otherwise will be set from Start + Duration later
    df["End_parsed"] = df["End Date"].apply(to_date_safe)

    # Iterative dependency resolution (stop if no change or after max_passes)
    max_passes = max(5, len(df))
    for _ in range(max_passes):
        changed = False
        for idx, row in df.iterrows():
            dep = str(row.get("Dependencies","") or "").strip()
            if dep == "":
                continue
            # find dependency index by HoleID equality (first match)
            dep_idxs = df.index[df["HoleID"].astype(str) == dep].tolist()
            if not dep_idxs:
                continue
            dep_idx = dep_idxs[0]
            dep_end = df.at[dep_idx, "End_parsed"]
            if dep_end is None:
                continue
            rig_src = str(row.get("Rigs","")).strip()
            rig_dep = str(df.at[dep_idx,"Rigs"] or "").strip()
            # if rigs match, we can auto-set Start if not already set by user
            if rig_src != "" and rig_src == rig_dep:
                desired_start = dep_end + timedelta(days=1)
                if df.at[idx, "Start_parsed"] is None:
                    df.at[idx, "Start_parsed"] = desired_start
                    changed = True
                # update End_parsed if start now exists
                if df.at[idx, "Start_parsed"] is not None and not pd.isna(df.at[idx, "Duration_calc"]):
                    df.at[idx, "End_parsed"] = df.at[idx, "Start_parsed"] + timedelta(days=math.ceil(df.at[idx, "Duration_calc"]))
        if not changed:
            break

    # Auto-start for rows without dependencies and without Start: last end for same rig (previous rows)
    for idx, row in df.iterrows():
        if df.at[idx, "Start_parsed"] is None:
            rig = str(row.get("Rigs","")).strip()
            if rig == "":
                continue
            if idx == 0:
                continue
            prev = df.loc[:idx-1]
            same_rig_ends = prev[prev["Rigs"].astype(str) == rig]["End_parsed"].dropna()
            if not same_rig_ends.empty:
                df.at[idx, "Start_parsed"] = same_rig_ends.max() + timedelta(days=1)

    # Compute End_parsed from Start_parsed + ceil(Duration)
    for idx, row in df.iterrows():
        s = df.at[idx, "Start_parsed"]
        dur = df.at[idx, "Duration_calc"]
        if s is not None and not pd.isna(dur):
            df.at[idx, "End_parsed"] = s + timedelta(days=math.ceil(dur))

    # Format final columns
    df["Start Date"] = df["Start_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["End Date"] = df["End_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["Duration"] = df["Duration_calc"].apply(lambda v: round(v,3) if not pd.isna(v) else "")

    # Compute progress (safe)
    def _progress(r):
        try:
            pdp = r["Planned Depth"]
            if pd.isna(pdp) or float(pdp) == 0:
                return 0.0
            return round(100.0 * float(r["Current Depth"]) / float(pdp), 2)
        except Exception:
            return 0.0
    df["Progress"] = df.apply(_progress, axis=1)

    # restore editable columns (HoleID, Rigs, Current Depth, Dependencies, Planned Depth, Start Date typed by user)
    for col in editable_cols:
        df[col] = df_edit[col]

    # ensure columns order and no NaNs
    out = df[["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
              "Current Depth","Progress","Dependencies"]].replace({np.nan: ""})

    return out

# -------------------------
# Timeline Calculator (existing app)
# -------------------------
def timeline_tab():
    st.markdown("<h2 style='text-align:center;'>Timeline Calculator</h2>", unsafe_allow_html=True)
    st.markdown("<div style='background-color:lightgray; padding:6px;'>"
                "Against a set cut-off date (when assay results are returned)."
                "</div>", unsafe_allow_html=True)

    # helper
    def subtract_business_days(end_date, business_days):
        current = end_date
        days_remaining = business_days
        while days_remaining > 0:
            current -= datetime.timedelta(days=1)
            if current.weekday() < 5:
                days_remaining -= 1
        return current

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
                "Resource": task  # use task label for coloring
            })
            end = start - datetime.timedelta(days=1)
        return list(reversed(df))

    def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
        df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
        fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
        fig.update_layout(title="Gantt Chart", height=350)
        return fig, df[0]["Start"]

    # inputs
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

    # highlight shipment date
    try:
        shipment_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        today = datetime.datetime.today()
        if shipment_dt < today:
            color = "red"
        elif shipment_dt <= today + datetime.timedelta(weeks=3):
            color = "yellow"
        else:
            color = "lightgreen"
        st.markdown(f"<div style='background-color:{color}; padding:6px; text-align:center;'>"
                    f"<b>Shipment Date: {shipment_dt.strftime('%Y-%m-%d')}</b></div>", unsafe_allow_html=True)
    except Exception:
        pass

# -------------------------
# Drilling Gantt tab
# -------------------------
def drilling_tab():
    st.header("Drilling Gantt (Dependency-aware)")

    # CSV template / upload
    st.download_button("Download CSV template", data=get_template_csv_bytes(), file_name="drilling_template.csv", mime="text/csv")
    uploaded_file = st.file_uploader("Upload drilling CSV (optional)", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        if "Dependencies" not in df.columns:
            df["Dependencies"] = ""
        # ensure columns exist
        for c in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs","Current Depth","Progress","Dependencies"]:
            if c not in df.columns:
                df[c] = ""
    else:
        df = pd.DataFrame([{"HoleID":"","Start Date":"","End Date":"","Planned Depth":"","Duration":"",
                            "Rigs":"","Current Depth":"","Progress":"","Dependencies":""}])

    # drilling rate input (renamed)
    drill_rate = st.number_input("Drilling rate (ft/day)", value=DEFAULT_DRILL_RATE, min_value=0.01, step=0.1)

    # Build options for Dependencies (all HoleIDs)
    hole_options = [""] + [str(x) for x in df["HoleID"].astype(str).fillna("") if str(x).strip() != ""]

    # Data editor configuration: single-select Selectbox for Dependencies
    column_config = {
        "Dependencies": st.column_config.SelectboxColumn("Dependencies", options=hole_options),
        "Start Date": st.column_config.TextColumn("Start Date"),
        "End Date": st.column_config.TextColumn("End Date"),
        "Planned Depth": st.column_config.NumberColumn("Planned Depth"),
        "Current Depth": st.column_config.NumberColumn("Current Depth"),
        "Rigs": st.column_config.TextColumn("Rigs"),
        "HoleID": st.column_config.TextColumn("HoleID"),
    }

    st.markdown("**Edit the table below.** Add rows with +, fill HoleID, Planned Depth, Rigs, Dependencies (single-select).")
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, column_config=column_config)

    # Recompute with current drilling rate
    df_calc = compute_drilling_logic(edited, drilling_rate=drill_rate)

    # After recompute, regenerate dependency options (Streamlit will rerun and refresh editor next time)
    hole_options_after = [""] + [str(x) for x in df_calc["HoleID"].astype(str).fillna("") if str(x).strip() != ""]

    # Highlight dependency-linked rows in computed table
    def highlight_deps(row):
        if str(row["Dependencies"]).strip() != "":
            return ["background-color: lightgray"] * len(row)
        return [""] * len(row)

    st.subheader("Computed table (Start/End/Duration/Progress)")
    styled = df_calc.style.apply(highlight_deps, axis=1)
    st.dataframe(styled, use_container_width=True)

    # Gantt plot: only include rows with valid Start & End
    df_plot = df_calc[(df_calc["Start Date"].astype(str).str.strip() != "") & (df_calc["End Date"].astype(str).str.strip() != "")]
    if not df_plot.empty:
        df_plot = df_plot.copy()
        df_plot["Start_dt"] = pd.to_datetime(df_plot["Start Date"])
        df_plot["End_dt"] = pd.to_datetime(df_plot["End Date"])
        fig = px.timeline(df_plot, x_start="Start_dt", x_end="End_dt", y="HoleID",
                          color="Rigs", text=df_plot["Progress"].astype(str) + "%")
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=600, title="Drilling Gantt")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No rows have valid Start and End dates yet. Fill Planned Depth, Rigs and/or Dependencies to compute them.")

# -------------------------
# App layout (tabs)
# -------------------------
st.title("Project Tools")
tab1, tab2 = st.tabs(["Timeline Calculator", "Drilling Gantt"])
with tab1:
    timeline_tab()
with tab2:
    drilling_tab()
