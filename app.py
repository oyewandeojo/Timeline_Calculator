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
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

# -------------------------
# Helper functions
# -------------------------
def to_date_safe(val):
    if val is None or val == "" or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        # convert to date if datetime-like
        return val.date() if isinstance(val, datetime.datetime) else val
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None

def compute_drilling_logic(df_raw, drilling_rate=DEFAULT_DRILL_RATE):
    """
    df_raw: dataframe (editable values preserved)
    - Duration = Planned Depth / drilling_rate
    - Respect manual Start Date if provided
    - Resolve dependencies iteratively (dependency HoleID -> Start = dep.End + 1 when rigs match)
    - Auto-start for same-rig subsequent rows (table order) when Start missing
    - Compute End Date = Start + ceil(Duration) days
    - Compute Progress = Current Depth / Planned Depth * 100
    Returns DataFrame with calculated columns filled (but preserves editable columns)
    """
    df = df_raw.copy().reset_index(drop=True)

    # ensure expected columns exist
    for col in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                "Current Depth","Progress","Dependencies"]:
        if col not in df.columns:
            df[col] = ""

    # preserve editable values first (so we don't wipe user edits)
    editable_cols = ["HoleID","Rigs","Current Depth","Dependencies","Planned Depth","Start Date"]
    df_editable = df[editable_cols].copy()

    # numeric conversions
    df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
    df["Current Depth"] = pd.to_numeric(df["Current Depth"], errors="coerce").fillna(0.0)

    # Duration calc using global drilling rate (float days)
    df["Duration_calc"] = df["Planned Depth"] / (drilling_rate if drilling_rate and drilling_rate>0 else DEFAULT_DRILL_RATE)

    # parse any existing Start / End values
    df["Start_parsed"] = df["Start Date"].apply(to_date_safe)
    df["End_parsed"] = df["End Date"].apply(to_date_safe)

    # If user provided Start Date (string parseable), Start_parsed will be not None and respected.
    # Resolve dependencies iteratively
    max_passes = max(5, len(df))
    for _ in range(max_passes):
        changed = False
        for idx, row in df.iterrows():
            dep = str(row.get("Dependencies","") or "").strip()
            if dep == "":
                continue
            # find row index of dependency by HoleID equality (first match)
            dep_idxs = df.index[df["HoleID"].astype(str) == dep].tolist()
            if not dep_idxs:
                continue
            dep_idx = dep_idxs[0]
            dep_end = df.at[dep_idx, "End_parsed"]
            if dep_end is None:
                continue  # dependency unresolved
            rig_src = str(row.get("Rigs","")).strip()
            rig_dep = str(df.at[dep_idx,"Rigs"] or "").strip()
            if rig_src != "" and rig_src == rig_dep:
                new_start = dep_end + timedelta(days=1)
                if df.at[idx, "Start_parsed"] != new_start:
                    # only set if different (and we didn't detect manual start)
                    if df.at[idx, "Start_parsed"] is None:
                        df.at[idx, "Start_parsed"] = new_start
                        changed = True
                    else:
                        # if user has typed a start, we prefer user's Start (don't override)
                        pass
        if not changed:
            break

    # Auto-set start dates for rows without dependencies and missing Start Date:
    # For each row in table order, if Start_parsed is None and has a rig, set to last end of same rig + 1
    for idx, row in df.iterrows():
        if df.at[idx, "Start_parsed"] is None:
            rig = str(row.get("Rigs","")).strip()
            if rig == "":
                continue
            # look at previous rows only (0..idx-1)
            if idx == 0:
                continue
            prev_rows = df.loc[:idx-1]
            same_rig_ends = prev_rows[prev_rows["Rigs"].astype(str) == rig]["End_parsed"].dropna()
            if not same_rig_ends.empty:
                df.at[idx, "Start_parsed"] = same_rig_ends.max() + timedelta(days=1)

    # Compute End_parsed where Start_parsed exists
    for idx, row in df.iterrows():
        s = df.at[idx, "Start_parsed"]
        dur = df.at[idx, "Duration_calc"]
        if s is not None and not pd.isna(dur):
            # use ceiling of duration as integer days
            df.at[idx, "End_parsed"] = s + timedelta(days=math.ceil(dur))
        # else leave End_parsed as-is (user may have filled it manually; we preserve if present)

    # Final formatting to strings
    df["Start Date"] = df["Start_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["End Date"] = df["End_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["Duration"] = df["Duration_calc"].apply(lambda v: round(v,3) if not pd.isna(v) else "")

    # Progress: avoid divide by zero
    def _progress(r):
        try:
            if pd.isna(r["Planned Depth"]) or r["Planned Depth"] == 0:
                return 0
            return round(100.0 * float(r["Current Depth"]) / float(r["Planned Depth"]), 2)
        except Exception:
            return 0
    df["Progress"] = df.apply(_progress, axis=1)

    # Put back editable columns (preserve user's typed values)
    for col in editable_cols:
        df[col] = df_editable[col]

    # Ensure expected order and fill NaN with empty string
    out = df[["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
              "Current Depth","Progress","Dependencies"]].replace({np.nan: ""})
    return out

# -------------------------
# CSV template helper
# -------------------------
def get_template_csv_bytes():
    cols = ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
            "Current Depth","Progress","Dependencies"]
    tmpl = pd.DataFrame(columns=cols).to_csv(index=False)
    return tmpl.encode("utf-8")

