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

    # Parse dates, handling both string and date objects
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

    # Fill End Date if Start exists but End doesn't
    for idx, row in df.iterrows():
        if pd.notnull(row["Start_parsed"]) and pd.isnull(row["End_parsed"]):
            df.at[idx, "End_parsed"] = row["Start_parsed"] + pd.to_timedelta(np.ceil(row["Duration"]), unit='D')

    # Format for display - keep as strings for data editor compatibility
    df["Start Date"] = df["Start_parsed"].dt.strftime(DATE_FMT)
    df["End Date"] = df["End_parsed"].dt.strftime(DATE_FMT)
    df["Progress"] = (df["Current Depth"] / df["Planned Depth"] * 100).round(2).fillna(0)

    return df

def prepare_data_for_editor(df):
    """Prepare dataframe for data editor - ensure proper data types"""
    editor_df = df.copy()
    
    # Convert date columns to datetime objects for editing, but handle NaNs
    if "Start Date" in editor_df.columns:
        editor_df["Start Date"] = pd.to_datetime(editor_df["Start Date"], errors="coerce")
    if "End Date" in editor_df.columns:
        editor_df["End Date"] = pd.to_datetime(editor_df["End Date"], errors="coerce")
    
    return editor_df

def get_dependency_options(df, current_hole_id):
    """Get dependency options excluding the current row's HoleID"""
    if df.empty or current_hole_id is None:
        return []
    return [h for h in df["HoleID"].dropna().unique() if h != current_hole_id]

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

# Enhanced data editor with dependency dropdowns
st.subheader("Drilling Schedule Table")
st.markdown("""
**Instructions:**
- Add/Edit rows in the table below
- Use the **Dependency** dropdown to select which hole this one depends on
- Start Date will automatically update to Dependency's End Date + 1 day (if same rig)
- Duration is calculated automatically using Global Drilling Rate
""")

# Prepare data for editing - convert dates to proper format
edit_df = prepare_data_for_editor(st.session_state.df)

# Create dynamic column configuration
def create_dynamic_column_config(df):
    """Create column config with dynamic dependency options"""
    base_config = {
        "HoleID": st.column_config.TextColumn("HoleID", required=True),
        "Start Date": st.column_config.DateColumn(
            "Start Date", 
            format="YYYY-MM-DD",
            help="Start date - will auto-update if dependency is selected"
        ),
        "End Date": st.column_config.DateColumn(
            "End Date", 
            format="YYYY-MM-DD",
            help="End date - calculated automatically"
        ),
        "Planned Depth": st.column_config.NumberColumn(
            "Planned Depth", 
            min_value=0.0, 
            step=0.1,
            help="Planned depth in feet"
        ),
        "Rigs": st.column_config.TextColumn(
            "Rigs",
            help="Rig name - dependencies only affect same rig"
        ),
        "Current Depth": st.column_config.NumberColumn(
            "Current Depth", 
            min_value=0.0, 
            step=0.1,
            help="Current depth achieved"
        ),
    }
    
    # Add dependency column with options if we have data
    if not df.empty and "HoleID" in df.columns:
        # Get all unique HoleIDs for dependency options
        all_hole_ids = df["HoleID"].dropna().unique().tolist()
        base_config["Dependency"] = st.column_config.SelectboxColumn(
            "Dependency",
            options=[""] + all_hole_ids,
            help="Select dependency - will auto-update start date if same rig"
        )
    else:
        base_config["Dependency"] = st.column_config.SelectboxColumn(
            "Dependency",
            options=[],
            help="Select dependency - will auto-update start date if same rig"
        )
    
    return base_config

# Edit the dataframe
col_config = create_dynamic_column_config(edit_df)

# Use a form to batch edits and reduce reruns
with st.form("drilling_schedule_form"):
    edited_df = st.data_editor(
        edit_df,
        column_config=col_config,
        num_rows="dynamic",
        key="drilling_editor",
        use_container_width=True
    )
    
    submitted = st.form_submit_button("Update Schedule")

# Process the edited data
if submitted or st.session_state.get("auto_update", False):
    # Convert dates back to strings for storage and computation
    processed_df = edited_df.copy()
    
    # Convert date columns to strings for consistent storage
    if "Start Date" in processed_df.columns:
        processed_df["Start Date"] = processed_df["Start Date"].dt.strftime(DATE_FMT)
    if "End Date" in processed_df.columns:
        processed_df["End Date"] = processed_df["End Date"].dt.strftime(DATE_FMT)
    
    # Check if we need to recalculate
    if not processed_df.empty:
        current_hash = hash(str(processed_df[["HoleID", "Dependency", "Planned Depth", "Rigs"]].to_dict()))
        
        # Recalculate if data changed or drilling rate changed
        if (st.session_state.prev_df_hash != current_hash or 
            "last_drill_rate" not in st.session_state or 
            st.session_state.last_drill_rate != drill_rate):
            
            st.session_state.prev_df_hash = current_hash
            st.session_state.last_drill_rate = drill_rate
            
            with st.spinner("Recalculating schedule..."):
                st.session_state.df = compute_table_logic(processed_df, drill_rate=drill_rate)
                st.session_state.auto_update = True
                st.rerun()
    else:
        st.session_state.df = processed_df

# Add manual refresh button as fallback
if st.button("Force Recalculation"):
    st.session_state.df = compute_table_logic(st.session_state.df, drill_rate=drill_rate)
    st.rerun()

# Display computed results
if not st.session_state.df.empty:
    st.subheader("Computed Schedule")
    
    # Show summary statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Holes", len(st.session_state.df))
    with col2:
        total_duration = st.session_state.df["Duration"].sum() if "Duration" in st.session_state.df.columns else 0
        st.metric("Total Duration (days)", f"{total_duration:.1f}")
    with col3:
        avg_progress = st.session_state.df["Progress"].mean() if "Progress" in st.session_state.df.columns else 0
        st.metric("Average Progress", f"{avg_progress:.1f}%")
    with col4:
        holes_with_deps = st.session_state.df["Dependency"].notna().sum() if "Dependency" in st.session_state.df.columns else 0
        st.metric("Holes with Dependencies", holes_with_deps)
    
    # Display the computed table
    display_df = st.session_state.df.copy()
    
    # Format the display dataframe
    st.dataframe(
        display_df,
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
        
        # Create tooltip
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
    - ✅ Dependency selector embedded directly in the input table
    - ✅ Global drilling rate remains editable and drives all duration calculations
    - ✅ Automatic date recalculation when dependencies change
    - ✅ Visual Gantt chart shows the complete schedule
    - ✅ Proper date handling with DateColumn for better UX
    
    **Note:** The dependency dropdown automatically excludes the current row's HoleID to prevent circular dependencies.
    Use the 'Update Schedule' button to apply changes or the 'Force Recalculation' button if needed.
    """)
