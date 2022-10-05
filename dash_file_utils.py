# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------------------------------------------------
# Climate information dashboard.
#
# Utility functions for file manipulation.
#
# Contact information:
# 1. rousseau.yannick@ouranos.ca (pimping agent)
# (C) 2020-2022 Ouranos, Canada
# ----------------------------------------------------------------------------------------------------------------------

# External libraries.
import io
import numpy as np
import os
import pandas as pd
import requests
import simplejson
from pathlib import Path
from typing import List, Tuple, Union

# Dashboard libraries.
from cl_constant import const as c


def p_exists(
    p: str
) -> bool:

    """
    --------------------------------------------------------------------------------------------------------------------
    Determine whether a path exists or not.

    Parameters
    ----------
    p: str
        Path.

    Returns
    -------
    bool
        True if a path exists.
    --------------------------------------------------------------------------------------------------------------------
    """

    if ("http" in p) or ("ftp" in p):
        return requests.head(p, allow_redirects=True).status_code == 200
    else:
        return os.path.exists(p)


def ls_dir(
    p: str
) -> List[str]:
    """
    --------------------------------------------------------------------------------------------------------------------
    List sub-directories within a directory.

    Parameters
    ----------
    p: str
        Path.

    Returns
    -------
    List[str]
        List of sub-directories.
    --------------------------------------------------------------------------------------------------------------------
    """

    dir_l = []

    for e in Path(p).iterdir():
        try:
            if Path(e).is_dir():
                dir_l.append(os.path.basename(str(e)))
        except NotADirectoryError:
            pass

    return dir_l


def load_geojson(
    p: Union[str, requests.Response],
    out_format: str = "vertices",
    first_only: bool = True
) -> Union[pd.DataFrame, List[pd.DataFrame], Tuple[List[float], any], List[Tuple[List[float], any]]]:

    """
    --------------------------------------------------------------------------------------------------------------------
    Load a geojson file.

    Parameters
    ----------
    p: Union[str, requests.Response]
        Path or HTTP response.
    out_format: str
        Format = {"vertices", "pandas"}
    first_only: bool
        If True, return the first feature only.
        If False, return all features.

    Returns
    -------
    Union[pd.DataFrame, List[pd.DataFrame], Tuple[List[float]], List[Tuple[List[float], any]]]
        Vertices and coordinates, or dataframe.
    --------------------------------------------------------------------------------------------------------------------
    """

    # Read file.
    if isinstance(p, str):
        f = open(p)
    else:
        f = io.StringIO(p.text)
    pydata = simplejson.load(f)

    # Structure that will hold the result.
    res = []

    for i in range(len(pydata["features"])):

        # Extract vertices.
        coords = pydata["features"][i]["geometry"]["coordinates"][0]
        vertices = coords[0]
        if len(vertices) == 2:
            coords = pydata["features"][i]["geometry"]["coordinates"]
            vertices = coords[0]

        # Extract vertices and coordinates.
        if out_format == "vertices":
            res_i = vertices, coords
        else:
            res_i = pd.DataFrame()
            res_i[c.DIM_LONGITUDE] = np.array(vertices).T.tolist()[0]
            res_i[c.DIM_LATITUDE] = np.array(vertices).T.tolist()[1]

        # Store the result for the current feature.
        if first_only:
            res = res_i
        else:
            res.append(res_i)

    return res
