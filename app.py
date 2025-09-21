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
# Helper: add business days (Mon-Fri only)
# --------------------------
def add_business_days(start_date, business_days):
    current = start_date
    days_added = 0
    while days_added < business_days:
        current += datetime.timedelta(days=1)
        if current.weekday() < 5:  # 0 = Monday, 6 = Sunday
            days_added += 1
    return current

# --------------------------
# Create gantt dataframe
# --------------------------
def create_gantt_df(shipment_gap, core_depth, split_rate, split_lab_gap, lab_days, cutoff_date_str):
    try:
        cutoff_date = datetime.datetime.strptime(cutoff_date_str, "%Y-%m-%d")
    except:
        cutoff_date = datetime.datetime.today() + datetime.timedelta(days=100)

    # Workweek-based durations
    split_days = int(core_depth / split_rate)  # splitting days in workdays

    stages = [
        ("Shipment→Split Gap", shipment_gap, "workweek"),
        ("Splitting", split_days, "workweek"),
        ("Split→Lab Gap", split_lab_gap, "workweek"),
        ("Lab", lab_days, "calendar")
    ]

    # Calculate backwards
    df = []
    end = cutoff_date
    for task, duration, mode in reversed(stages):
        if mode == "calendar":
            start = end - datetime.timedelta(days=duration - 1)
        else:  # workweek
            start = end
            for _ in range(duration - 1):
                start -= datetime.timedelta(days=1)
                while start.weekday() >= 5:  # skip weekends
                    start -= datetime.timedelta(days=1)
        df.append({
            "Task": task,
            "Start": start.strftime("%Y-%m-%d"),
            "Finish": end.strftime("%Y-%m-%d"),
            "Resource": stage_colors[task]
        })
        end = start - datetime.timedelta(days=1)  # next stage ends the day before this stage starts

    return list(reversed(df))

# --------------------------
# Gantt chart function
# --------------------------
def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
    df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
    fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
    fig.update_layout(title="Stepped Sequential Gantt Chart", height=400)
    return fig
