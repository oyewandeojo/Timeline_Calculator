import datetime
import streamlit as st
import plotly.figure_factory as ff

# --------------------------
# Stage colors
# --------------------------
stage_colors = {
    "Shipment→Split Gap": "lightblue",
    "Splitting": "orange",
    "Split→Lab Gap": "yellow",
    "Lab": "green"
}

# --------------------------
# Helper: subtract business days (Mon–Fri only)
# --------------------------
def subtract_business_days(end_date, business_days):
    current = end_date
    days_remaining = business_days
    while days_remaining > 0:
        current -= datetime.timedelta(days=1)
        if current.weekday() < 5:  # Mon–Fri
            days_remaining -= 1
    return current

# --------------------------
# Create gantt dataframe
# --------------------------
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

# --------------------------
# Gantt chart function
# --------------------------
def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
    df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
    fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
    fig.update_layout(title="Gantt Chart", height=300)
    return fig, df[0]["Start"]

# --------------------------
# Streamlit Layout
# --------------------------
st.title("Timeline Calculator")

st.markdown(
    "<div style='background-color:lightgray; padding:8px; font-style:italic;'>"
    "Against a set cut-off date (in this case when assay results are returned and invoiced).<br>"
    "The core samples have to be shipped by the date specified below if all the editable variables below are met.<br>"
    "The shipment date is highlighted by colour (green means greater than 3 weeks from today; "
    "yellow within the next 3 weeks and red means the date has passed)."
    "</div>",
    unsafe_allow_html=True
)

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
    splitting_rate = st.slider("Splitting Rate (ft/day)", 50, 500, 150, step=10)
with col3:
    split_to_lab_gap = st.number_input("Split→Lab Gap (days)", value=3, step=1)
with col4:
    lab_days = st.slider("Lab Processing Time (days)", 10, 100, 50, step=5)

# Update chart
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
    f"<div style='background-color:{color}; padding:10px; text-align:center; font-size:14px;'>"
    f"<b>Shipment Date: {shipment_dt.strftime('%Y-%m-%d')}</b>"
    "</div>",
    unsafe_allow_html=True
)




