# -*- coding: utf-8 -*-
"""
Assistant de construction d'un raster Curve Number (CN), à partir d'une
couche raster d'occupation du sol et d'une couche raster de groupe
hydrologique de sol (A/B/C/D), en appliquant la table de correspondance
standard du NRCS (méthode SCS-CN, TR-55).

Contrairement à une approche s'appuyant sur des jeux de données globaux
automatiques (ex. croisement occupation du sol satellite x base de sols
mondiale), ce module travaille à partir des couches que L'UTILISATEUR
fournit -- donc adaptées à sa région, sans dépendre de la couverture ou de
la qualité d'un jeu de données mondial sur une zone donnée (voir le
manuel utilisateur pour une discussion de cette limite chez certains
outils concurrents en Afrique subsaharienne).

Toute combinaison (classe d'occupation du sol, groupe de sol) non prévue
dans la table est explicitement comptabilisée et exclue (nodata) plutôt
que de provoquer un plantage ou une valeur silencieusement fausse.
"""
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

# ---------------------------------------------------------------------------
# Table de correspondance CN standard du NRCS (TR-55, Table 2-2), condition
# hydrologique moyenne. Valeurs largement publiées et non spécifiques à une
# région -- c'est le croisement avec les couches LOCALES fournies par
# l'utilisateur qui rend le résultat adapté au contexte d'étude.
# ---------------------------------------------------------------------------
NRCS_CN_TABLE = {
    "cultures_rangs":      {"A": 67, "B": 78, "C": 85, "D": 89},  # cultures en rangs (maïs, sorgho...)
    "cereales":            {"A": 63, "B": 75, "C": 83, "D": 87},  # céréales / petits grains
    "prairies_paturages":  {"A": 39, "B": 61, "C": 74, "D": 80},  # prairies, pâturages, bonne condition
    "savane_brousse":      {"A": 35, "B": 56, "C": 70, "D": 77},  # brousse/savane arbustive
    "foret":                {"A": 30, "B": 55, "C": 70, "D": 77},  # forêt dense, bonne condition
    "sol_nu":               {"A": 77, "B": 86, "C": 91, "D": 94},  # sol nu / labour à nu
    "zone_residentielle":   {"A": 61, "B": 75, "C": 83, "D": 87},  # habitat diffus (~38% imperméable)
    "zone_urbaine_dense":   {"A": 89, "B": 92, "C": 94, "D": 95},  # urbain dense / commercial (~85% imperméable)
    "surface_impermeable":  {"A": 98, "B": 98, "C": 98, "D": 98},  # routes revêtues, parkings, toits
    "piste_non_revetue":    {"A": 72, "B": 82, "C": 87, "D": 89},  # piste en terre compactée
    "plan_eau_zone_humide": {"A": 100, "B": 100, "C": 100, "D": 100},  # eau libre / zone humide
}

CATEGORY_LABELS = {
    "cultures_rangs": "Cultures en rangs (maïs, sorgho, mil...)",
    "cereales": "Céréales / petits grains",
    "prairies_paturages": "Prairies / pâturages",
    "savane_brousse": "Savane / brousse arbustive",
    "foret": "Forêt dense",
    "sol_nu": "Sol nu / labour à nu",
    "zone_residentielle": "Zone résidentielle (habitat diffus)",
    "zone_urbaine_dense": "Zone urbaine dense / commerciale",
    "surface_impermeable": "Surface imperméable (route, parking, toit)",
    "piste_non_revetue": "Piste non revêtue",
    "plan_eau_zone_humide": "Plan d'eau / zone humide",
}

SOIL_GROUPS = ["A", "B", "C", "D"]

SOIL_GROUP_DESCRIPTIONS = {
    "A": "A -- fort potentiel d'infiltration (sables, faible ruissellement)",
    "B": "B -- potentiel d'infiltration modéré",
    "C": "C -- potentiel d'infiltration faible",
    "D": "D -- potentiel d'infiltration très faible (argiles, fort ruissellement)",
}


def read_unique_values(raster_path, band=1, max_values=200):
    """
    Lit les valeurs de pixel distinctes présentes dans un raster (pour
    peupler l'assistant de correspondance). Limite à `max_values` valeurs
    distinctes pour éviter de bloquer l'interface sur un raster continu
    mal choisi par erreur (ex. un MNT au lieu d'une carte d'occupation du sol).

    :return: (liste_valeurs_triees, nodata, tronque: bool)
    """
    ds = gdal.Open(raster_path)
    b = ds.GetRasterBand(band)
    nodata = b.GetNoDataValue()
    arr = b.ReadAsArray()
    if arr is None:
        return [], nodata, False

    values = np.unique(arr)
    if nodata is not None:
        values = values[values != nodata]

    truncated = len(values) > max_values
    values = values[:max_values]
    return [v.item() for v in values], nodata, truncated


