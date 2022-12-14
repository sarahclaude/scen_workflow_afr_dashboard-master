# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------------------------------------------------
# Climate information dashboard.
# 
# Plotting functions.
# - time series;
# - table of statistics;
# - map.
#
# Contributors:
# 1. rousseau.yannick@ouranos.ca
# (C) 2021-2022 Ouranos Inc., Canada
# ----------------------------------------------------------------------------------------------------------------------

# External libraries.
import altair as alt
import holoviews as hv
# Do not delete the following import statement (hvplot.pandas), even if it seems unused.
import hvplot.pandas
import math
import matplotlib.colors as colors
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import panel as pn
import plotly.graph_objects as go
import plotly.io as pio
import skill_metrics as sm
import xarray as xr
from bokeh.models import FixedTicker
from descartes import PolygonPatch
from matplotlib.lines import Line2D
from mpl_toolkits.axes_grid1 import make_axes_locatable
from typing import Union, List, Optional

# Dashboard libraries.
import cl_rcp
import cl_stat
import dash_file_utils as dfu
import dash_stats as stats
import dash_utils as du
from cl_constant import const as c
from cl_context import cntx
from cl_rcp import RCP, RCPs
from cl_sim import Sim
from cl_varidx import VarIdx

alt.renderers.enable("default")
pn.extension("vega")
hv.extension("bokeh", logo=False)
pio.renderers.default = "iframe"

MODE_RCP = "rcp"
MODE_SIM = "sim"


