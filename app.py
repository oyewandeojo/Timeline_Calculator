import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import altair as alt

# ---------- Constants ----------
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

# ---------- Helpers ----------
def compute_table_logic(df, drill_rate=DEFAULT_DRILL_RATE):
    df = df.copy()
    df["Planned Depth"] = pd.to_numeric(df.get("Planned Depth", 0), errors="coerce")
    df["Current Depth"] = pd.to_numeric(df.get("Current Depth", 0), errors="coerce").fillna(0.0)
    df["Duration"] = (df["Planned Depth"] / drill_rate).round(2)

    df["Start_parsed"] = pd.to_datetime(df["Start Date"], errors="coerce")
    df["End_parsed"] = pd.to_datetime(df["End Date"], errors="coerce")

    # Resolve dependencies
    max_passes = max(5, len(df))
    for _ in range(max_passes):
        changed = False
        for idx, row in df.iterrows():
            dep = str(row.get("Dependency", "")).strip()
            if dep == "":
                continue
            dep_idx = df.index[df["HoleID"] == dep].tolist()
            if not dep_idx:
                continue
            dep_idx = dep_idx[0]
            dep_end = df.at[dep_idx, "End_parsed"]
            if pd.isna(dep_end):
                continue
            if row["Rigs"] == df.at[dep_idx, "Rigs"]:
                new_start = dep_end + timedelta(days=1)
                if pd.isna(df.at[idx, "Start_parsed"]) or df.at[idx, "Start_parsed"] != new_start:
                    df.at[idx, "Start_parsed"] = new_start
                    df.at[idx, "End_parsed"] = new_start + timedelta(days=int(np.ceil(row["Duration"])))
                    changed = True
        if not changed:
            break

    # Fill End Date if Start exists
    for idx, row in df.iterrows():
        if pd.notnull(row["Start_parsed"]) and pd.isnull(row["End_parsed"]):
            df.at[idx, "End_parsed"] = row["Start_parsed"] + pd.to_timedelta(np.ceil(row["Duration"]), unit='D')

    # Format for display
    df["Start Date"] = df["Start_parsed"].dt.strftime(DATE_FMT)
    df["End Date"] = df["End_parsed"].dt.strftime(DATE_FMT)
    df["Progress"] = (df["Current Depth"] / df["Planned Depth"] * 100).round(2).fillna(0)

    return df

def create_dependency_column_config():
    """Create column config for the data editor with dependency dropdowns"""
    return {
        "HoleID": st.column_config.TextColumn("HoleID", required=True),
        "Start Date": st.column_config.DateColumn("Start Date", format=DATE_FMT),
        "End Date": st.column_config.DateColumn("End Date", format=DATE_FMT),
        "Planned Depth": st.column_config.NumberColumn("Planned Depth", min_value=0.0, step=0.1),
        "Rigs": st.column_config.TextColumn("Rigs"),
        "Current Depth": st.column_config.NumberColumn("Current Depth", min_value=0.0, step=0.1),
        "Dependency": st.column_config.SelectboxColumn(
            "Dependency",
            help="Select dependency - will auto-update start date"
        )
    }

# ---------- Streamlit App ----------
st.title("Drilling Gantt with Inline Dependency Selector")

# Global drilling rate input
drill_rate = st.number_input(
    "Global Drilling Rate (ft/day)", 
    value=DEFAULT_DRILL_RATE, 
    min_value=0.1, 
    step=0.1,
    help="Editable global rate used to calculate duration for all holes"
)

# Initialize session state
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "HoleID", "Start Date", "End Date", "Planned Depth", 
        "Rigs", "Current Depth", "Dependency"
    ])

# Track previous state for change detection
if "prev_df_hash" not in st.session_state:
    st.session_state.prev_df_hash = None

# Create dependency options for each row
def get_dependency_options(df, current_hole_id):
    """Get dependency options excluding the current row's HoleID"""
    if df.empty or current_hole_id is None:
        return []
    return [h for h in df["HoleID"].dropna().unique() if h != current_hole_id]

# Enhanced data editor with dependency dropdowns
st.subheader("Drilling Schedule Table")
st.markdown("""
**Instructions:**
- Add/Edit rows in the table below
- Use the **Dependency** dropdown to select which hole this one depends on
- Start Date will automatically update to Dependency's End Date + 1 day (if same rig)
- Duration is calculated automatically using Global Drilling Rate
""")

# Prepare data for editing
edit_df = st.session_state.df.copy()

