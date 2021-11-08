import warnings

import numpy as np
from magicgui.widgets import Table
from napari_plugin_engine import napari_hook_implementation
from napari.types import ImageData, LabelsData, LayerDataTuple
from napari import Viewer
from pandas import DataFrame
from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QWidget, QGridLayout, QPushButton, QFileDialog
from skimage.measure import regionprops_table
from napari_tools_menu import register_function
import napari
import math

@napari_hook_implementation
def napari_experimental_provide_function():
    return [skimage_regionprops]

@register_function(menu="Measurement > Regionprops (scikit-image)")
def skimage_regionprops(image: ImageData, labels_layer: napari.layers.Labels, napari_viewer : Viewer, size : bool = True, intensity : bool = True, perimeter : bool = False, shape : bool = False, position : bool = False, moments : bool = False):
    """
    Adds a table widget to a given napari viewer with quantitative analysis results derived from an image-labelimage pair.
    """
    labels = labels_layer.data

    if image is not None and labels is not None:

        # deal with dimensionality of data
        if len(image.shape) > len(labels.shape):
            dim = 0
            subset = ""
            while len(image.shape) > len(labels.shape):
                current_dim_value = napari_viewer.dims.current_step[dim]
                dim = dim + 1
                image = image[current_dim_value]
                subset = subset + ", " + str(current_dim_value)
            warnings.warn("Not the full image was analysed, just the subset [" + subset[2:] + "] according to selected timepoint / slice.")


        properties = ['label']
        extra_properties = []

        if size:
            properties = properties + ['area', 'bbox_area', 'convex_area', 'equivalent_diameter']

        if intensity:
            properties = properties + ['max_intensity', 'mean_intensity', 'min_intensity']

            # arguments must be in the specified order, matching regionprops
            def standard_deviation_intensity(region, intensities):
                return np.std(intensities[region])

            extra_properties.append(standard_deviation_intensity)

        if perimeter:
            if len(labels_layer.data.shape) == 2:
                properties = properties + ['perimeter', 'perimeter_crofton']
            else:
                warnings.warn("Perimeter measurements are not supported in 3D")

        if shape:
            properties = properties + ['solidity', 'extent', 'feret_diameter_max', 'local_centroid']
            if len(labels_layer.data.shape) == 2:
                properties = properties + ['major_axis_length', 'minor_axis_length', 'orientation', 'eccentricity']
            else:
                properties = properties + ['moments_central']
            # euler_number,

        if position:
            properties = properties + ['centroid', 'bbox', 'weighted_centroid']

        if moments:
            properties = properties + ['moments', 'moments_normalized']
            if 'moments_central' not in properties:
                properties = properties + ['moments_central']
            if len(labels_layer.data.shape) == 2:
                properties = properties + ['moments_hu']

        # todo:
        # weighted_local_centroid
        # weighted_moments
        # weighted_moments_central
        # weighted_moments_hu
        # weighted_moments_normalized

        # quantitative analysis using scikit-image's regionprops
        table = regionprops_table(np.asarray(labels).astype(int), intensity_image=np.asarray(image),
                                  properties=properties, extra_properties=extra_properties)

        if shape:
            if len(labels_layer.data.shape) == 3:
                axis_lengths_0 = []
                axis_lengths_1 = []
                axis_lengths_2 = []
                for i in range(len(table['moments_central-0-0-0'])):
                    table_temp = { # ugh
                        'moments_central-0-0-0': table['moments_central-0-0-0'][i],
                        'moments_central-2-0-0': table['moments_central-2-0-0'][i],
                        'moments_central-0-2-0': table['moments_central-0-2-0'][i],
                        'moments_central-0-0-2': table['moments_central-0-0-2'][i],
                        'moments_central-1-1-0': table['moments_central-1-1-0'][i],
                        'moments_central-1-0-1': table['moments_central-1-0-1'][i],
                        'moments_central-0-1-1': table['moments_central-0-1-1'][i]
                    }
                    axis_lengths = ellipsoid_axis_lengths(table_temp)
                    axis_lengths_0.append(axis_lengths[0]) # ugh
                    axis_lengths_1.append(axis_lengths[1])
                    axis_lengths_2.append(axis_lengths[2])

                table["minor_axis_length"] = axis_lengths_2
                table["intermediate_axis_length"] = axis_lengths_1
                table["major_axis_length"] = axis_lengths_0

                if not moments:
                    # remove moment from table as we didn't ask for them
                    table = {k: v for k, v in table.items() if not 'moments_central' in k}

        # Store results in the properties dictionary:
        labels_layer.properties = table

        # turn table into a widget
        dock_widget = table_to_widget(table, labels_layer)

        # add widget to napari
        napari_viewer.window.add_dock_widget(dock_widget, area='right')
    else:
        warnings.warn("Image and labels must be set.")

