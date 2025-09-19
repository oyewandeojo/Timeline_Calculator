import panel as pn
import plotly.figure_factory as ff
import datetime

pn.extension('plotly')

stage_colors = ["lightblue", "orange", "yellow", "green"]

# --------------------------
# Panel widgets
# --------------------------
cutoff_date_input = pn.widgets.TextInput(name="Cut-off Date", value="2025-12-01")
core_depth_input = pn.widgets.IntInput(name="Core Depth (ft)", value=5000, step=1)
shipment_gap_input = pn.widgets.IntInput(name="Shipment→Split Gap (days)", value=2, step=1)
splitting_rate_input = pn.widgets.IntInput(name="Splitting Rate (ft/day)", value=150, step=1)
split_to_lab_gap_input = pn.widgets.IntInput(name="Split→Lab Gap (days)", value=3, step=1)
lab_days_input = pn.widgets.IntInput(name="Lab Processing Time (days)", value=50, step=1)

# --------------------------
# Functions to create Gantt chart
# --------------------------
def create_gantt_df(shipment_gap, core_depth, split_rate, split_lab_gap, lab_days, cutoff_date_str):
    try:
        cutoff_date = datetime.datetime.strptime(cutoff_date_str, "%Y-%m-%d")
    except:
        cutoff_date = datetime.datetime.today() + datetime.timedelta(days=100)

    split_days = core_depth / split_rate
    stages = [
        ("Shipment→Split Gap", shipment_gap),
        ("Splitting", split_days),
        ("Split→Lab Gap", split_lab_gap),
        ("Lab", lab_days)
    ]

    total_days = sum(duration for _, duration in stages)
    shipment_date = cutoff_date - datetime.timedelta(days=total_days)

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

def update_gantt(cutoff_date, core_depth, shipment_gap, splitting_rate, split_to_lab_gap, lab_days):
    df = create_gantt_df(shipment_gap, core_depth, splitting_rate, split_to_lab_gap, lab_days, cutoff_date)
    fig = ff.create_gantt(df, index_col='Resource', show_colorbar=False, showgrid_x=True, showgrid_y=True)
    fig.update_layout(title="Stepped Sequential Gantt Chart", height=400)
    return fig

# --------------------------
# Panel layout
# --------------------------
widgets = pn.Column(
    cutoff_date_input,
    core_depth_input,
    shipment_gap_input,
    splitting_rate_input,
    split_to_lab_gap_input,
    lab_days_input,
    width=300
)

gantt_pane = pn.bind(
    update_gantt,
    cutoff_date=cutoff_date_input,
    core_depth=core_depth_input,
    shipment_gap=shipment_gap_input,
    splitting_rate=splitting_rate_input,
    split_to_lab_gap=split_to_lab_gap_input,
    lab_days=lab_days_input
)

layout = pn.Row(
    widgets,
    pn.Column(pn.pane.Plotly(gantt_pane, sizing_mode='stretch_width'))
)

# --------------------------
# Crucial for Hugging Face Spaces
# --------------------------
layout.servable()