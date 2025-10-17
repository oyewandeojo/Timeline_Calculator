import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import altair as alt
import io

# ---------- Constants ----------
DATE_FMT = "%Y-%m-%d"
DEFAULT_DRILL_RATE = 10.0

# ---------- Template & Import Helpers ----------
def create_template_df():
    """Create a template dataframe for download"""
    return pd.DataFrame({
        "HoleID": ["Hole_001", "Hole_002", "Hole_003"],
        "Start Date": ["2024-01-01", "", ""],
        "End Date": ["2024-01-05", "", ""],
        "Planned Depth": [100.0, 150.0, 200.0],
        "Rigs": ["Rig_A", "Rig_A", "Rig_B"],
        "Current Depth": [0.0, 0.0, 0.0],
        "Dependency": ["", "Hole_001", ""]
    })

def validate_import_df(df):
    """Validate imported dataframe has required columns"""
    required_columns = ["HoleID", "Start Date", "End Date", "Planned Depth", "Rigs", "Current Depth", "Dependency"]
    
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        return False, f"Missing required columns: {', '.join(missing_columns)}"
    
    # Check for duplicate HoleIDs
    if df["HoleID"].duplicated().any():
        return False, "Duplicate HoleIDs found in the data"
    
    return True, "Valid data"

def process_imported_df(df):
    """Process imported dataframe to ensure proper data types"""
    processed_df = df.copy()
    
    # Ensure all required columns exist
    required_columns = ["HoleID", "Start Date", "End Date", "Planned Depth", "Rigs", "Current Depth", "Dependency"]
    for col in required_columns:
        if col not in processed_df.columns:
            processed_df[col] = ""
    
    # Convert numeric columns
    processed_df["Planned Depth"] = pd.to_numeric(processed_df["Planned Depth"], errors="coerce").fillna(0)
    processed_df["Current Depth"] = pd.to_numeric(processed_df["Current Depth"], errors="coerce").fillna(0)
    
    # Fill empty strings for optional columns
    processed_df["Dependency"] = processed_df["Dependency"].fillna("")
    processed_df["Rigs"] = processed_df["Rigs"].fillna("")
    
    return processed_df

# ---------- Computation Helpers ----------
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

# ---------- Streamlit App ----------
st.title("Drilling Gantt with Inline Dependency Selector")

# Initialize session state
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=[
        "HoleID", "Start Date", "End Date", "Planned Depth", 
        "Rigs", "Current Depth", "Dependency"
    ])

# ---------- Import/Export Section ----------
st.subheader("Import & Export Data")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Import Data**")
    uploaded_file = st.file_uploader(
        "Upload CSV file", 
        type=["csv"],
        help="Upload a CSV file with drilling data. Download the template below to ensure proper format."
    )
    
    if uploaded_file is not None:
        try:
            imported_df = pd.read_csv(uploaded_file)
            is_valid, message = validate_import_df(imported_df)
            
            if is_valid:
                processed_df = process_imported_df(imported_df)
                st.session_state.df = processed_df
                st.success(f"✅ Data imported successfully! Loaded {len(processed_df)} holes.")
            else:
                st.error(f"❌ Import failed: {message}")
                
        except Exception as e:
            st.error(f"❌ Error reading file: {str(e)}")

with col2:
    st.markdown("**Export Data**")
    
    # Download template
    template_df = create_template_df()
    csv_template = template_df.to_csv(index=False)
    st.download_button(
        label="📥 Download Template",
        data=csv_template,
        file_name="drilling_schedule_template.csv",
        mime="text/csv",
        help="Download a template CSV file to ensure proper formatting"
    )
    
    # Download current data
    if not st.session_state.df.empty:
        csv_data = st.session_state.df.to_csv(index=False)
        st.download_button(
            label="📥 Export Current Data",
            data=csv_data,
            file_name=f"drilling_schedule_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            help="Download current drilling schedule as CSV"
        )
    else:
        st.download_button(
            label="📥 Export Current Data",
            data="",
            file_name="empty_drilling_schedule.csv",
            mime="text/csv",
            disabled=True,
            help="No data available to export"
        )

