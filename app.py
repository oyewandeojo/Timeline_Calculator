import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import altair as alt

# ---------- Helpers ----------
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

def compute_table_logic(df, drill_rate=DEFAULT_DRILL_RATE):
    df = df.copy()
    df["Planned Depth"] = pd.to_numeric(df["Planned Depth"], errors="coerce")
    df["Current Depth"] = pd.to_numeric(df.get("Current Depth",0), errors="coerce").fillna(0.0)
    df["Duration"] = (df["Planned Depth"] / drill_rate).round(2)

    # Initialize parsed dates
    df["Start_parsed"] = pd.to_datetime(df["Start Date"], errors="coerce")
    df["End_parsed"] = pd.to_datetime(df["End Date"], errors="coerce")

    # Resolve dependencies
    max_passes = max(5, len(df))
    for _ in range(max_passes):
        changed = False
        for idx, row in df.iterrows():
            dep = str(row.get("Dependency","")).strip()
            if dep == "":
                continue
            dep_idx = df.index[df["HoleID"]==dep].tolist()
            if not dep_idx:
                continue
            dep_idx = dep_idx[0]
            dep_end = df.at[dep_idx,"End_parsed"]
            if dep_end is None:
                continue
            if row["Rigs"] == df.at[dep_idx,"Rigs"]:
                new_start = dep_end + timedelta(days=1)
                if df.at[idx,"Start_parsed"] != new_start:
                    df.at[idx,"Start_parsed"] = new_start
                    df.at[idx,"End_parsed"] = new_start + timedelta(days=int(np.ceil(row["Duration"])))
                    changed = True
        if not changed:
            break

    # Fill End Date if Start exists
    for idx, row in df.iterrows():
        if pd.notnull(row["Start_parsed"]):
            df.at[idx,"End_parsed"] = row["Start_parsed"] + pd.to_timedelta(np.ceil(row["Duration"]), unit='D')

    # Format for display
    df["Start Date"] = df["Start_parsed"].dt.strftime(DATE_FMT)
    df["End Date"] = df["End_parsed"].dt.strftime(DATE_FMT)
    df["Progress"] = (df["Current Depth"] / df["Planned Depth"] * 100).round(2).fillna(0)

    return df

# ---------- Streamlit Layout ----------
st.title("Drilling Gantt with Dependencies")

# Drilling rate input
drill_rate = st.number_input("Drilling rate (ft/day)", value=DEFAULT_DRILL_RATE, min_value=0.1, step=0.1)

# Editable table
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["HoleID","Start Date","End Date",
                                                "Planned Depth","Rigs","Current Depth","Dependency"])

edited_df = st.data_editor(st.session_state.df, num_rows="dynamic")

# Dependency selector for selected row
selected_idx = st.number_input("Select row index to assign Dependency", min_value=0,
                               max_value=len(edited_df)-1 if not edited_df.empty else 0, value=0, step=1)

if not edited_df.empty:
    current_hole = edited_df.at[selected_idx, "HoleID"]
    options = [h for h in edited_df["HoleID"] if h != current_hole and h != ""]
    dep_selected = st.selectbox(f"Dependency for {current_hole}", options, index=0 if options else -1)
    if dep_selected:
        edited_df.at[selected_idx, "Dependency"] = dep_selected

# Recompute table logic
st.session_state.df = compute_table_logic(edited_df, drill_rate=drill_rate)

# Display computed table
st.dataframe(st.session_state.df)

# Altair Gantt chart
if not st.session_state.df.empty:
    chart_df = st.session_state.df.copy()
    chart_df = chart_df[pd.notnull(chart_df["Start_parsed"]) & pd.notnull(chart_df["End_parsed"])]
    chart_df["Start"] = pd.to_datetime(chart_df["Start Date"])
    chart_df["End"] = pd.to_datetime(chart_df["End Date"])
    chart_df["HoleID"] = chart_df["HoleID"].astype(str)

    gantt = alt.Chart(chart_df).mark_bar().encode(
        x="Start:T",
        x2="End:T",
        y=alt.Y("HoleID:N", sort=alt.SortField(field="Start", order="ascending")),
        tooltip=["HoleID","Start Date","End Date","Planned Depth","Duration","Rigs","Dependency"]
    ).properties(height=400)
    st.altair_chart(gantt, use_container_width=True)
