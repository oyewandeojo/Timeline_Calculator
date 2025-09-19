import streamlit as st
import plotly.figure_factory as ff
import datetime

st.title("Sequential Gantt Chart")

# --------------------------
# Widgets
# --------------------------
cutoff_date = st.text_input("Cut-off Date", "2025-12-01")
core_depth = st.number_input("Core Depth (ft)", value=5000, step=1)
shipment_gap = st.number_input("Shipment→Split Gap (days)", value=2, step=1)
split_to_lab_gap = st.number_input("Split→Lab Gap (days)", value=3, step=1)

# Sliders for splitting rate and lab processing time
splitting_rate = st.slider("Splitting Rate (ft/day)", min_value=100, max_value=200, value=150, step=1)
lab_days = st.slider("Lab Processing Time (days)", min_value=30, max_value=70, value=50, step=1)

# --------------------------
# Functions
# --------------------------
stage_colors = ["lightblue", "orange", "yellow", "green"]

def create_gantt_df(shipment_gap, core_depth, split_rate, split_lab_gap, lab_days, cutoff_date_str):
    try:
        cutoff_date_dt = datetime.datetime.strptime(cutoff_date_str, "%Y-%m-%d")
    except:
        cutoff_date_dt = datetime.datetime.today() + datetime.timedelta(days=100)

    split_days = core_depth / split_rate
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
            "Resource": stage_colors[idx]
        })
    return df

# --------------------------
# Generate Gantt chart
# --------------------------
df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
fig.update_layout(title="Stepped Sequential Gantt Chart", height=400)

st.plotly_chart(fig)
