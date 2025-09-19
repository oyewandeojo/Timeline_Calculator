import streamlit as st
import plotly.figure_factory as ff
import datetime

st.title("Timeline Calculator")

st.markdown(
    """
    <span style='background-color:lightgray; font-style:italic;'>
    Against a set cut-off date (in this case when assay results are returned and invoiced).
    </span><br>
    <span style='background-color:lightgray; font-style:italic;'>
    The core samples have to be shipped by the date specified below if all the editable variables below are met.
    </span><br>
    <span style='background-color:lightgray; font-style:italic;'>
    The shipment date is highlighted by colour (green means greater than 3 weeks from today; yellow within the next 3 weeks and red means the date has passed).
    </span>
    """,
    unsafe_allow_html=True
)

# --------------------------
# Stage colors for Gantt chart
# --------------------------
stage_colors = {
    "Shipment→Split Gap": "#ADD8E6",  # lightblue
    "Splitting": "#FFA500",            # orange
    "Split→Lab Gap": "#FFFF00",        # yellow
    "Lab": "#008000"                    # green
}

# --------------------------
# Individual inputs (vertical)
# --------------------------
cutoff_date = st.text_input("Cut-off Date", "2025-12-01")
core_depth = st.number_input("Core Footage (ft)", value=5000, step=1)

# --------------------------
# Horizontal row for the rest
# --------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    shipment_gap = st.number_input("Shipment→Split Gap (days)", value=2, step=1)

with col2:
    splitting_rate = st.slider("Splitting Rate (ft/day)", min_value=100, max_value=200, value=150, step=1)

with col3:
    split_to_lab_gap = st.number_input("Split→Lab Gap (days)", value=3, step=1)

with col4:
    lab_days = st.slider("Lab Processing Time (days)", min_value=30, max_value=70, value=50, step=1)

# --------------------------
# Function to create Gantt data and calculate shipment date
# --------------------------
def create_gantt_df(shipment_gap, core_footage, split_rate, split_lab_gap, lab_days, cutoff_date_str):
    try:
        cutoff_date_dt = datetime.datetime.strptime(cutoff_date_str, "%Y-%m-%d")
    except:
        cutoff_date_dt = datetime.datetime.today() + datetime.timedelta(days=100)

    split_days = core_footage / split_rate
    stages = [
        ("Shipment→Split Gap", shipment_gap),
        ("Splitting", split_days),
        ("Split→Lab Gap", split_lab_gap),
        ("Lab", lab_days)
    ]

    total_days = sum(duration for _, duration in stages)
    shipment_date = cutoff_date_dt - datetime.timedelta(days=total_days)

    df = []
    for idx, (task, duration) in enumerate(stages):
        if idx == 0:
            start = shipment_date
        else:
            start = prev_end + datetime.timedelta(days=1)
        end = start + datetime.timedelta(days=duration - 1)
        prev_end = end
        df.append({
            "Task": task,
            "Start": start.strftime("%Y-%m-%d"),
            "Finish": end.strftime("%Y-%m-%d"),
            "Resource": stage_colors[task]
        })
    return df, shipment_date

# --------------------------
# Generate Gantt chart
# --------------------------
df, shipment_date = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
fig.update_layout(title="Stepped Sequential Gantt Chart", height=400)

st.plotly_chart(fig)

# --------------------------
# Highlight shipment date based on proximity to today
# --------------------------
today = datetime.datetime.today()
if shipment_date < today:
    color = "red"
elif today <= shipment_date <= today + datetime.timedelta(weeks=3):
    color = "yellow"
else:
    color = "green"

st.markdown(
    f"<span style='background-color:{color}; padding:5px; font-weight:bold'>Shipment Date: {shipment_date.strftime('%Y-%m-%d')}</span>", 
    unsafe_allow_html=True
)













