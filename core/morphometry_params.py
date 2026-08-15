# -*- coding: utf-8 -*-
"""
Calcul des paramètres morphométriques d'un bassin versant à partir d'un MNT
(altitudes, pentes, courbe hypsométrique, indices de pente).

Nécessite GDAL et numpy (fournis avec l'installation QGIS).
"""
import math
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()


def _rasterize_mask(dem_path, polygon_geom_wkt, epsg):
    """
    Découpe le MNT sur l'emprise du polygone et renvoie un tableau numpy
    masqué (NaN hors bassin) ainsi que la taille de pixel (m).
    """
    src_ds = gdal.Open(dem_path)
    gt = src_ds.GetGeoTransform()
    pixel_w = gt[1]
    pixel_h = abs(gt[5])

    mem_vec = ogr.GetDriverByName("Memory").CreateDataSource("mask")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    layer = mem_vec.CreateLayer("mask", srs, ogr.wkbPolygon)
    feat = ogr.Feature(layer.GetLayerDefn())
    geom = ogr.CreateGeometryFromWkt(polygon_geom_wkt)
    feat.SetGeometry(geom)
    layer.CreateFeature(feat)

    minx, maxx, miny, maxy = geom.GetEnvelope()

    warp_opts = gdal.WarpOptions(
        format="MEM",
        outputBounds=(minx, miny, maxx, maxy),
        xRes=pixel_w,
        yRes=pixel_h,
        cutlineDSName=None,
        dstNodata=-9999,
    )
    clipped_ds = gdal.Warp("", src_ds, options=warp_opts)

    # Rasterize mask polygon on the clipped grid
    mask_ds = gdal.GetDriverByName("MEM").Create(
        "", clipped_ds.RasterXSize, clipped_ds.RasterYSize, 1, gdal.GDT_Byte
    )
    mask_ds.SetGeoTransform(clipped_ds.GetGeoTransform())
    mask_ds.SetProjection(clipped_ds.GetProjection())
    gdal.RasterizeLayer(mask_ds, [1], layer, burn_values=[1])

    dem_arr = clipped_ds.GetRasterBand(1).ReadAsArray().astype(float)
    mask_arr = mask_ds.GetRasterBand(1).ReadAsArray()
    nodata = clipped_ds.GetRasterBand(1).GetNoDataValue()

    valid = (mask_arr == 1)
    if nodata is not None:
        valid &= (dem_arr != nodata)

    dem_arr[~valid] = np.nan
    return dem_arr, pixel_w, pixel_h


def altitude_and_hypsometric_stats(dem_path, polygon_geom_wkt, epsg, n_classes=20):
    """
    Calcule les statistiques d'altitude et la courbe hypsométrique
    (fraction de surface au-dessus de chaque seuil d'altitude).

    :return: dict avec Hmin, Hmax, Hmean, Hmed, denivelee, courbe hypsométrique
             (liste de tuples (altitude, % surface cumulée)) et intégrale
             hypsométrique (Hi).
    """
    dem_arr, px_w, px_h = _rasterize_mask(dem_path, polygon_geom_wkt, epsg)
    valid = dem_arr[~np.isnan(dem_arr)]
    if valid.size == 0:
        return None

    hmin = float(np.min(valid))
    hmax = float(np.max(valid))
    hmean = float(np.mean(valid))
    hmed = float(np.median(valid))

    # Courbe hypsométrique : altitude relative vs surface relative
    thresholds = np.linspace(hmin, hmax, n_classes + 1)
    total_cells = valid.size
    curve = []
    for t in thresholds:
        frac_area = float(np.sum(valid >= t)) / total_cells
        curve.append((float(t), frac_area * 100.0))

    # Intégrale hypsométrique (Hi) approximée par (Hmean-Hmin)/(Hmax-Hmin)
    hi = (hmean - hmin) / (hmax - hmin) if hmax > hmin else None

    return {
        "altitude_min_m": hmin,
        "altitude_max_m": hmax,
        "altitude_moyenne_m": hmean,
        "altitude_mediane_m": hmed,
        "denivelee_m": hmax - hmin,
        "courbe_hypsometrique": curve,
        "integrale_hypsometrique_Hi": hi,
    }


def mean_raster_value(raster_path, polygon_geom_wkt, epsg):
    """
    Calcule la valeur moyenne d'un raster QUELCONQUE sur l'emprise du bassin
    (même principe que mean_slope_percent, généralisé). Utilisé notamment
    pour la moyenne surfacique du Curve Number (CN) fourni par l'utilisateur.
    """
    arr, px_w, px_h = _rasterize_mask(raster_path, polygon_geom_wkt, epsg)
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return None
    return float(np.mean(valid))


def mean_slope_percent(dem_path, polygon_geom_wkt, epsg):
    """
    Calcule la pente moyenne du bassin (%) par différences finies (gradient)
    sur le MNT découpé.
    """
    dem_arr, px_w, px_h = _rasterize_mask(dem_path, polygon_geom_wkt, epsg)
    if np.all(np.isnan(dem_arr)):
        return None

    filled = np.where(np.isnan(dem_arr), np.nanmean(dem_arr), dem_arr)
    dzdy, dzdx = np.gradient(filled, px_h, px_w)
    slope = np.sqrt(dzdx ** 2 + dzdy ** 2)  # m/m
    slope[np.isnan(dem_arr)] = np.nan
    mean_slope = float(np.nanmean(slope)) * 100.0  # en %
    return mean_slope


def global_slope_index(hmax_5pct, hmin_95pct, basin_length_km):
    """
    Indice de pente globale Ig = (H5% - H95%) / L
    (H5%, H95% en m ; L = longueur du rectangle équivalent, en km)
    """
    if not basin_length_km:
        return None
    return (hmax_5pct - hmin_95pct) / basin_length_km


def specific_denivelation(ig, area_km2):
    """Dénivelée spécifique : Ds = Ig * sqrt(A)"""
    return ig * math.sqrt(area_km2) if ig is not None else None