# -------------------------
# Timeline Calculator (your existing app)
# -------------------------
def timeline_tab():
    st.markdown("<h2 style='text-align: center; font-style:bold; font-size:24px;'>Timeline Calculator</h2>", unsafe_allow_html=True)
    st.markdown("<div style='background-color:lightgray; padding:6px; font-style:italic;'>"
                "Against a set cut-off date (when assay results are returned).<br>"
                "The core samples have to be shipped by the date specified below if editable variables are met."
                "</div>", unsafe_allow_html=True)

    # stage colors and helper as in your app
    stage_colors = {
        "Shipment→Split Gap": "lightblue",
        "Splitting": "orange",
        "Split→Lab Gap": "yellow",
        "Lab": "green"
    }
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

    # Shipment highlight
    try:
        shipment_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        today = datetime.datetime.today()
        if shipment_dt < today:
            color = "red"
        elif shipment_dt <= today + datetime.timedelta(weeks=3):
            color = "yellow"
        else:
            color = "lightgreen"
        st.markdown(f"<div style='background-color:{color}; padding:6px; text-align:center; font-size:14px;'>"
                    f"<b>Shipment Date: {shipment_dt.strftime('%Y-%m-%d')}</b></div>", unsafe_allow_html=True)
    except Exception:
        pass

# -------------------------
# Drilling Gantt tab
# -------------------------
def drilling_tab():
    st.header("Drilling Gantt (Dependency-aware)")

    # CSV template download
    st.download_button("Download CSV template", data=get_template_csv_bytes(), file_name="drilling_template.csv", mime="text/csv")

    # upload
    uploaded_file = st.file_uploader("Upload drilling CSV (optional)", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        # ensure Dependencies column exists
        if "Dependencies" not in df.columns:
            df["Dependencies"] = ""
    else:
        # default empty row
        df = pd.DataFrame([{"HoleID":"","Start Date":"","End Date":"","Planned Depth":"","Duration":"",
                            "Rigs":"","Current Depth":"","Progress":"","Dependencies":""}])

    # Global drilling rate
    drill_rate = st.number_input("Global Drilling Rate (units/day)", value=DEFAULT_DRILL_RATE, min_value=0.01, step=0.1)

    # We will keep rig colors in session_state so they persist while editing
    if "rig_colors" not in st.session_state:
        st.session_state.rig_colors = {}

    # Build current hole options from df (include empty)
    hole_options = [""] + [str(x) for x in df["HoleID"].astype(str).fillna("") if str(x).strip() != ""]

    # Build column_config for data_editor with dynamic dependency dropdown
    column_config = {
        "Dependencies": st.column_config.SelectboxColumn("Dependencies", options=hole_options),
        # Let user edit Start Date as text (yyyy-mm-dd) if desired
        "Start Date": st.column_config.TextColumn("Start Date"),
        "End Date": st.column_config.TextColumn("End Date"),
        "Planned Depth": st.column_config.NumberColumn("Planned Depth"),
        "Current Depth": st.column_config.NumberColumn("Current Depth"),
        "Rigs": st.column_config.TextColumn("Rigs"),
    }

    st.markdown("**Edit table below.** Add rows with the + button, fill HoleID, Planned Depth, Rigs, etc. Dependencies dropdown lists existing HoleIDs.")
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, column_config=column_config)

    # After editing, recompute logic (preserve user editable fields)
    df_calc = compute_drilling_logic(edited, drilling_rate=drill_rate)

    # Update hole options again (in case user added new HoleIDs) and re-render editor if needed:
    # (Streamlit reruns when you edit, so the SelectboxColumn will refresh next run)
    hole_options_after = [""] + [str(x) for x in df_calc["HoleID"].astype(str).fillna("") if str(x).strip() != ""]

    # Rig colors: create pickers for unique rigs and store in session_state
    rigs = [r for r in sorted(df_calc["Rigs"].astype(str).unique()) if r and r.strip() != ""]
    st.subheader("Rig colors (pick per rig)")
    cols = st.columns(3)
    for i, rig in enumerate(rigs):
        default = st.session_state.rig_colors.get(rig, "#636EFA")
        ci = cols[i % 3].color_picker(f"{rig}", value=default, key=f"rig_color_{rig}")
        st.session_state.rig_colors[rig] = ci

    # Build color map for plotly
    color_map = {rig: st.session_state.rig_colors.get(rig, "#636EFA") for rig in rigs}

    # Show computed table
    st.subheader("Computed table (calculated fields shown)")
    st.dataframe(df_calc, use_container_width=True)

    # Gantt chart: need start/end as datetimes — if empty, remove row
    df_plot = df_calc.copy()
    df_plot = df_plot[(df_plot["Start Date"].astype(str).str.strip() != "") & (df_plot["End Date"].astype(str).str.strip() != "")]
    # convert Start/End to datetime for plotly
    if not df_plot.empty:
        df_plot["Start_dt"] = pd.to_datetime(df_plot["Start Date"])
        df_plot["End_dt"] = pd.to_datetime(df_plot["End Date"])
        fig = px.timeline(df_plot,
                          x_start="Start_dt",
                          x_end="End_dt",
                          y="HoleID",
                          color="Rigs",
                          color_discrete_map=color_map,
                          text=df_plot["Progress"].astype(str) + "%")
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=600, title="Drilling Gantt")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No rows with computed Start and End dates yet. Fill Planned Depth, Rigs and/or Dependencies to compute dates.")

# -------------------------
# App layout with tabs
# -------------------------
st.set_page_config(page_title="Timeline + Drilling Gantt", layout="wide")
st.title("Project Tools")

tab1, tab2 = st.tabs(["Timeline Calculator", "Drilling Gantt"])
with tab1:
    timeline_tab()
with tab2:
    drilling_tab()