def build_cn_raster(land_use_path, soil_group_path, land_use_mapping, soil_group_mapping,
                     output_path, default_cn_for_unmapped=None):
    """
    Construit un raster Curve Number à partir d'une couche d'occupation du
    sol et d'une couche de groupe hydrologique de sol.

    :param land_use_path: chemin du raster d'occupation du sol.
    :param soil_group_path: chemin du raster de groupe hydrologique de sol.
    :param land_use_mapping: dict {valeur_pixel_occupation_sol: clé NRCS_CN_TABLE}.
    :param soil_group_mapping: dict {valeur_pixel_groupe_sol: "A"/"B"/"C"/"D"}.
    :param output_path: chemin du GeoTIFF de sortie (grille alignée sur land_use_path).
    :param default_cn_for_unmapped: si fourni, valeur de CN appliquée aux pixels dont la
        combinaison n'est pas reconnue (occupation du sol ou groupe de sol non mappé),
        au lieu de les laisser en nodata. À utiliser avec prudence : mieux vaut, en
        général, corriger la correspondance plutôt que de forcer une valeur par défaut.
    :return: dict avec :
        - "n_valid" : nb de pixels avec un CN calculé,
        - "n_unmapped_land_use" : nb de pixels dont le code d'occupation du sol
          n'a pas de correspondance dans land_use_mapping,
        - "n_unmapped_soil" : nb de pixels dont le code de groupe de sol n'a pas
          de correspondance dans soil_group_mapping,
        - "unmapped_land_use_codes" / "unmapped_soil_codes" : valeurs brutes
          rencontrées sans correspondance (pour diagnostic).
    """
    land_use_ds = gdal.Open(land_use_path)
    lu_band = land_use_ds.GetRasterBand(1)
    lu_nodata = lu_band.GetNoDataValue()
    lu_arr = lu_band.ReadAsArray()

    gt = land_use_ds.GetGeoTransform()
    proj = land_use_ds.GetProjection()
    x_size = land_use_ds.RasterXSize
    y_size = land_use_ds.RasterYSize

    # Alignement du raster de groupe de sol sur la grille EXACTE de la couche
    # d'occupation du sol (même emprise, même résolution, même SCR) --
    # rééchantillonnage au plus proche voisin pour préserver les codes de
    # classe (une interpolation continue n'aurait aucun sens sur des données
    # catégorielles).
    soil_aligned_ds = gdal.Warp(
        "", soil_group_path, format="MEM",
        outputBounds=(gt[0], gt[3] + gt[5] * y_size, gt[0] + gt[1] * x_size, gt[3]),
        width=x_size, height=y_size,
        dstSRS=proj,
        resampleAlg=gdal.GRA_NearestNeighbour,
    )
    soil_band = soil_aligned_ds.GetRasterBand(1)
    soil_nodata = soil_band.GetNoDataValue()
    soil_arr = soil_band.ReadAsArray()

    cn_arr = np.full(lu_arr.shape, -9999.0, dtype=np.float32)

    valid_mask = np.ones(lu_arr.shape, dtype=bool)
    if lu_nodata is not None:
        valid_mask &= (lu_arr != lu_nodata)
    if soil_nodata is not None:
        valid_mask &= (soil_arr != soil_nodata)

    unmapped_lu_codes = set()
    unmapped_soil_codes = set()
    n_unmapped_lu = 0
    n_unmapped_soil = 0
    n_valid = 0

    lu_codes_present = np.unique(lu_arr[valid_mask]) if valid_mask.any() else []
    soil_codes_present = np.unique(soil_arr[valid_mask]) if valid_mask.any() else []

    # Pré-calcul : pour chaque combinaison (code occupation du sol présent,
    # code groupe de sol présent) réellement rencontrée dans les données,
    # détermine le CN une seule fois (évite de refaire le lookup pixel par
    # pixel, plus rapide sur de grands rasters).
    cn_by_combo = {}
    for lu_code in lu_codes_present:
        category = land_use_mapping.get(lu_code)
        if category is None or category not in NRCS_CN_TABLE:
            unmapped_lu_codes.add(lu_code)
            continue
        for soil_code in soil_codes_present:
            soil_group = soil_group_mapping.get(soil_code)
            if soil_group not in SOIL_GROUPS:
                unmapped_soil_codes.add(soil_code)
                continue
            cn_by_combo[(lu_code, soil_code)] = NRCS_CN_TABLE[category][soil_group]

    for lu_code, soil_code in cn_by_combo:
        combo_mask = valid_mask & (lu_arr == lu_code) & (soil_arr == soil_code)
        n_pixels = int(combo_mask.sum())
        if n_pixels:
            cn_arr[combo_mask] = cn_by_combo[(lu_code, soil_code)]
            n_valid += n_pixels

    if unmapped_lu_codes or unmapped_soil_codes:
        unmapped_mask = valid_mask.copy()
        combo_covered = np.zeros(lu_arr.shape, dtype=bool)
        for lu_code, soil_code in cn_by_combo:
            combo_covered |= (lu_arr == lu_code) & (soil_arr == soil_code)
        unmapped_mask &= ~combo_covered

        n_unmapped = int(unmapped_mask.sum())
        if default_cn_for_unmapped is not None:
            cn_arr[unmapped_mask] = default_cn_for_unmapped
            n_valid += n_unmapped
        # Répartition indicative (un pixel peut cumuler les deux causes) :
        n_unmapped_lu = int(np.isin(lu_arr, list(unmapped_lu_codes)).sum()) if unmapped_lu_codes else 0
        n_unmapped_soil = int(np.isin(soil_arr, list(unmapped_soil_codes)).sum()) if unmapped_soil_codes else 0

    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, x_size, y_size, 1, gdal.GDT_Float32)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(-9999.0)
    out_band.WriteArray(cn_arr)
    out_band.FlushCache()
    out_ds = None

    return {
        "n_valid": n_valid,
        "n_unmapped_land_use": n_unmapped_lu,
        "n_unmapped_soil": n_unmapped_soil,
        "unmapped_land_use_codes": sorted(unmapped_lu_codes),
        "unmapped_soil_codes": sorted(unmapped_soil_codes),
    }