def ellipsoid_axis_lengths(table):
    """Compute ellipsoid major, intermediate and minor axis length.

    Adapted from https://forum.image.sc/t/scikit-image-regionprops-minor-axis-length-in-3d-gives-first-minor-radius-regardless-of-whether-it-is-actually-the-shortest/59273/2

    Parameters
    ----------
    table from regionprops containing moments_central

    Returns
    -------
    axis_lengths: tuple of float
        The ellipsoid axis lengths in descending order.
    """


    m0 = table['moments_central-0-0-0']
    sxx = table['moments_central-2-0-0'] / m0
    syy = table['moments_central-0-2-0'] / m0
    szz = table['moments_central-0-0-2'] / m0
    sxy = table['moments_central-1-1-0'] / m0
    sxz = table['moments_central-1-0-1'] / m0
    syz = table['moments_central-0-1-1'] / m0
    S = np.asarray([[sxx, sxy, sxz], [sxy, syy, syz], [sxz, syz, szz]])
    # determine eigenvalues in descending order
    eigvals = np.sort(np.linalg.eigvalsh(S))[::-1]
    return tuple([math.sqrt(20.0 * e) for e in eigvals])

def table_to_widget(table: dict, labels_layer: napari.layers.Labels) -> QWidget:
    """
    Takes a table given as dictionary with strings as keys and numeric arrays as values and returns a QWidget which
    contains a QTableWidget with that data.
    """
    # Using a custom widget because this one freezes napari:
    # view = Table(value=table)
    view = QTableWidget(len(next(iter(table.values()))), len(table))
    for i, column in enumerate(table.keys()):
        view.setItem(0, i, QTableWidgetItem(column))
        for j, value in enumerate(table.get(column)):
            view.setItem(j + 1, i, QTableWidgetItem(str(value)))

    if labels_layer is not None:

        @view.clicked.connect
        def clicked_table():
            row = view.currentRow()
            label = table["label"][row]
            labels_layer.selected_label = label

        def after_labels_clicked():
            row = view.currentRow()
            label = table["label"][row]
            if label != labels_layer.selected_label:
                for r, l in enumerate(table["label"]):
                    if l ==  labels_layer.selected_label:
                        view.setCurrentCell(r, view.currentColumn())
                        break

        @labels_layer.mouse_drag_callbacks.append
        def clicked_labels(event, event1):
            # We need to run this lagter as the labels_layer.selected_label isn't changed yet.
            QTimer.singleShot(200, after_labels_clicked)



    copy_button = QPushButton("Copy to clipboard")

    @copy_button.clicked.connect
    def copy_trigger():
        DataFrame(table).to_clipboard()

    save_button = QPushButton("Save as csv...")

    @save_button.clicked.connect
    def save_trigger():
        filename, _ = QFileDialog.getSaveFileName(save_button, "Save as csv...", ".", "*.csv")
        DataFrame(table).to_csv(filename)

    widget = QWidget()
    widget.setWindowTitle("region properties")
    widget.setLayout(QGridLayout())
    widget.layout().addWidget(copy_button)
    widget.layout().addWidget(save_button)
    widget.layout().addWidget(view)

    return widget