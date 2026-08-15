# -*- coding: utf-8 -*-
"""
HydroSuiteBM Pro
Hydrological Analysis Platform for QGIS -- édition complète.
Point d'entrée du plugin QGIS.
"""


def classFactory(iface):
    from .hydrosuitebm_pro import HydroSuiteBMPro
    return HydroSuiteBMPro(iface)