# Create dependency options for the column config
if not edit_df.empty:
    # Create a mapping of HoleID to available dependencies for each row
    dependency_options = {}
    for hole_id in edit_df["HoleID"]:
        dependency_options[hole_id] = get_dependency_options(edit_df, hole_id)
    
    # Update column config with dynamic options
    col_config = create_dependency_column_config()
    col_config["Dependency"].options = [""] + sorted(set(
        option for options in dependency_options.values() for option in options
    ))

    # Edit the dataframe
    edited_df = st.data_editor(
        edit_df,
        column_config=col_config,
        num_rows="dynamic",
        key="drilling_editor",
        use_container_width=True
    )
    
    # Check if dependencies changed and trigger recalculation
    current_hash = hash(str(edited_df[["HoleID", "Dependency", "Planned Depth"]].to_dict()))
    
    if st.session_state.prev_df_hash != current_hash:
        st.session_state.prev_df_hash = current_hash
        # Force recalculation
        with st.spinner("Recalculating schedule..."):
            st.session_state.df = compute_table_logic(edited_df, drill_rate=drill_rate)
            st.rerun()
    else:
        # Normal recalculation
        st.session_state.df = compute_table_logic(edited_df, drill_rate=drill_rate)
else:
    # Empty state
    edited_df = st.data_editor(
        st.session_state.df,
        column_config=create_dependency_column_config(),
        num_rows="dynamic",
        key="drilling_editor"
    )
    st.session_state.df = edited_df

# Display computed results
if not st.session_state.df.empty:
    st.subheader("Computed Schedule")
    
    # Show summary statistics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Holes", len(st.session_state.df))
    with col2:
        total_duration = st.session_state.df["Duration"].sum()
        st.metric("Total Duration (days)", f"{total_duration:.1f}")
    with col3:
        avg_progress = st.session_state.df["Progress"].mean()
        st.metric("Average Progress", f"{avg_progress:.1f}%")
    
    # Display the computed table
    display_df = st.session_state.df.copy()
    st.dataframe(
        display_df.style.format({
            "Duration": "{:.1f}",
            "Progress": "{:.1f}%"
        }),
        use_container_width=True
    )

    # Altair Gantt chart
    st.subheader("Drilling Schedule Gantt Chart")
    chart_df = st.session_state.df.copy()
    chart_df = chart_df[pd.notnull(chart_df["Start Date"]) & pd.notnull(chart_df["End Date"])]
    
    if not chart_df.empty:
        chart_df["Start"] = pd.to_datetime(chart_df["Start Date"])
        chart_df["End"] = pd.to_datetime(chart_df["End Date"])
        chart_df["HoleID"] = chart_df["HoleID"].astype(str)
        chart_df["Tooltip"] = (
            "Hole: " + chart_df["HoleID"] + 
            "\nStart: " + chart_df["Start Date"] +
            "\nEnd: " + chart_df["End Date"] +
            "\nDuration: " + chart_df["Duration"].round(1).astype(str) + " days" +
            "\nRig: " + chart_df["Rigs"].fillna("Not set") +
            "\nDependency: " + chart_df["Dependency"].fillna("None")
        )

        gantt = alt.Chart(chart_df).mark_bar(
            cornerRadius=3,
            opacity=0.7
        ).encode(
            x=alt.X("Start:T", title="Timeline"),
            x2=alt.X2("End:T"),
            y=alt.Y("HoleID:N", 
                   title="Hole ID",
                   sort=alt.SortField(field="Start", order="ascending")),
            color=alt.Color("Rigs:N", title="Rig", scale=alt.Scale(scheme="category10")),
            tooltip=["Tooltip:N"]
        ).properties(
            height=400,
            title="Drilling Schedule Gantt Chart"
        ).configure_axis(
            grid=True
        ).configure_view(
            strokeWidth=0
        )
        
        st.altair_chart(gantt, use_container_width=True)
    else:
        st.info("No valid date data available for Gantt chart. Please add Start/End dates.")
else:
    st.info("Add drilling data to the table above to get started.")

# Add some explanation
with st.expander("How it works"):
    st.markdown("""
    **Automatic Dependency Logic:**
    - When you select a dependency from the dropdown in the table, the system automatically:
      1. Excludes the row's own HoleID from dependency options
      2. Checks if the dependency has the same rig
      3. If same rig, updates the Start Date to be the dependency's End Date + 1 day
      4. Recalculates Duration based on Planned Depth and Global Drilling Rate
      5. Updates End Date accordingly
    
    **Key Features:**
    - Dependency selector is embedded directly in the input table
    - Global drilling rate remains editable and drives all duration calculations
    - Automatic date recalculation when dependencies change
    - Visual Gantt chart shows the complete schedule
    """)