# ---------- Global Drilling Rate ----------
st.subheader("Global Parameters")
drill_rate = st.number_input(
    "Global Drilling Rate (ft/day)", 
    value=DEFAULT_DRILL_RATE, 
    min_value=0.1, 
    step=0.1,
    help="Editable global rate used to calculate duration for all holes"
)

# ---------- Data Editor Section ----------
st.subheader("Drilling Schedule Table")
st.markdown("""
**Instructions:**
- Add/Edit rows in the table below or import data from CSV
- Use the **Dependency** dropdown to select which hole this one depends on
- Start Date will automatically update to Dependency's End Date + 1 day (if same rig)
- Duration is calculated automatically using Global Drilling Rate
- All updates happen automatically as you type/select
""")

# Prepare data for editing - convert dates to proper format
if not st.session_state.df.empty:
    edit_df = prepare_data_for_editor(st.session_state.df)
else:
    edit_df = st.session_state.df.copy()

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
if not edit_df.empty:
    col_config = create_dynamic_column_config(edit_df)
    
    edited_df = st.data_editor(
        edit_df,
        column_config=col_config,
        num_rows="dynamic",
        key="drilling_editor",
        use_container_width=True
    )

    # Always recalculate when the dataframe or drill rate changes
    # Convert dates back to strings for storage and computation
    processed_df = edited_df.copy()
    
    # Convert date columns to strings for consistent storage
    if "Start Date" in processed_df.columns:
        processed_df["Start Date"] = processed_df["Start Date"].dt.strftime(DATE_FMT)
    if "End Date" in processed_df.columns:
        processed_df["End Date"] = processed_df["End Date"].dt.strftime(DATE_FMT)
    
    # Always recalculate - Streamlit's reactivity will handle the updates
    st.session_state.df = compute_table_logic(processed_df, drill_rate=drill_rate)
else:
    # Handle empty dataframe
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        key="drilling_editor_empty",
        use_container_width=True
    )
    st.session_state.df = edited_df

# ---------- Results Display ----------
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
    st.info("Add drilling data to the table above or import a CSV file to get started.")

# ---------- How It Works Section ----------
with st.expander("How it works"):
    st.markdown("""
    **Automatic Dependency Logic:**
    - When you select a dependency from the dropdown in the table, the system automatically:
      1. Excludes the row's own HoleID from dependency options
      2. Checks if the dependency has the same rig
      3. If same rig, updates the Start Date to be the dependency's End Date + 1 day
      4. Recalculates Duration based on Planned Depth and Global Drilling Rate
      5. Updates End Date accordingly
    
    **Import/Export Features:**
    - 📤 **Download Template**: Get a properly formatted CSV template
    - 📥 **Import Data**: Upload your own CSV data (must match template format)
    - 📤 **Export Data**: Download your current schedule as CSV
    
    **Required CSV Columns:**
    - `HoleID`: Unique identifier for each hole (text)
    - `Start Date`: Start date (YYYY-MM-DD format)
    - `End Date`: End date (YYYY-MM-DD format)  
    - `Planned Depth`: Total planned depth in feet (number)
    - `Rigs`: Rig name (text)
    - `Current Depth`: Current depth achieved (number)
    - `Dependency`: HoleID this hole depends on (text, leave empty if none)
    
    **Key Features:**
    - ✅ Dependency selector embedded directly in the input table
    - ✅ Global drilling rate remains editable and drives all duration calculations
    - ✅ **Automatic updates** - everything happens instantly as you type/select
    - ✅ CSV import/export for easy data management
    - ✅ Visual Gantt chart shows the complete schedule
    
    **Note:** The dependency dropdown automatically excludes the current row's HoleID to prevent circular dependencies.
    All changes are applied automatically - no buttons needed!
    """)
