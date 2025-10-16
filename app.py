# app.py
import datetime
import math
import io
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
from datetime import timedelta

st.set_page_config(page_title="Timeline + Drilling Gantt", layout="wide")
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

# ---------------- helpers ----------------
def to_date_safe(val):
    if val is None or val == "" or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
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

def compute_drilling_logic(df_raw, drilling_rate=DEFAULT_DRILL_RATE, dependency_map=None):
    """
    df_raw: DataFrame from editor
    dependency_map: dict mapping HoleID -> chosen dependency HoleID ('' or None for none)
    """
    df = df_raw.copy().reset_index(drop=True)

    # ensure columns
    for col in ["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
                "Current Depth","Progress","Dependencies"]:
        if col not in df.columns:
            df[col] = ""

    # preserve editable fields
    editable_cols = ["HoleID","Rigs","Current Depth","Planned Depth","Start Date","Dependencies"]
    df_edit = df[editable_cols].copy()

    # numeric conversions
    df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
    df["Current Depth"] = pd.to_numeric(df["Current Depth"], errors="coerce").fillna(0.0)

    # Duration (float)
    rate = drilling_rate if (drilling_rate and drilling_rate > 0) else DEFAULT_DRILL_RATE
    df["Duration_calc"] = df["Planned Depth"] / rate

    # parse Start/End from user editable values (manual Start respected)
    df["Start_parsed"] = df_edit["Start Date"].apply(to_date_safe)
    df["End_parsed"] = df["End Date"].apply(to_date_safe)

    # use dependency_map (from per-row selectors) overriding any Dependencies column in editor
    if dependency_map is not None:
        # copy into df["Dependencies"] for reference
        for i, hid in enumerate(df["HoleID"].astype(str).fillna("")):
            df.at[i, "Dependencies"] = dependency_map.get(hid, "") if hid != "" else ""
    else:
        # use whatever is in the editor
        pass

    # Iterative resolution
    max_passes = max(5, len(df))
    for _ in range(max_passes):
        changed = False
        for idx, row in df.iterrows():
            dep_hole = str(row.get("Dependencies","") or "").strip()
            if dep_hole == "":
                continue
            # find dependency row by HoleID
            dep_idxs = df.index[df["HoleID"].astype(str) == dep_hole].tolist()
            if not dep_idxs:
                continue
            dep_idx = dep_idxs[0]
            dep_end = df.at[dep_idx, "End_parsed"]
            # if dependency's end unknown, skip for now
            if dep_end is None:
                continue
            rig_src = str(row.get("Rigs","")).strip()
            rig_dep = str(df.at[dep_idx, "Rigs"] or "").strip()
            # only auto-set start if rigs match
            if rig_src != "" and rig_src == rig_dep:
                desired_start = dep_end + timedelta(days=1)
                # only set start if user hasn't typed their own Start
                if df.at[idx, "Start_parsed"] is None:
                    df.at[idx, "Start_parsed"] = desired_start
                    changed = True
                # then set end if duration known
                if df.at[idx, "Start_parsed"] is not None and not pd.isna(df.at[idx, "Duration_calc"]):
                    df.at[idx, "End_parsed"] = df.at[idx, "Start_parsed"] + timedelta(days=math.ceil(df.at[idx, "Duration_calc"]))
        if not changed:
            break

    # Auto-start for same rig (previous rows)
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

    # Compute End from Start + ceil(Duration)
    for idx, row in df.iterrows():
        s = df.at[idx, "Start_parsed"]
        dur = df.at[idx, "Duration_calc"]
        if s is not None and not pd.isna(dur):
            df.at[idx, "End_parsed"] = s + timedelta(days=math.ceil(dur))

    # Format outputs
    df["Start Date"] = df["Start_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["End Date"] = df["End_parsed"].apply(lambda d: d.strftime(DATE_FMT) if d is not None else "")
    df["Duration"] = df["Duration_calc"].apply(lambda v: round(v,3) if not pd.isna(v) else "")

    # Progress safe
    def _progress(r):
        try:
            pdp = r["Planned Depth"]
            if pd.isna(pdp) or float(pdp) == 0:
                return 0.0
            return round(100.0 * float(r["Current Depth"]) / float(pdp), 2)
        except Exception:
            return 0.0
    df["Progress"] = df.apply(_progress, axis=1)

    # restore editable cols (so user typed values are preserved)
    for col in editable_cols:
        if col in df.columns:
            df[col] = df_edit[col]

    # final
    out = df[["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs",
              "Current Depth","Progress","Dependencies"]].replace({np.nan:""})
    return out

# ---------------- Timeline tab (kept as your original) ----------------
def timeline_tab():
    st.markdown("<h2 style='text-align:center;'>Timeline Calculator</h2>", unsafe_allow_html=True)
    st.markdown("<div style='background-color:lightgray; padding:6px;'>Against a set cut-off date (assay results).</div>", unsafe_allow_html=True)

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
            df.append({"Task": task, "Start": start.strftime("%Y-%m-%d"), "Finish": end.strftime("%Y-%m-%d"), "Resource": task})
            end = start - datetime.timedelta(days=1)
        return list(reversed(df))

    def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
        df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
        import plotly.figure_factory as ff
        fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
        fig.update_layout(title="Gantt Chart", height=350)
        return fig, df[0]["Start"]

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
    try:
        shipment_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        today = datetime.datetime.today()
        if shipment_dt < today:
            color = "red"
        elif shipment_dt <= today + datetime.timedelta(weeks=3):
            color = "yellow"
        else:
            color = "lightgreen"
        st.markdown(f"<div style='background-color:{color}; padding:6px; text-align:center;'><b>Shipment Date: {shipment_dt.strftime('%Y-%m-%d')}</b></div>", unsafe_allow_html=True)
    except Exception:
        pass

# ---------------- Drilling tab ----------------
def drilling_tab():
    st.header("Drilling Gantt (Dependency-aware)")

    # CSV template download
    st.download_button("Download CSV template", data=get_template_csv_bytes(), file_name="drilling_template.csv", mime="text/csv")

    # upload
    uploaded_file = st.file_uploader("Upload drilling CSV", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        if "Dependencies" not in df.columns:
            df["Dependencies"] = ""
    else:
        df = pd.DataFrame([{"HoleID":"","Start Date":"","End Date":"","Planned Depth":"","Duration":"",
                            "Rigs":"","Current Depth":"","Progress":"","Dependencies":""}])

    # drilling rate
    drill_rate = st.number_input("Drilling rate (ft/day)", value=DEFAULT_DRILL_RATE, min_value=0.01, step=0.1)

    # Build dependency options (HoleIDs). We'll provide per-row selectors below excluding the row's own HoleID.
    hole_ids = [str(x) for x in df["HoleID"].astype(str).fillna("")]

    # Configure editable table (we keep Dependencies column editable but we will also provide per-row selectors for reliable exclusion)
    col_config = {
        "HoleID": st.column_config.TextColumn("HoleID"),
        "Planned Depth": st.column_config.NumberColumn("Planned Depth"),
        "Current Depth": st.column_config.NumberColumn("Current Depth"),
        "Rigs": st.column_config.TextColumn("Rigs"),
        "Start Date": st.column_config.TextColumn("Start Date"),
        # keep Dependencies visible (users can edit) but we'll also show explicit selectors below
        "Dependencies": st.column_config.TextColumn("Dependencies")
    }

    st.markdown("Edit the table below (add rows with +). Then use the **Dependency selector** section below to pick one dependency per HoleID (the selector excludes the same row).")
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, column_config=col_config)

    # Build per-row dependency selectors (excludes own HoleID)
    st.markdown("### Dependency selector (single-select, excludes the row's own HoleID)")
    dependency_map = {}
    # We display selectors in columns for compactness
    for i, row in edited.iterrows():
        hid = str(row.get("HoleID","") or "")
        # options: all other holeIDs including blank
        options = [""] + [h for h in edited["HoleID"].astype(str).fillna("") if h.strip() != "" and h != hid]
        # default value from the table if present, else blank
        default = str(row.get("Dependencies","") or "")
        key = f"dep_select_{i}_{hid}"
        sel = st.selectbox(f"{hid or '[no HoleID]'} → depends on", options, index=(options.index(default) if default in options else 0), key=key)
        dependency_map[hid] = sel

    # Compute with dependency_map
    df_calc = compute_drilling_logic(edited, drilling_rate=drill_rate, dependency_map=dependency_map)

    # Visual indication: produce HTML-styled table where dependency rows are shaded
    def styled_html_table(df_show):
        # create simple styled HTML table
        html = "<table style='width:100%; border-collapse:collapse;'>"
        # header
        html += "<thead><tr>"
        for c in df_show.columns:
            html += f"<th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>{c}</th>"
        html += "</tr></thead><tbody>"
        for _, r in df_show.iterrows():
            dep = str(r.get("Dependencies","") or "").strip()
            row_style = "background:#efefef;" if dep != "" else ""
            html += f"<tr style='{row_style}'>"
            for c in df_show.columns:
                html += f"<td style='border:1px solid #eee;padding:6px'>{r[c]}</td>"
            html += "</tr>"
        html += "</tbody></table>"
        return html

    st.subheader("Computed table (dependency-linked rows shaded)")
    st.markdown(styled_html_table(df_calc), unsafe_allow_html=True)

    # Altair Gantt: only include rows with valid Start & End
    df_plot = df_calc[(df_calc["Start Date"].astype(str).str.strip() != "") & (df_calc["End Date"].astype(str).str.strip() != "")]
    if not df_plot.empty:
        df_plot = df_plot.copy()
        df_plot["Start_dt"] = pd.to_datetime(df_plot["Start Date"])
        df_plot["End_dt"] = pd.to_datetime(df_plot["End Date"])
        # Altair timeline: use x and x2
        chart = alt.Chart(df_plot).mark_bar().encode(
            x=alt.X('Start_dt:T', title='Start'),
            x2='End_dt:T',
            y=alt.Y('HoleID:N', sort=alt.EncodingSortField(field="Start_dt", order="ascending")),
            color=alt.Color('Rigs:N', title='Rig'),
            tooltip=['HoleID', 'Rigs', 'Start Date', 'End Date', 'Duration', 'Progress']
        ).properties(height=400, width='container')
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No rows with computed Start & End dates. Fill Planned Depth, Rigs and/or choose Dependencies.")

# ---------------- main app ----------------
st.title("Project Tools")
tab1, tab2 = st.tabs(["Timeline Calculator", "Drilling Gantt"])
with tab1:
    timeline_tab()
with tab2:
    drilling_tab()