def gen_ts(
    df: pd.DataFrame,
    mode: Optional[str] = MODE_RCP
) -> Union[alt.Chart, any, plt.figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a plot of time series.
    
    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    mode: Optional[str]
        If mode == MODE_RCP: show curves and envelopes.
        If mode == MODE_SIM: show curves only.

    Returns
    -------
    Union[alt.Chart, any, plt.figure] :
        Plot of time series.


    Logic related to line width (variable "line_alpha").

    wf_plot | delta | simulation |   ref |   rcp
    -----+-------+------------+-------+------
    rcp  |   no  |      blank | thick | thick
    sim  |   no  |      blank | thick |  thin
    rcp  |  yes  |      blank |  thin | thick
    sim  |  yes  |      blank |  thin |  thin
    rcp  |   no  |  specified | thick | thick
    sim  |   no  |  specified | thick | thick
    rcp  |  yes  |  specified |  thin | thick
    sim  |  yes  |  specified |  thin | thick

    --------------------------------------------------------------------------------------------------------------------
    """

    # Extract minimum and maximum x-values (round to lower and upper decades).
    x_min = math.floor(min(df["year"]) / 10) * 10
    x_max = math.ceil(max(df["year"]) / 10) * 10

    # Extract minimum and maximum y-values (to the right of column 'year').
    list(df.columns).index("year")
    first_col_index = (2 if mode == MODE_SIM else 1) + list(df.columns).index("year")
    y_min = df.iloc[:, first_col_index:].min().min()
    y_max = df.iloc[:, first_col_index:].max().max()

    # Plot components.
    x_label = "Ann??e"
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    y_label = ("??" if delta_code == "True" else "") + cntx.varidx.label

    # Assign zero to all years (not only to the refrence period).
    if cntx.delta.code == "True":
        df[c.REF] = 0

    # If there is a single row, add a second line to allow time series to work.
    if len(df) == 1:
        df = df.append(df.iloc[[0]], ignore_index=True)
        x_min = df["year"][1]
        x_max = x_min + 1
        df["year"][1] = x_max

    # Subset columns and rename columns.
    df_subset = df
    if mode == MODE_SIM:

        # Emissions scenarios and simulations are not specified.
        if cntx.code == c.PLATFORM_SCRIPT:
            df_subset = df

        else:

            # RCP specified.
            rcp_code = cntx.rcp.code
            if rcp_code not in ["", c.RCPXX]:
                df_subset = df[["year", "ref"]]
                for column in df.columns:
                    if rcp_code in column:
                        df_subset[column] = df[column]

            # Simulation specified.
            if cntx.sim.code not in ["", c.SIMXX]:
                df_subset = df[["year", "ref", cntx.sim.code]]

    # Combine RCPs.
    if (cntx.view.code == c.VIEW_TS_BIAS) and (cntx.rcp.code in ["", c.RCPXX]) and (mode == MODE_RCP):

        for stat_code in ["lower", "middle", "upper"]:

            # Identify the columns associated with the current statistic.
            columns = []
            for column in df_subset.columns:
                if stat_code in column:
                    columns.append(column)

            # Calculate overall values.
            if stat_code == "lower":
                df_subset[c.RCPXX + "_" + stat_code] = df_subset[columns].min(axis=1)
            elif stat_code == "middle":
                df_subset[c.RCPXX + "_" + stat_code] = df_subset[columns].mean(axis=1)
            elif stat_code == "upper":
                df_subset[c.RCPXX + "_" + stat_code] = df_subset[columns].max(axis=1)

            # Delete columns.
            df_subset.drop(columns, axis=1, inplace=True)

    # Generate plot.
    if cntx.lib.code == c.LIB_MAT:
        ts = gen_ts_mat(df_subset, x_label, y_label, [x_min, x_max], [y_min, y_max], mode)
    elif cntx.lib.code == c.LIB_HV:
        ts = gen_ts_hv(df_subset, x_label, y_label, [y_min, y_max], mode)
    else:
        ts = gen_ts_alt(df_subset, x_label, y_label, [y_min, y_max], mode)
        
    return ts


def gen_ts_alt(
    df: pd.DataFrame,
    x_label: str,
    y_label: str,
    y_range: List[float],
    mode: str
) -> alt.Chart:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a plot of time series using altair.
    
    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    x_label: str
        X-label.
    y_label: str
        Y-label.
    y_range: List[str]
        Range of y_values to display [{y_min}, {y_max}].
        Dataframe.
    mode: str
        If mode == MODE_RCP: show curves and envelopes.
        If mode == MODE_SIM: show curves only.

    Returns
    -------
    alt.Chart :
        Plot of time series.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Move reference RCP at the end of the list.
    if (cntx.view.code == c.VIEW_TS) or (cntx.rcp.code not in ["", c.RCPXX]):
        rcps = cntx.rcps.copy()
        rcps.remove(c.REF, inplace=True)
    else:
        rcps = RCPs([c.RCPXX])
    rcps.add(RCP(c.REF), inplace=True)

    # Plot components.
    x_axis = alt.Axis(title=x_label, format="d")
    y_axis = alt.Axis(title=y_label, format="d")
    y_scale = alt.Scale(domain=y_range)
    color_l = rcps.color_l
    col_legend = alt.Legend(title="", orient="top-left", direction="horizontal", symbolType="stroke")
    if cntx.view.code == c.VIEW_TS_BIAS:
        for i in range(len(color_l)):
            if color_l[i] != RCP(c.REF).color:
                color_l[i] = "darkgrey"
    col_scale = alt.Scale(range=color_l, domain=rcps.desc_l)

    # Add layers.
    plot = None
    for item in ["area", "curve"]:

        for rcp in rcps.items:

            cond_ts      = (cntx.view.code == c.VIEW_TS) and (cntx.rcp.code not in ["", c.RCPXX])
            cond_ts_bias = (cntx.view.code == c.VIEW_TS_BIAS) and (cntx.rcp.code != "")
            if ((item == "area") and (rcp.is_ref or (mode == MODE_SIM))) or \
               ((cond_ts or cond_ts_bias) and (rcp.code not in [cntx.rcp.code, c.REF])):
                continue

            rcp_desc = rcp.desc.replace(dict(cl_rcp.code_props())[c.RCPXX][0], "Simulation(s)")

            # Subset columns.
            df_rcp = pd.DataFrame()
            df_rcp["Ann??e"] = df["year"]
            df_rcp["Sc??nario"] = [rcp.desc] * len(df)
            if rcp.is_ref:
                df_rcp["Moy"] = df[c.REF]
            else:
                if mode == MODE_RCP:
                    df_rcp["Min"] = df[rcp.code + "_lower"]
                    df_rcp["Moy"] = df[rcp.code + "_middle"]
                    df_rcp["Max"] = df[rcp.code + "_upper"]
                else:
                    for column in list(df.columns):
                        if (rcp.code in column) or ((rcp.code == c.RCPXX) and ("rcp" in column)):
                            df_rcp[column] = df[column]

            # Round values and set tooltip.
            n_dec = cntx.varidx.precision
            tooltip = []
            if "Moy" in df_rcp:
                column = "Moyenne"
                if ("Min" not in list(df_rcp.columns)) and ("Max" not in list(df_rcp.columns)):
                    column = "Valeur"
                df_rcp[column] = np.array(du.round_values(df_rcp["Moy"], n_dec)).astype(float)
                tooltip = [column]
            if "Min" in df_rcp:
                df_rcp["Minimum"] = np.array(du.round_values(df_rcp["Min"], n_dec)).astype(float)
                df_rcp["Maximum"] = np.array(du.round_values(df_rcp["Max"], n_dec)).astype(float)
                tooltip = ["Minimum", "Moyenne", "Maximum"]
            if mode == MODE_SIM:
                excl_l = ["Sc??nario", "Ann??e", "Moy", "Min", "Max"]
                tooltip = [e for e in list(df_rcp.columns) if e not in excl_l]
                tooltip.sort()
            tooltip = ["Ann??e", "Sc??nario"] + tooltip

            # Draw area.
            if (item == "area") and (mode == MODE_RCP):

                # Opacity of area.
                area_alpha = 0.3

                # Draw area.
                area = alt.Chart(df_rcp).mark_area(opacity=area_alpha, text=rcp_desc).encode(
                    x=alt.X("Ann??e", axis=x_axis),
                    y=alt.Y("Min", axis=y_axis, scale=y_scale),
                    y2="Max",
                    color=alt.Color("Sc??nario", scale=col_scale, legend=col_legend)
                )
                plot = area if plot is None else (plot + area)
            
            # Draw curve(s).
            elif item == "curve":

                # Line width (see comment in the header of 'gen_ts').
                if rcp.is_ref or ((mode == MODE_RCP) or ((mode == MODE_SIM) and (cntx.sim.code not in ["", c.SIMXX]))):
                    line_alpha = 2.0
                else:
                    line_alpha = 1.0

                # Columns to plot.
                columns = []
                if "Valeur" in list(df_rcp.columns):
                    columns.append("Valeur")
                if ("Moy" in list(df_rcp.columns)) and ("Valeur" not in list(df_rcp.columns)):
                    columns.append("Moy")
                if mode == MODE_SIM:
                    for column in list(df_rcp.columns):
                        if ("Ann??e" not in column) and ("Sc??nario" not in column):
                            columns.append(column)

                # Draw curves.
                for column in columns:
                    if rcp.is_ref:
                        curve = alt.Chart(df_rcp).\
                            mark_line(size=line_alpha, text=rcp_desc, color=rcp.color).encode(
                            x=alt.X("Ann??e", axis=x_axis),
                            y=alt.Y(column, axis=y_axis, scale=y_scale),
                            color=alt.Color("Sc??nario", scale=col_scale, legend=col_legend),
                            tooltip=tooltip
                        ).interactive()
                    else:
                        curve = alt.Chart(df_rcp).mark_line(size=line_alpha, text=rcp_desc).encode(
                            x=alt.X("Ann??e", axis=x_axis),
                            y=alt.Y(column, axis=y_axis, scale=y_scale),
                            color=alt.Color("Sc??nario", scale=col_scale, legend=col_legend),
                            tooltip=tooltip
                        ).interactive()
                    plot = curve if plot is None else (plot + curve)

    # Adjust size and title
    height = 362 if cntx.code == c.PLATFORM_STREAMLIT else 300
    title = alt.TitleParams([plot_title(), plot_code()])
    plot = plot.configure_axis(grid=False).properties(height=height, width=650, title=title).\
        configure_title(offset=0, orient="top", anchor="start")

    return plot


def gen_ts_hv(
    df: pd.DataFrame,
    x_label: str,
    y_label: str,
    y_range: List[float],
    mode: str
) -> any:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a plot of time series using hvplot.
    
    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    x_label: str
        X-label.
    y_label: str
        Y-label.
    y_range: List[str]
        Range of y_values to display [{y_min}, {y_max}].
        Dataframe.
    mode: str
        If mode == MODE_RCP: show curves and envelopes.
        If mode == MODE_SIM: show curves only.

    Returns
    -------
    any :
        Plot of time series.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Move reference RCP at the end of the list.
    if (cntx.view.code == c.VIEW_TS) or (cntx.rcp.code not in ["", c.RCPXX]):
        rcps = cntx.rcps.copy()
        rcps.remove(c.REF, inplace=True)
    else:
        rcps = cl_rcp.RCPs([c.RCPXX])
    rcps.add(cl_rcp.RCP(c.REF), inplace=True)

    # Loop through RCPs.
    plot = None
    for item in ["area", "curve"]:

        for rcp in rcps.items:

            cond_ts      = (cntx.view.code == c.VIEW_TS) and (cntx.rcp.code not in ["", c.RCPXX])
            cond_ts_bias = (cntx.view.code == c.VIEW_TS_BIAS) and (cntx.rcp.code != "")
            if (item == "area") and (rcp.is_ref or (mode == MODE_SIM)) or \
               ((cond_ts or cond_ts_bias) and (rcp.code not in [cntx.rcp.code, c.REF])):
                continue

            # Color (area and curve).
            color = rcp.color if (cntx.view.code == c.VIEW_TS) or (rcp.code == c.REF) else "darkgrey"

            # Subset and rename columns.
            df_rcp = pd.DataFrame()
            df_rcp["Ann??e"] = df["year"]
            df_rcp["Sc??nario"] = [rcp.desc] * len(df_rcp)
            if rcp.is_ref:
                df_rcp["Moyenne"] = df[c.REF]
            else:
                if mode == MODE_RCP:
                    if str(rcp.code + "_lower") in df.columns:
                        df_rcp["Minimum"] = df[str(rcp.code + "_lower")]
                    if str(rcp.code + "_middle") in df.columns:
                        df_rcp["Moyenne"] = df[str(rcp.code + "_middle")]
                    if str(rcp.code + "_upper") in df.columns:
                        df_rcp["Maximum"] = df[str(rcp.code + "_upper")]
                else:
                    for column in list(df.columns):
                        if (rcp.code in column) or ((rcp.code == c.RCPXX) and ("rcp" in column)):
                            df_rcp[Sim(column).desc] = df[column]

            # Round values and set tooltip.
            n_dec = cntx.varidx.precision
            tooltip = []
            if "Moyenne" in df_rcp:
                column = "Moyenne"
                if ("Minimum" not in df_rcp.columns) and ("Maximum" not in df_rcp.columns):
                    column = "Valeur"
                df_rcp[column] = np.array(du.round_values(df_rcp["Moyenne"], n_dec)).astype(float)
                tooltip = [column]
            if "Minimum" in df_rcp:
                df_rcp["Minimum"] = np.array(du.round_values(df_rcp["Minimum"], n_dec)).astype(float)
                df_rcp["Maximum"] = np.array(du.round_values(df_rcp["Maximum"], n_dec)).astype(float)
                tooltip = ["Minimum", "Moyenne", "Maximum"]
            if mode == MODE_SIM:
                excl_l = ["Sc??nario", "Ann??e", "Moyenne", "Minimum", "Maximum"]
                tooltip = [e for e in list(df_rcp.columns) if e not in excl_l]
                tooltip.sort()
            tooltip = ["Ann??e", "Sc??nario"] + tooltip

            # Draw area.
            if item == "area":

                # Opacity of area.
                area_alpha = 0.3

                # Draw area.
                area = df_rcp.hvplot.area(x="Ann??e", y="Minimum", y2="Maximum", ylim=y_range,
                                          color=color, alpha=area_alpha, line_alpha=0)
                plot = area if plot is None else plot * area

            # Draw curve(s).
            elif item == "curve":

                # Line width (see comment in the header of 'gen_ts').
                if rcp.is_ref or ((mode == MODE_RCP) or ((mode == MODE_SIM) and (cntx.sim.code not in ["", c.SIMXX]))):
                    line_alpha = 1.0
                else:
                    line_alpha = 0.3

                # Columns to plot.
                columns = []
                if "Valeur" in df_rcp.columns:
                    columns.append("Valeur")
                if ("Moyenne" in df_rcp.columns) and ("Valeur" not in df_rcp.columns):
                    columns.append("Moyenne")
                if mode == MODE_SIM:
                    for column in list(df_rcp.columns):
                        if ("Ann??e" not in column) and ("Sc??nario" not in column):
                            columns.append(column)

                # Draw curves.
                for column in columns:
                    desc = rcp.desc.replace(dict(cl_rcp.code_props())[c.RCPXX][0], "Simulation(s)")
                    curve = df_rcp.hvplot.line(x="Ann??e", y=column, ylim=y_range, color=color,
                                               line_alpha=line_alpha, label=desc, hover_cols=tooltip)
                    plot = curve if plot is None else plot * curve

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plot = plot.opts(hv.opts.Overlay(title=title))

    # Adjust size and add legend.
    try:
        plot = plot.opts(legend_position="top_left", legend_opts={"click_policy": "hide", "orientation": "horizontal"},
                         frame_height=300, frame_width=645, border_line_alpha=0.0, background_fill_alpha=0.0,
                         xlabel=x_label, ylabel=y_label)
    except ValueError:
        pass

    return plot


def gen_ts_mat(
    df: pd.DataFrame,
    x_label: str,
    y_label: str,
    x_range: List[float],
    y_range: List[float],
    mode: str
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a plot of time series using matplotlib.
    
    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    x_label: str
        X-label.
    y_label: str
        Y-label.
    x_range: List[float]
        Range of x_values to display [{x_min}, {x_max}].
    y_range: List[float]
        Range of y_values to display [{y_min}, {y_max}].
    mode: str
        If mode == MODE_RCP: show curves and envelopes.
        If mode == MODE_SIM: show curves only.

    Returns
    -------
    plt.Figure :
        Plot of time series.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Font size.
    fs        = 9 if cntx.code == c.PLATFORM_STREAMLIT else 10
    fs_title  = fs + 1
    fs_labels = fs
    fs_ticks  = fs

    # Initialize figure and axes.
    if c.PLATFORM_STREAMLIT in cntx.code:
        fig = plt.figure(figsize=(9, 4.4), dpi=cntx.dpi)
    else:
        dpi = cntx.dpi if c.PLATFORM_JUPYTER in cntx.code else None
        fig = plt.figure(figsize=(10.6, 4.8), dpi=dpi)
        plt.subplots_adjust(top=0.90, bottom=0.10, left=0.09, right=0.98, hspace=0.0, wspace=0.0)
    specs = gridspec.GridSpec(ncols=1, nrows=1, figure=fig)
    ax = fig.add_subplot(specs[:])

    # Format.
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.tick_params(axis="x", labelsize=fs_ticks, length=5)
    ax.tick_params(axis="y", labelsize=fs_ticks, length=5)
    ax.set_xticks(range(int(x_range[0]), int(x_range[1]) + 10, 10), minor=False)
    ax.set_xticks(range(int(x_range[0]), int(x_range[1]) + 5, 5), minor=True)
    plt.xlim(x_range[0], x_range[1])
    if not np.isnan(y_range[0]) and not np.isnan(y_range[1]):
        plt.ylim(y_range[0], y_range[1])

    # Move reference RCP at the end of the list.
    if (cntx.view.code == c.VIEW_TS) or (cntx.rcp.code not in ["", c.RCPXX]):
        rcps = cntx.rcps.copy()
        rcps.remove(c.REF, inplace=True)
    else:
        rcps = cl_rcp.RCPs([c.RCPXX])
    rcps.add(c.REF, inplace=True)

    # Loop through RCPs.
    leg_labels = []
    leg_lines = []
    for rcp in rcps.items:

        cond_ts = (cntx.view.code == c.VIEW_TS) and (cntx.rcp.code not in ["", c.RCPXX])
        cond_ts_bias = (cntx.view.code == c.VIEW_TS_BIAS) and (cntx.rcp.code != "")
        if (cond_ts or cond_ts_bias) and (rcp.code not in [cntx.rcp.code, c.REF]):
            continue

        # Color (area and curve).
        color = rcp.color if (cntx.view.code == c.VIEW_TS) or (rcp.code == c.REF) else "darkgrey"

        # Subset and rename columns.
        df_year = df.year
        df_rcp = pd.DataFrame()
        if rcp.is_ref:
            df_rcp["Moy"] = df[c.REF]
        else:
            if mode == MODE_RCP:
                if str(rcp.code + "_lower") in df.columns:
                    df_rcp["Min"] = df[str(rcp.code + "_lower")]
                if str(rcp.code + "_middle") in df.columns:
                    df_rcp["Moy"] = df[str(rcp.code + "_middle")]
                if str(rcp.code + "_upper") in df.columns:
                    df_rcp["Max"] = df[str(rcp.code + "_upper")]
            else:
                for column in df.columns:
                    if (rcp.code in column) or ((rcp.code == c.RCPXX) and ("rcp" in column)):
                        df_rcp[Sim(column).desc] = df[column]

        # Skip if no data is available for this RCP.
        if len(df_rcp) == 0:
            continue

        # Opacity of area.
        alpha = 0.3

        # Line width (see comment in the header of 'gen_ts').
        if rcp.is_ref or ((mode == MODE_RCP) or ((mode == MODE_SIM) and (cntx.sim.code not in ["", c.SIMXX]))):
            line_width = 1.5
        else:
            line_width = 1.0

        # Draw area and curves.
        if rcp.is_ref:
            ax.plot(df_year, df_rcp, color=color, linewidth=line_width)
        else:
            if mode == MODE_RCP:
                ax.plot(df_year, df_rcp["Moy"], color=color, linewidth=line_width)
                ax.fill_between(np.array(df_year), df_rcp["Min"], df_rcp["Max"], color=color,
                                alpha=alpha)
            else:
                for i in range(len(df_rcp.columns)):
                    ax.plot(df_year, df_rcp[df_rcp.columns[i]], color=color, linewidth=line_width)
        
        # Collect legend label and line.
        desc = rcp.desc.replace(dict(cl_rcp.code_props())[c.RCPXX][0], "Simulation(s)")
        leg_labels.append(desc)
        leg_lines.append(Line2D([0], [0], color=color, lw=2))

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plt.title(title, loc="left", fontweight="bold", fontsize=fs_title)

    # Legend.
    ax.legend(leg_lines, leg_labels, loc="upper left", ncol=len(leg_labels), mode="expland", frameon=False,
              fontsize=fs_labels)

    plt.close(fig)
    
    return fig


def gen_tbl(
) -> Union[pd.DataFrame, go.Figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a table.

    Returns
    -------
    Union[pd.DataFrame, go.Figure] :
        Dataframe or figure.
    --------------------------------------------------------------------------------------------------------------------
    """
    
    # Load data.
    df = pd.DataFrame(du.load_data())

    # List of statistics (in a column).
    stat_l, stat_desc_l = [], []
    for code in [c.STAT_MIN, c.STAT_CENTILE_LOWER, c.STAT_MEDIAN, c.STAT_CENTILE_UPPER, c.STAT_MAX, c.STAT_MEAN]:
        centile = -1
        if code in [c.STAT_MEAN, c.STAT_MIN, c.STAT_MAX]:
            stat_l.append([code, -1])
        elif code == c.STAT_CENTILE_LOWER:
            centile = cntx.opt_tbl_centiles[0]
            stat_l.append([c.STAT_CENTILE, centile])
        elif code == c.STAT_MEDIAN:
            stat_l.append([c.STAT_CENTILE, 50])
        elif code == c.STAT_CENTILE_UPPER:
            centile = cntx.opt_tbl_centiles[len(cntx.opt_tbl_centiles) - 1]
            stat_l.append([c.STAT_CENTILE, centile])
        stat_desc_l.append(cl_stat.code_desc(centile)[code])

    # Initialize resulting dataframe.
    df_res = pd.DataFrame()
    df_res["Statistique"] = stat_desc_l

    # Loop through RCPs.
    columns = []
    for rcp in cntx.rcps.items:

        if rcp.is_ref:
            continue

        # Extract delta.
        delta = 0.0
        if cntx.delta.code == "True":
            delta = float(df[df["rcp"] == c.REF]["val"])

        # Extract statistics.
        vals = []
        for stat in stat_l:
            df_cell = float(df[(df["rcp"] == rcp.code) &
                               (df["hor"] == cntx.hor.code) &
                               (df["stat"] == stat[0]) &
                               (df[c.STAT_CENTILE] == stat[1])]["val"])
            val = df_cell - delta
            vals.append(val)
        df_res[rcp.code] = vals

        # Adjust precision.
        n_dec = cntx.varidx.precision
        for i in range(len(df_res)):
            df_res[rcp.code] = du.round_values(df_res[rcp.code], n_dec)

        columns.append(rcp.desc)

    df_res.columns = [df_res.columns[0]] + columns

    # Add units.
    for column in df_res.columns[1:]:
        df_res[column] = df_res[column].astype(str)
        df_res[column] += (" " if cntx.varidx.unit != "??C" else "") + cntx.varidx.unit

    # Title.
    title = "<b>" + str(plot_title()) + "<br>" + str(plot_code()) + "</b>"

    # In Jupyter Notebook, a dataframe appears nicely.
    if cntx.code == c.PLATFORM_JUPYTER:
        res = df_res.set_index(df_res.columns[0])

    # In Streamlit, a table needs to be formatted.
    else:
        values = []
        for col_name in df_res.columns:
            values.append(df_res[col_name])
        fig = go.Figure(data=[go.Table(
            header=dict(values=list(df_res.columns),
                        line_color="white",
                        fill_color=cntx.col_sb_fill,
                        align="right"),
            cells=dict(values=values,
                       line_color="white",
                       fill_color="white",
                       align="right"))
        ])
        fig.update_layout(
            font=dict(size=15),
            width=700,
            height=210,
            margin=go.layout.Margin(l=0, r=0, b=0, t=50),
            title_text=title,
            title_x=0,
            title_font=dict(size=15)
        )
        res = fig

    return res


def gen_map(
    df: pd.DataFrame,
    z_range: List[float]
) -> Union[any, plt.Figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a heat map using matplotlib.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe (with 2 dimensions: longitude and latitude).
    z_range: List[float]
        Range of values to consider in colorbar.

    Returns
    -------
    Union[any, plt.Figure]
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Find minimum and maximum values (consider all relevant cases).
    z_min = z_range[0]
    z_max = z_range[1]

    # Number of clusters.
    n_cluster = 10 if cntx.opt_map_discrete else 256
    if (z_min < 0) and (z_max > 0):
        n_cluster = n_cluster * 2

    # Adjust minimum and maximum values so that zero is attributed the intermediate color in a scale or
    # use only the positive or negative side of the color scale if the other part is not required.
    if (z_min < 0) and (z_max > 0):
        v_max_abs = max(abs(z_min), abs(z_max))
        v_range = [-v_max_abs, v_max_abs]
    else:
        v_range = [z_min, z_max]

    # Maximum number of decimal places for colorbar ticks.
    n_dec_max = 4

    # Calculate ticks.
    ticks = None
    tick_labels = []
    if cntx.opt_map_discrete:
        ticks = []
        for i in range(n_cluster + 1):
            tick = i / float(n_cluster) * (v_range[1] - v_range[0]) + v_range[0]
            ticks.append(tick)

        # Adjust tick precision.
        tick_labels = adjust_precision(ticks, n_dec_max=n_dec_max, output_type="str")

    # Adjust minimum and maximum values.
    if ticks is not None:
        v_range = [ticks[0], ticks[n_cluster]]

    # Build color map (custom or matplotlib).
    cmap_name = str(get_cmap_name(z_min, z_max))
    hex_l = get_hex_l(cmap_name)
    if hex_l is not None:
        cmap = get_cmap(cmap_name, hex_l, n_cluster)
    else:
        cmap = plt.cm.get_cmap(cmap_name, n_cluster)

    # Generate map.
    if cntx.lib.code == c.LIB_HV:
        fig = gen_map_hv(df, cntx.opt_map_locations, v_range, cmap, ticks, tick_labels)
    else:
        fig = gen_map_mat(df, cntx.opt_map_locations, v_range, cmap, ticks, tick_labels)

    return fig


def gen_map_hv(
    df: pd.DataFrame,
    df_loc: pd.DataFrame,
    v_range: List[float],
    cmap: plt.cm,
    ticks: List[float],
    tick_labels: List[str]
) -> any:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a heat map using hvplot.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    df_loc: pd.DataFrame
        Dataframe.
    v_range: List[float]
        Minimum and maximum values in colorbar.
    cmap: plt.cm
        Color map.
    ticks: List[float]
        Ticks.
    tick_labels: List[str]
        Tick labels.

    Returns
    -------
    any
        Plot.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Font size.
    fs_labels      = 10
    fs_annotations = 8

    # Label.
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    label = ("??" if delta_code == "True" else "") + cntx.varidx.label

    # Rename dimensions.
    df.rename(columns={"val": "Valeur", c.DIM_LONGITUDE: "Longitude", c.DIM_LATITUDE: "Latitude"}, inplace=True)

    # Replace a 1x1 grid by a 9x9 grid with similar values to prevent a big square from appearing on the map.
    square = None
    if len(df) == 1:
        lon = df[c.DIM_LONGITUDE.capitalize()]
        lat = df[c.DIM_LATITUDE.capitalize()]
        val = df["Valeur"]
        lon = ([lon[0] - 0.05] * 3) + ([lon[0]] * 3) + ([lon[0] + 0.05] * 3)
        lat = [lat[0] - 0.05, lat[0], lat[0] + 0.05] * 3
        val = [val[0] + np.random.random_sample() / 1000 for _ in range(9)]
        df = pd.DataFrame({c.DIM_LONGITUDE.capitalize(): lon, c.DIM_LATITUDE.capitalize(): lat, "Valeur": val},
                          index=list(range(9)))

    # Generate mesh.
    heatmap = df.hvplot.heatmap(x="Longitude", y="Latitude", C="Valeur", aspect="equal").\
        opts(cmap=cmap, clim=(v_range[0], v_range[1]), clabel=label)

    # Adjust ticks.
    if cntx.opt_map_discrete:
        ticker = FixedTicker(ticks=ticks)
        ticks_dict = {ticks[i]: tick_labels[i] for i in range(len(ticks))}
        heatmap = heatmap.opts(colorbar_opts={"ticker": ticker, "major_label_overrides": ticks_dict})

    # Draw region boundary.
    bounds = None
    p_bounds = cntx.project.p_bounds
    if ((cntx.project.drive is None) and os.path.exists(p_bounds)) or\
       ((cntx.project.drive is not None) and (cntx.project.p_bounds != "")):
        if cntx.project.drive is None:
            df_curve = dfu.load_geojson(p_bounds, "pandas")
        else:
            df_curve = cntx.project.drive.load_geojson(p_bounds, "pandas")
        x_lim = (min(df_curve[c.DIM_LONGITUDE]), max(df_curve[c.DIM_LONGITUDE]))
        y_lim = (min(df_curve[c.DIM_LATITUDE]), max(df_curve[c.DIM_LATITUDE]))
        bounds =\
            df_curve.hvplot.line(x=c.DIM_LONGITUDE, y=c.DIM_LATITUDE, color="black", alpha=0.7, xlim=x_lim, ylim=y_lim)
    else:
        x_lim = (min(df[c.DIM_LONGITUDE.capitalize()]), max(df[c.DIM_LONGITUDE.capitalize()]))
        y_lim = (min(df[c.DIM_LATITUDE.capitalize()]), max(df[c.DIM_LATITUDE.capitalize()]))

    # Draw locations.
    points = None
    labels = None
    if (df_loc is not None) and (len(df_loc) > 0):
        df_loc = df_loc.copy()
        df_loc.rename(columns={c.DIM_LONGITUDE: "Longitude", c.DIM_LATITUDE: "Latitude", "desc": "Emplacement"},
                      inplace=True)
        points = df_loc.hvplot.scatter(x=c.DIM_LONGITUDE.capitalize(), y=c.DIM_LATITUDE.capitalize(), color="none",
                                       line_color="black", hover_cols=["Emplacement"], xlim=x_lim, ylim=y_lim)
        labels =\
            hv.Labels(data=df_loc, x=c.DIM_LONGITUDE.capitalize(), y=c.DIM_LATITUDE.capitalize(), text="Emplacement").\
            opts(xoffset=0.05, yoffset=0.1, padding=0.2, text_color="black", text_align="left",
                 text_font_style="italic", text_font_size=str(fs_annotations) + "pt")

    # Combine layers.
    plot = heatmap
    if square is not None:
        plot = plot * square
    if bounds is not None:
        plot = plot * bounds
    if points is not None:
        plot = plot * points * labels

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plot = plot.opts(hv.opts.Overlay(title=title))

    # Add legend.
    plot = plot.opts(height=400, width=740, xlabel=c.DIM_LONGITUDE.capitalize() + " (??)",
                     ylabel=c.DIM_LATITUDE.capitalize() + " (??)", fontsize=fs_labels)

    return plot


def gen_map_mat(
    df: pd.DataFrame,
    df_loc: pd.DataFrame,
    v_range: List[float],
    cmap: plt.cm,
    ticks: List[float],
    tick_labels: List[str]
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a heat map using matplotlib.
    
    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    df_loc: pd.DataFrame
        Dataframe.
    v_range: List[float]
        Minimum and maximum values in colorbar.
    cmap: plt.cm
        Color map.
    ticks: List[float]
        Ticks.
    tick_labels: List[str]
        Tick labels.

    Returns
    -------
    plt.Figure
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Font size.
    fs            = 6 if cntx.code == c.PLATFORM_STREAMLIT else 10
    fs_title      = fs + 2
    fs_labels     = fs
    fs_ticks      = fs
    fs_ticks_cbar = fs
    if cntx.delta.code == "True":
        fs_ticks_cbar = fs_ticks_cbar - 1

    # Label.
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    label = ("??" if delta_code == "True" else "") + cntx.varidx.label

    # Initialize figure and axes.
    if c.PLATFORM_STREAMLIT in cntx.code:
        fig = plt.figure(figsize=(9, 4.45), dpi=cntx.dpi)
    else:
        dpi = cntx.dpi if c.PLATFORM_JUPYTER in cntx.code else None
        fig = plt.figure(dpi=dpi)
        width = 10
        w_to_d_ratio = fig.get_figwidth() / fig.get_figheight()
        fig.set_figwidth(width)
        fig.set_figheight(width / w_to_d_ratio)
        plt.subplots_adjust(top=0.98, bottom=0.10, left=0.07, right=0.93, hspace=0.0, wspace=0.0)
    specs = gridspec.GridSpec(ncols=1, nrows=1, figure=fig)
    ax = fig.add_subplot(specs[:], aspect="equal")

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plt.title(title, loc="left", fontweight="bold", fontsize=fs_title)

    # Convert to DataArray.
    df = pd.DataFrame(df, columns=[c.DIM_LONGITUDE, c.DIM_LATITUDE, "val"])
    df = df.sort_values(by=[c.DIM_LATITUDE, c.DIM_LONGITUDE])
    lat = list(set(df[c.DIM_LATITUDE]))
    lat.sort()
    lon = list(set(df[c.DIM_LONGITUDE]))
    lon.sort()
    val = list(df["val"])
    single_cell = (len(lon) == 1) and (len(lat) == 1)

    # Replace a 1x1 grid by a 9x9 grid with similar values to enable the colorbar and show something on the map.
    if single_cell:
        lat = [lat[0] - 0.05, lat[0], lat[0] + 0.05]
        lon = [lon[0] - 0.05, lon[0], lon[0] + 0.05]
        val = [val[0] + np.random.random_sample() / 1000 for _ in range(9)]

    # Assemble DataArray.
    arr = np.reshape(val, (len(lat), len(lon)))
    da = xr.DataArray(data=arr, dims=[c.DIM_LATITUDE, c.DIM_LONGITUDE],
                      coords=[(c.DIM_LATITUDE, lat), (c.DIM_LONGITUDE, lon)])

    # Generate mesh.
    cbar_ax = make_axes_locatable(ax).append_axes("right", size="5%", pad=0.05)
    da.plot.pcolormesh(cbar_ax=cbar_ax, add_colorbar=True, add_labels=True,
                       ax=ax, cbar_kwargs=dict(orientation="vertical", pad=0.05, label=label, ticks=ticks),
                       cmap=cmap, vmin=v_range[0], vmax=v_range[1])

    # Format.
    ax.set_xlabel("Longitude (??)", fontsize=fs_labels)
    ax.set_ylabel("Latitude (??)", fontsize=fs_labels)
    ax.tick_params(axis="x", labelsize=fs_ticks, length=5, rotation=90)
    ax.tick_params(axis="y", labelsize=fs_ticks, length=5)
    ax.set_xticks(ax.get_xticks(), minor=True)
    ax.set_yticks(ax.get_yticks(), minor=True)
    if cntx.opt_map_discrete:
        cbar_ax.set_yticklabels(tick_labels)
    cbar_ax.set_ylabel(label, fontsize=fs_labels)
    cbar_ax.tick_params(labelsize=fs_ticks_cbar, length=0)

    # Draw region boundary.
    p_bounds = cntx.project.p_bounds
    if ((cntx.project.drive is None) and os.path.exists(p_bounds)) or\
       ((cntx.project.drive is not None) and (cntx.project.p_bounds != "")):
        draw_region_boundary(ax)

    # Draw locations.
    if df_loc is not None:
        ax.scatter(df_loc[c.DIM_LONGITUDE], df_loc[c.DIM_LATITUDE], facecolors="none", edgecolors="black", s=10)
        for i in range(len(df_loc)):
            offset = 0.05
            ax.text(df_loc[c.DIM_LONGITUDE][i] + offset, df_loc[c.DIM_LATITUDE][i] + offset, df_loc["desc"][i],
                    fontdict=dict(color="black", size=fs_labels, style="italic"))

    plt.close(fig)
    
    return fig


def get_cmap_name(
    z_min: float,
    z_max: float
) -> str:

    """
    --------------------------------------------------------------------------------------------------------------------
    Get colour map name.

    Parameters
    ----------
    z_min: float
        Minimum value.
    z_max: float
        Maximum value.

    Returns
    -------
    str
        Colour map name.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Determine color scale index.
    is_wind_var = cntx.varidx.code in [c.V_UAS, c.V_VAS, c.V_SFCWINDMAX]
    if (cntx.delta.code == "False") and (not is_wind_var):
        cmap_idx = 0
    elif (z_min < 0) and (z_max > 0):
        cmap_idx = 1
    elif (z_min < 0) and (z_max < 0):
        cmap_idx = 2
    else:
        cmap_idx = 3

    # Temperature-related.
    if cntx.varidx.code in \
        [c.V_TAS, c.V_TASMIN, c.V_TASMAX, c.I_ETR, c.I_TGG, c.I_TNG, c.I_TNX, c.I_TXX, c.I_TXG]:
        cmap_name = cntx.opt_map_col_temp_var[cmap_idx]
    elif cntx.varidx.code in \
        [c.I_TX_DAYS_ABOVE, c.I_HEAT_WAVE_MAX_LENGTH, c.I_HEAT_WAVE_TOTAL_LENGTH, c.I_HOT_SPELL_FREQUENCY,
         c.I_HOT_SPELL_MAX_LENGTH, c.I_HOT_SPELL_TOTAL_LENGTH, c.I_TROPICAL_NIGHTS, c.I_TX90P, c.I_WSDI]:
        cmap_name = cntx.opt_map_col_temp_idx_1[cmap_idx]
    elif cntx.varidx.code in [c.I_TN_DAYS_BELOW, c.I_TNG_MONTHS_BELOW]:
        cmap_name = cntx.opt_map_col_temp_idx_2[cmap_idx]

    # Precipitation-related.
    elif cntx.varidx.code in [c.V_PR, c.I_PRCPTOT, c.I_RX1DAY, c.I_RX5DAY, c.I_SDII, c.I_RAIN_SEASON_PRCPTOT]:
        cmap_name = cntx.opt_map_col_prec_var[cmap_idx]
    elif cntx.varidx.code in [c.I_CWD, c.I_R10MM, c.I_R20MM, c.I_WET_DAYS, c.I_RAIN_SEASON_LENGTH]:
        cmap_name = cntx.opt_map_col_prec_idx_1[cmap_idx]
    elif cntx.varidx.code in [c.I_CDD, c.I_DRY_DAYS, c.I_DROUGHT_CODE, c.I_DRY_SPELL_TOTAL_LENGTH]:
        cmap_name = cntx.opt_map_col_prec_idx_2[cmap_idx]
    elif cntx.varidx.code in [c.I_RAIN_SEASON_START, c.I_RAIN_SEASON_END]:
        cmap_name = cntx.opt_map_col_prec_idx_3[cmap_idx]

    # Evaporation-related.
    elif cntx.varidx.code in [c.V_EVSPSBL, c.V_EVSPSBLPOT]:
        cmap_name = cntx.opt_map_col_evap_var[cmap_idx]

    # Wind-related.
    elif cntx.varidx.code in [c.V_UAS, c.V_VAS, c.V_SFCWINDMAX]:
        cmap_name = cntx.opt_map_col_wind_var[cmap_idx]
    elif cntx.varidx.code in [c.I_WG_DAYS_ABOVE, c.I_WX_DAYS_ABOVE]:
        cmap_name = cntx.opt_map_col_wind_idx_1[cmap_idx]

    # Default values.
    else:
        cmap_name = cntx.opt_map_col_default[cmap_idx]

    return cmap_name


def get_hex_l(
    name: str
) -> List[str]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Get the list of HEX color codes associated with a color map.

    Parameters
    ----------
    name : str
        Name of a color map.

    Returns
    -------
    List[str]
        List of HEX color codes.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Custom color maps (not in matplotlib). The order assumes a vertical color bar.
    hex_wh  = "#ffffff"  # White.
    hex_gy  = "#808080"  # Grey.
    hex_gr  = "#008000"  # Green.
    hex_yl  = "#ffffcc"  # Yellow.
    hex_or  = "#f97306"  # Orange.
    hex_br  = "#662506"  # Brown.
    hex_rd  = "#ff0000"  # Red.
    hex_pi  = "#ffc0cb"  # Pink.
    hex_pu  = "#800080"  # Purple.
    hex_bu  = "#0000ff"  # Blue.
    hex_lbu = "#7bc8f6"  # Light blue.
    hex_lbr = "#d2b48c"  # Light brown.
    hex_sa  = "#a52a2a"  # Salmon.
    hex_tu  = "#008080"  # Turquoise.

    code_hex_l = {
        "Pinks": [hex_wh, hex_pi],
        "PiPu": [hex_pi, hex_wh, hex_pu],
        "Browns": [hex_wh, hex_br],
        "Browns_r": [hex_br, hex_wh],
        "YlBr": [hex_yl, hex_br],
        "BrYl": [hex_br, hex_yl],
        "BrYlGr": [hex_br, hex_yl, hex_gr],
        "GrYlBr": [hex_gr, hex_yl, hex_br],
        "YlGr": [hex_yl, hex_gr],
        "GrYl": [hex_gr, hex_yl],
        "BrWhGr": [hex_br, hex_wh, hex_gr],
        "GrWhBr": [hex_gr, hex_wh, hex_br],
        "TuYlSa": [hex_tu, hex_yl, hex_sa],
        "YlTu": [hex_yl, hex_tu],
        "YlSa": [hex_yl, hex_sa],
        "LBuWhLBr": [hex_lbu, hex_wh, hex_lbr],
        "LBlues": [hex_wh, hex_lbu],
        "BuYlRd": [hex_bu, hex_yl, hex_rd],
        "LBrowns": [hex_wh, hex_lbr],
        "LBuYlLBr": [hex_lbu, hex_yl, hex_lbr],
        "YlLBu": [hex_yl, hex_lbu],
        "YlLBr": [hex_yl, hex_lbr],
        "YlBu": [hex_yl, hex_bu],
        "Turquoises": [hex_wh, hex_tu],
        "Turquoises_r": [hex_tu, hex_wh],
        "PuYlOr": [hex_pu, hex_yl, hex_or],
        "YlOrRd": [hex_yl, hex_or, hex_rd],
        "YlOr": [hex_yl, hex_or],
        "YlPu": [hex_yl, hex_pu],
        "PuYl": [hex_pu, hex_yl],
        "GyYlRd": [hex_gy, hex_yl, hex_rd],
        "RdYlGy": [hex_rd, hex_yl, hex_gy],
        "YlGy": [hex_yl, hex_gy],
        "GyYl": [hex_gy, hex_yl],
        "YlRd": [hex_yl, hex_rd],
        "RdYl": [hex_rd, hex_yl],
        "GyWhRd": [hex_gy, hex_wh, hex_rd]}

    hex_l = None
    if name in list(code_hex_l.keys()):
        hex_l = code_hex_l[name]

    return hex_l


def get_cmap(
    cmap_name: str,
    hex_l: [str],
    n_cluster: int
):
    """
    --------------------------------------------------------------------------------------------------------------------
    Create a color map that can be used in heat map figures.

    If pos_l is not provided, color map graduates linearly between each color in hex_l.
    If pos_l is provided, each color in hex_l is mapped to the respective location in pos_l.

    Parameters
    ----------
    cmap_name: str
        Color map name.
    hex_l: [str]
        Hex code string list.
    n_cluster: int
        Number of clusters.

    Returns
    -------
        Color map.
    --------------------------------------------------------------------------------------------------------------------
    """

    # List of positions.
    if len(hex_l) == 2:
        pos_l = [0.0, 1.0]
    else:
        pos_l = [0.0, 0.5, 1.0]

    # Reverse hex list.
    if "_r" in cmap_name:
        hex_l.reverse()

    # Build colour map.
    rgb_l = [rgb_to_dec(hex_to_rgb(i)) for i in hex_l]
    if pos_l:
        pass
    else:
        pos_l = list(np.linspace(0, 1, len(rgb_l)))
    cdict = dict()
    for num, col in enumerate(["red", "green", "blue"]):
        col_l = [[pos_l[i], rgb_l[i][num], rgb_l[i][num]] for i in range(len(pos_l))]
        cdict[col] = col_l

    return colors.LinearSegmentedColormap("custom_cmap", segmentdata=cdict, N=n_cluster)


def adjust_precision(
    val_l: List[float],
    n_dec_max: Optional[int] = 4,
    output_type: Optional[str] = "float"
) -> List[Union[int, float, str]]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Adjust the precision of float values in a list so that each value is different than the following one.

    Parameters
    ----------
    val_l: List[float]
        List of values.
    n_dec_max: Optional[int]
        Maximum number of decimal places.
    output_type: Optional[str]
        Output type = {"int", "float", "str"}

    Returns
    -------
    List[Union[int, float, str]]
        Values with adjusted precision.
    --------------------------------------------------------------------------------------------------------------------
    """

    val_opt_l = []

    # Loop through potential numbers of decimal places.
    for n_dec in range(0, n_dec_max + 1):

        # Loop through values.
        unique_vals = True
        val_opt_l = []
        for i in range(len(val_l)):
            val_i = float(val_l[i])

            # Adjust precision.
            if n_dec == 0:
                if not np.isnan(float(val_i)):
                    val_i = str(int(round(val_i, n_dec)))
                else:
                    val_i = str(val_i)
            else:
                val_i = str("{:." + str(n_dec) + "f}").format(float(str(round(val_i, n_dec))))

            # Add value to list.
            val_opt_l.append(val_i)

            # Two consecutive rounded values are equal.
            if i > 0:
                if val_opt_l[i - 1] == val_opt_l[i]:
                    unique_vals = False

        # Stop loop if all values are unique.
        if unique_vals or (n_dec == n_dec_max):
            break

    # Convert values to output type if it's not numerical.
    val_new_l = []
    for i in range(len(val_l)):
        if output_type == "int":
            val_new_l.append(int(val_opt_l[i]))
        elif output_type == "float":
            val_new_l.append(float(val_opt_l[i]))
        else:
            val_new_l.append(val_opt_l[i])

    return val_new_l


def draw_region_boundary(
    ax: plt.axes
) -> plt.axes:

    """
    --------------------------------------------------------------------------------------------------------------------
    Draw region boundary.

    Parameters
    ----------
    ax : plt.axes
        Plots axes.
    --------------------------------------------------------------------------------------------------------------------
    """

    def _set_plot_extent(_ax, _vertices):

        # Extract limits.
        x_min = x_max = y_min = y_max = None
        for i in range(len(_vertices)):
            x_i = _vertices[i][0]
            y_i = _vertices[i][1]
            if i == 0:
                x_min = x_max = x_i
                y_min = y_max = y_i
            else:
                x_min = min(x_i, x_min)
                x_max = max(x_i, x_max)
                y_min = min(y_i, y_min)
                y_max = max(y_i, y_max)

        # Set the graph axes to the feature extents
        _ax.set_xlim(x_min, x_max)
        _ax.set_ylim(y_min, y_max)
        
        return _ax

    def _plot_feature(_coords, _ax):
        
        _patch = PolygonPatch({"type": "Polygon", "coordinates": _coords},
                              fill=False, ec="black", alpha=0.75, zorder=2)
        _ax.add_patch(_patch)
        
        return _ax

    # Load geojson file.
    if cntx.project.drive is None:
        vertices, coords = dfu.load_geojson(cntx.p_bounds, "vertices")
    else:
        vertices, coords = cntx.project.drive.load_geojson(cntx.p_bounds, "vertices")

    # Draw feature.
    ax_new = ax
    ax_new = _set_plot_extent(ax_new, vertices)
    ax_new = _plot_feature(coords, ax_new)
    
    return ax_new


def hex_to_rgb(
    value: str
):

    """
    --------------------------------------------------------------------------------------------------------------------
    Converts hex to RGB colors

    Parameters
    ----------
    value: str
        String of 6 characters representing a hex color.

    Returns
    -------
        list of 3 RGB values
    --------------------------------------------------------------------------------------------------------------------
    """

    value = value.strip("#")
    lv = len(value)

    return tuple(int(value[i:i + lv // 3], 16) for i in range(0, lv, lv // 3))


def rgb_to_dec(
    value: [int]
):

    """
    --------------------------------------------------------------------------------------------------------------------
    Converts RGB to decimal colors (i.e. divides each value by 256)

    Parameters
    ----------
    value: [int]
        List of 3 RGB values.

    Returns
    -------
        List of 3 decimal values.
    --------------------------------------------------------------------------------------------------------------------
    """

    return [v/256 for v in value]


def gen_cycle_ms(
    df: pd.DataFrame
) -> Union[any, plt.Figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a boxplot of monthly values.

    Parameters:
    ----------
    df: pd.DataFrame
        Dataframe.

    Returns
    -------
    Union[any, plt.Figure]
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    if cntx.lib.code == c.LIB_HV:
        fig = gen_cycle_ms_hv(df)
    else:
        fig = gen_cycle_ms_mat(df)

    return fig


def gen_cycle_ms_hv(
    df: pd.DataFrame
) -> any:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a boxplot of monthly values using hvplot.

    Parameters:
    ----------
    df: pd.DataFrame
        Dataframe.

    Returns
    -------
    any
        Plot.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Collect data.
    col_year = []
    col_month = []
    col_val = []
    for m in range(1, 13):
        col_year += list(df["year"])
        col_month += [m] * len(df)
        col_val += list(df[str(m)])

    # Translation between month number and string.
    ticks = list(range(1, 13))
    tick_labels = ["Jan", "F??v", "Mar", "Avr", "Mai", "Jui", "Jul", "Ao??", "Sep", "Oct", "Nov", "D??c"]
    ticks_dict = {ticks[i]: tick_labels[i] for i in range(len(ticks))}

    # Prepare the dataframe that will be used in the plot.
    df = pd.DataFrame()
    df["Ann??e"] = col_year
    df["Mois"] = col_month
    for i in range(len(df)):
        df.iloc[i, 1] = ticks_dict[df.iloc[i, 1]]
    df["Valeur"] = col_val

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())

    # Generate plot.
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    y_label = ("??" if delta_code == "True" else "") + cntx.varidx.label
    plot = df.hvplot.box(y="Valeur", by="Mois", height=375, width=730, legend=False, box_fill_color="white",
                         hover_cols=["Mois", "Valeur"]).opts(tools=["hover"], ylabel=y_label, title=title)

    return plot


def gen_cycle_ms_mat(
    df: pd.DataFrame
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a boxplot of monthly values using matplotlib.

    Parameters:
    ----------
    df: pd.DataFrame
        Dataframe.
        
    Returns
    -------
    plt.Figure
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Collect data.
    data = []
    for m in range(1, 13):
        data.append(df[str(m)])

    # Font size.
    fs = 10
    fs_axes = fs

    # Draw.
    height = 5.45 if cntx.code == c.PLATFORM_STREAMLIT else 5.15
    dpi = None if cntx.code == c.PLATFORM_SCRIPT else cntx.dpi
    fig = plt.figure(figsize=(9.95, height), dpi=dpi)
    plt.subplots_adjust(top=0.91, bottom=0.10, left=0.07, right=0.99, hspace=0.10, wspace=0.10)
    specs = gridspec.GridSpec(ncols=1, nrows=1, figure=fig)
    ax = fig.add_subplot(specs[:])
    bp = ax.boxplot(data, showfliers=False)

    # Format.
    plt.xticks([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
               ["Jan", "F??v", "Mar", "Avr", "Mai", "Jui", "Jul", "Ao??", "Sep", "Oct", "Nov", "D??c"], rotation=0)
    plt.xlabel("Mois", fontsize=fs_axes)
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    y_label = ("??" if delta_code == "True" else "") + cntx.varidx.label
    plt.ylabel(y_label, fontsize=fs_axes)
    plt.setp(bp["medians"], color="black")
    plt.tick_params(axis="x", labelsize=fs_axes)
    plt.tick_params(axis="y", labelsize=fs_axes)

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plt.title(title, loc="left", fontweight="bold")

    # Close plot.
    plt.close(fig)

    return fig


def gen_cycle_d(
    df: pd.DataFrame
) -> Union[any, plt.Figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a time series of daily values.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.

    Returns
    -------
    Union[any, plt.Figure]
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    if cntx.lib.code == c.LIB_HV:
        fig = gen_cycle_d_hv(df)
    else:
        fig = gen_cycle_d_mat(df)

    return fig


def gen_cycle_d_hv(
    df: pd.DataFrame
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a time series of daily values using hvplot

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.

    Returns
    -------
    plt.Figure
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Rename columns.
    df.rename(columns={"day": "Jour", "mean": "Moyenne", "min": "Minimum", "max": "Maximum"}, inplace=True)

    # Draw area.
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    y_label = ("??" if delta_code == "True" else "") + cntx.varidx.label
    area = df.hvplot.area(x="Jour", y="Minimum", y2="Maximum",
                          color="darkgrey", alpha=0.3, line_alpha=0, xlabel="Jour", ylabel=y_label)

    # Draw curve.
    tooltip = ["Jour", "Minimum", "Moyenne", "Maximum"]
    curve = df.hvplot.line(x="Jour", y="Moyenne", color="black", alpha=0.7, hover_cols=tooltip)

    # Combine components.
    plot = area * curve

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plot = plot.opts(hv.opts.Overlay(title=title))

    # Add legend.
    plot = plot.opts(legend_position="top_left", legend_opts={"click_policy": "hide", "orientation": "horizontal"},
                     frame_height=300, frame_width=645, border_line_alpha=0.0, background_fill_alpha=0.0)

    return plot

    
def gen_cycle_d_mat(
    df: pd.DataFrame,
    plt_type: Optional[int] = 1
) -> Union[plt.Figure, None]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a time series of daily values using matplotlib.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    plt_type: Optional[int]
        Plot type {1=line, 2=bar}
        If the value
        
    Returns
    -------
    Union[plt.Figure, None]
        Figure.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Font size.
    fs = 10
    fs_axes = fs
    fs_legend = fs

    # Number of values on the x-axis.
    n = len(df)

    # Draw curve (mean values) and shadow (zone between minimum and maximum values).
    height = 5.45 if cntx.code == c.PLATFORM_STREAMLIT else 5.15
    dpi = None if cntx.code == c.PLATFORM_SCRIPT else cntx.dpi
    fig, ax = plt.subplots(figsize=(9.95, height), dpi=dpi)
    plt.subplots_adjust(top=0.91, bottom=0.10, left=0.07, right=0.99, hspace=0.10, wspace=0.10)

    # Draw areas.
    ref_color = cl_rcp.RCP(c.REF).color
    rcp_color = "darkgrey"
    if plt_type == 1:
        ax.plot(range(1, n + 1), df[c.STAT_MEAN], color=ref_color, alpha=1.0)
        ax.fill_between(np.array(range(1, n + 1)), df[c.STAT_MEAN], df[c.STAT_MAX], color=rcp_color, alpha=1.0)
        ax.fill_between(np.array(range(1, n + 1)), df[c.STAT_MEAN], df[c.STAT_MIN], color=rcp_color, alpha=1.0)
    else:
        bar_width = 1.0
        plt.bar(range(1, n + 1), df[c.STAT_MAX], width=bar_width, color=rcp_color)
        plt.bar(range(1, n + 1), df[c.STAT_MEAN], width=bar_width, color=rcp_color)
        plt.bar(range(1, n + 1), df[c.STAT_MIN], width=bar_width, color="white")
        ax.plot(range(1, n + 1), df[c.STAT_MEAN], color=ref_color, alpha=1.0)
        y_lim_lower = min(df[c.STAT_MIN])
        y_lim_upper = max(df[c.STAT_MAX])
        plt.ylim([y_lim_lower, y_lim_upper])

    # Format.
    plt.xlim([1, n])
    plt.xticks(np.arange(1, n + 1, 30))
    plt.xlabel("Jour", fontsize=fs_axes)
    delta_code = cntx.delta.code if cntx.delta is not None else "False"
    y_label = ("??" if delta_code == "True" else "") + cntx.varidx.label
    plt.ylabel(y_label, fontsize=fs_axes)
    plt.tick_params(axis="x", labelsize=fs_axes)
    plt.tick_params(axis="y", labelsize=fs_axes)

    # Title.
    title = str(plot_title()) + "\n" + str(plot_code())
    plt.title(title, loc="left", fontweight="bold")

    # Format.
    plt.legend(["Valeur moyenne", "??tendue des valeurs"], fontsize=fs_legend)

    # Close plot.
    plt.close(fig)
    
    return fig


def plot_title(
) -> str:

    """
    --------------------------------------------------------------------------------------------------------------------
    Get plot title.

    Returns
    -------
    str
        Plot title.
    --------------------------------------------------------------------------------------------------------------------
    """

    return cntx.varidx.desc


def plot_code(
) -> str:

    """
    --------------------------------------------------------------------------------------------------------------------
    Get plot code.

    Returns
    -------
    str
        Plot code.
    --------------------------------------------------------------------------------------------------------------------
    """

    code = ""

    if cntx.view.code in [c.VIEW_TS, c.VIEW_TS_BIAS, c.VIEW_CYCLE]:
        code = cntx.varidx.code
        if cntx.view.code == c.VIEW_CYCLE:
            code += " - " + cntx.hor.code
        if cntx.rcp.code not in ["", c.RCPXX]:
            code += " - " + cntx.rcp.desc
        if cntx.sim.code not in ["", c.SIMXX]:
            if (cntx.rcp.code in ["", c.RCPXX]) and (cntx.sim.rcp is not None):
                code += " - " + cntx.sim.rcp.desc
            if "rcp" in cntx.sim.code:
                code += " - " + cntx.sim.rcm + "_" + cntx.sim.gcm

    elif cntx.view.code == c.VIEW_TBL:
        code = cntx.varidx.code + " - " + cntx.hor.code

    elif cntx.view.code == c.VIEW_MAP:
        code = cntx.varidx.code + " - " + cntx.hor.code + " - " + cntx.rcp.desc
        if cntx.rcp.code != c.REF:
            if cntx.stat.code != c.STAT_CENTILE:
                desc = cntx.stat.desc
            else:
                desc = str(cntx.stat.centile) + "e " + c.STAT_CENTILE
            code += " - " + desc

    delta_code = cntx.delta.code if cntx.delta is not None else "False"

    return ("??" if delta_code == "True" else "") + code


def gen_cluster_tbl(
    n_cluster: int
) -> pd.DataFrame:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate cluster table (based on time series).

    Parameters
    ----------
    n_cluster: int
        Number of clusters.

    Returns
    -------
    pd.DataFrame
    --------------------------------------------------------------------------------------------------------------------
    """

    # Column names.
    col_sim = "Simulation"
    col_rcp = "RCP"
    col_grp = "Groupe"

    # Calculate clusters.
    df = pd.DataFrame(stats.calc_clusters(n_cluster))

    # Subset columns and sort rows.
    df = df[[col_sim, col_rcp, col_grp]]
    df.sort_values(by=[col_grp, col_rcp], inplace=True)

    # Title.
    vars_str = str(cntx.varidxs.code_l).replace("[", "").replace("]", "").replace("'", "")
    title = "<b>Regroupement des simulations par similarit??<br>=f(" + vars_str + ")</b>"

    # In Jupyter Notebook, a dataframe appears nicely.
    if cntx.code == c.PLATFORM_JUPYTER:
        tbl = df.set_index(df.columns[0])

    # In Streamlit, a table needs to be formatted.
    else:

        # Determine text colors.
        cmap = plt.cm.get_cmap(cntx.opt_cluster_col, n_cluster)
        text_color_l = []
        for i in range(n_cluster):
            text_color_l_i = []
            for j in range(len(df)):
                group = df[col_grp].values[j]
                text_color_l_i.append(colors.to_hex(cmap((group - 1) / (n_cluster - 1))))
            text_color_l.append(text_color_l_i)

        # Values.
        values = []
        for col_name in df.columns:
            values.append(df[col_name])

        # Table
        fig = go.Figure(data=[go.Table(
            header=dict(values=list(df.columns),
                        line_color="white",
                        fill_color=cntx.col_sb_fill,
                        align="right"),
            cells=dict(values=values,
                       font=dict(color=text_color_l),
                       line_color="white",
                       fill_color="white",
                       align="right"))
        ])
        fig.update_layout(
            font=dict(size=15),
            width=700,
            height=50 + 23 * len(df),
            margin=go.layout.Margin(l=0, r=0, b=0, t=50),
            title_text=title,
            title_x=0,
            title_font=dict(size=15)
        )
        tbl = fig

    return tbl


def gen_cluster_plot(
    n_cluster: int,
    p_l: Optional[List[str]] = None
) -> Union[any, plt.figure]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a cluster scatter plot (based on time series).

    Parameters
    ----------
    n_cluster: int
        Number of clusters.
    p_l: Optional[List[str]]
        Path of data files (one per variable).

    Returns
    -------
    Union[any, plt.figure] :
        Cluster scatter plot.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Column names.
    col_grp   = "Groupe"
    col_leg_x = "leg_x"
    col_leg_y = "leg_y"
    col_color = "color"

    # Calculate clusters.
    df = pd.DataFrame(stats.calc_clusters(n_cluster, p_l))
    df.sort_index(inplace=True)

    # Extract variables.
    if cntx.varidxs.count == 1:
        var_1 = var_2 = cntx.varidxs.items[0]
    else:
        var_1 = cntx.varidxs.items[0]
        var_2 = cntx.varidxs.items[1]

    # Title.
    vars_str = str(cntx.varidxs.code_l).replace("[", "").replace("]", "").replace("'", "")
    title = "Regroupement des simulations par similarit??\n=f(" + vars_str + ")"

    # Labels.
    axis_labels = dict({"x": var_1.desc + " (" + var_1.unit + ")", "y": var_2.desc + " (" + var_2.unit + ")"})

    # Color map.
    cmap = plt.cm.get_cmap(cntx.opt_cluster_col, n_cluster)

    # Legend: number of columns and rows.
    n_col_max = 30
    n_row = math.ceil(n_cluster / n_col_max)
    n_row_max = 15

    # Legend: spacing between legend items.
    x_min = np.nanmin(df[var_1.code])
    x_max = np.nanmax(df[var_1.code])
    dx = (x_max - x_min) / n_col_max
    y_min = np.nanmin(df[var_2.code])
    y_max = np.nanmax(df[var_2.code])
    dy = (y_max - y_min) / n_row_max
    leg_pos = {"x": x_min, "y": y_min + (dy * n_row)}

    # Legend: collect legend items.
    leg_pos_x_l, leg_pos_y_l, color_l = [], [], []
    for i in range(len(df)):
        group = df[col_grp][i]
        i_col = (group - 1) % n_col_max
        i_row = n_row - math.ceil(group / n_col_max)
        leg_pos_x_l.append(x_min + (dx * i_col))
        leg_pos_y_l.append(y_min + (dy * i_row))
        color_l.append("black" if n_cluster == 1 else colors.to_hex(cmap((group - 1) / (n_cluster - 1))))
    df[col_leg_x] = leg_pos_x_l
    df[col_leg_y] = leg_pos_y_l
    df[col_color] = color_l

    # Generate plot.
    if cntx.lib.code == c.LIB_MAT:
        plot = gen_cluster_plot_mat(df, var_1, var_2, title, axis_labels, leg_pos)
    else:
        plot = gen_cluster_plot_hv(df, var_1, var_2, title, axis_labels, leg_pos)

    return plot


def gen_cluster_plot_hv(
    df: pd.DataFrame,
    var_1: VarIdx,
    var_2: VarIdx,
    title: str,
    axis_labels: dict,
    leg_pos: Optional[dict]
) -> any:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a cluster scatter plot (based on time series) using hvplot.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    var_1: VarIdx
        First variable.
    var_2: VarIdx
        Second variable.
    title: str
        Title.
    axis_labels: dict
        Axis labels {"x", "y"}
    leg_pos: Optional[dict],
        Legend position {"x", "y"}

    Returns
    -------
    any
        Cluster scatter plot.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Legend type (1=standard, 2=text).
    leg_type = 2

    # Font size.
    fs_labels = 10

    # Column names.
    col_sim       = "Simulation"
    col_rcp       = "RCP"
    col_grp       = "Groupe"
    col_leg_x     = "leg_x"
    col_leg_y     = "leg_y"
    col_leg_title = "leg_title"
    col_color     = "color"

    # Number of clusters.
    n_cluster = len(df[col_grp].unique())

    # Adjust precision (not working great).
    # df[var_1.code] = adjust_precision(list(df[var_1.code].values), n_dec_max=var_1.precision, output_type="float")
    # df[var_2.code] = adjust_precision(list(df[var_2.code].values), n_dec_max=var_2.precision, output_type="float")

    # Rename columns.
    df.rename(columns={var_1.code: var_1.desc, var_2.code: var_2.desc}, inplace=True)

    # Create scatter plots and labels.
    plot = None
    labels = None
    for i in range(n_cluster):

        # Select the rows corresponding to the current cluster.
        df_i = df[df[col_grp] == i + 1].copy()

        # Color.
        color = df_i[col_color].values[0]

        # Create points.
        hover_cols = [col_sim, col_rcp, col_grp, var_1.desc, var_2.desc]
        if leg_type == 1:
            label = (col_grp + " " + str(i + 1))
            plot_i = df_i.hvplot.scatter(x=var_1.desc, y=var_2.desc, color=color, label=label,
                                         hover_cols=hover_cols)
        else:
            plot_i = df_i.hvplot.scatter(x=var_1.desc, y=var_2.desc, color=color,
                                         hover_cols=hover_cols)
        plot = plot_i if plot is None else plot * plot_i

        # Create legend items.
        if leg_type == 2:
            for j in range(2):
                df_grp = None
                color_j = "black" if j == 0 else color
                if (i == 0) and (j == 0):
                    df_grp = pd.DataFrame([[i + 1, float(leg_pos["x"]), float(leg_pos["y"]), "Groupes:"]],
                                          columns=[col_grp, col_leg_x, col_leg_y, col_leg_title])
                    df_grp.set_index(col_grp, inplace=True)
                elif j == 1:
                    df_grp = df_i[[col_grp, col_leg_x, col_leg_y]]
                    df_grp.set_index(col_grp, inplace=True)
                    df_grp = df_grp[0:1]
                    df_grp[col_leg_title] = str(i + 1)
                if df_grp is not None:
                    label = hv.Labels(data=df_grp, x=col_leg_x, y=col_leg_y, text=col_leg_title).\
                        opts(text_color=color_j, text_align="left", text_font_size=str(fs_labels) + "pt")
                    labels = label if labels is None else labels * label

    # Add labels
    if labels is not None:
        plot = plot * labels

    # Title.
    plot = plot.opts(hv.opts.Overlay(title=title))

    # Adjust size and add legend.
    if leg_type == 1:
        plot = plot.opts(frame_height=300, frame_width=645, border_line_alpha=0.0, background_fill_alpha=0.0,
                         xlabel=axis_labels["x"], ylabel=axis_labels["y"], legend_position="top_left",
                         legend_opts={"click_policy": "hide", "orientation": "horizontal"})
    else:
        plot = plot.opts(frame_height=300, frame_width=645, border_line_alpha=0.0, background_fill_alpha=0.0,
                         xlabel=axis_labels["x"], ylabel=axis_labels["y"])

    return plot


def gen_cluster_plot_mat(
    df: pd.DataFrame,
    var_1: VarIdx,
    var_2: VarIdx,
    title: str,
    axis_labels: dict,
    leg_pos: Optional[dict]
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Plot a cluster scatter plot (based on time series) using matplotlib.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe.
    var_1: VarIdx
        First variable.
    var_2: VarIdx
        Second variable.
    title: str
        Title.
    axis_labels: dict
        Axis labels {"x", "y"}
    leg_pos: Optional[dict],
        Legend position {"x", "y"}

    Returns
    -------
    plt.Figure
        Figure
    --------------------------------------------------------------------------------------------------------------------
    """

    # Legend type (1=standard, 2=text).
    leg_type = 2

    # Column names.
    col_grp   = "Groupe"
    col_leg_x = "leg_x"
    col_leg_y = "leg_y"
    col_color = "color"

    # Number of clusters.
    n_cluster = len(df[col_grp].unique())

    # Font size.
    fs        = 9 if cntx.code == c.PLATFORM_STREAMLIT else 10
    fs_title  = fs + 1
    fs_labels = fs

    # Initialize figure and axes.
    if c.PLATFORM_STREAMLIT in cntx.code:
        fig = plt.figure(figsize=(9, 4.4), dpi=cntx.dpi)
    else:
        dpi = cntx.dpi if c.PLATFORM_JUPYTER in cntx.code else None
        fig = plt.figure(figsize=(10.6, 4.8), dpi=dpi)
        plt.subplots_adjust(top=0.91, bottom=0.11, left=0.06, right=0.98, hspace=0.0, wspace=0.0)
    specs = gridspec.GridSpec(ncols=1, nrows=1, figure=fig)
    ax = fig.add_subplot(specs[:])

    # Format.
    ax.set_xlabel(axis_labels["x"])
    ax.set_ylabel(axis_labels["y"])

    # Create scatter plot (matplotlib).
    leg_labels = []
    leg_lines = []
    ax.text(leg_pos["x"], leg_pos["y"], "Groupes:", color="black")
    for i in range(n_cluster):

        # Color.
        color = df[df[col_grp] == i + 1][col_color].unique()[0]

        # Add points.
        ax.scatter(x=df[df[col_grp] == i + 1][var_1.code], y=df[df[col_grp] == i + 1][var_2.code], s=15, color=color)

        # Add legend items.
        if leg_type == 1:
            leg_labels.append(col_grp + " " + str(i + 1))
            leg_lines.append(Line2D([0], [0], color=color, lw=2))
        else:
            leg_x = df[df[col_grp] == i + 1][col_leg_x].unique()[0]
            leg_y = df[df[col_grp] == i + 1][col_leg_y].unique()[0]
            ax.text(leg_x, leg_y, str(i + 1), color=color)

    # Title.
    plt.title(title, loc="left", fontweight="bold", fontsize=fs_title)

    # Legend.
    if leg_type == 1:
        plt.legend()
        ax.legend(leg_lines, leg_labels, loc="upper left", ncol=5, mode="expland", frameon=False, fontsize=fs_labels)

    plt.close(fig)

    return fig


def gen_taylor_plot(
    df: pd.DataFrame
) -> plt.Figure:

    """
    --------------------------------------------------------------------------------------------------------------------
    Generate a Taylor diagram.

    Parameters
    ----------
    df: pd.DataFrame
        Dataframe containing the following columns:
        - Labels.
        - Standard deviations.
        - Centered root mean square deviations.
        - Correlation coefficients.

    Returns
    -------
    plt.Figure
        Figure

    Note:
    pip uninstall Flask Jinja2
    pip install Flask Jinja2==3.0
    --------------------------------------------------------------------------------------------------------------------
    """

    # Extract columns.
    sim_code_l = list(df["sim_code"])
    sdev_l     = list(df["sdev"])
    crmsd_l    = list(df["crmsd"])
    ccoef_l    = list(df["ccoef"])

    # Determine tick marks along the CRMSD axis.
    tick_crmsd = []
    for i in [0, 0.25, 0.5, 0.75]:
        tick_crmsd.append(max(crmsd_l) * i)
    tick_crmsd = list(adjust_precision(tick_crmsd, n_dec_max=2, output_type="float"))

    # Determine the number of columns (assuming 15 rows).
    n_columns = math.ceil((len(sim_code_l) - 1) / 15.0)

    # Generated diagram.
    sm.taylor_diagram(np.array(sdev_l), np.array(crmsd_l), np.array(ccoef_l),
                      markerLabel=sim_code_l, markerLabelColor="r", markerLegend="on", markerColor="r",
                      styleOBS="-", colOBS="r", markerobs="o", markerSize=6, tickRMS=tick_crmsd,
                      tickRMSangle=115, showlabelsRMS="on", titleRMS="on", titleOBS="Reference", checkstats="on")
    fig = plt.gcf()

    # Resize figure and left-align.
    if min(ccoef_l) >= 0:
        fig.set_figwidth(7.5 + (n_columns - 1) * 3.75)
    else:
        fig.set_figwidth(12.0 + (n_columns - 1) * 3.75)
    fig.set_figheight(5)
    fig.axes[0].set_anchor('W')
    plt.subplots_adjust(left=0.05)

    plt.close(fig)

    return fig
