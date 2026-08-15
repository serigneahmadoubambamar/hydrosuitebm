# -*- coding: utf-8 -*-
"""
Calcul des paramètres géométriques d'un bassin versant à partir de sa
géométrie polygonale (surface projetée, en mètres).
"""
import math


def geometric_parameters(area_m2, perimeter_m):
    """
    Calcule les paramètres géométriques classiques d'un bassin versant.

    :param area_m2: superficie du bassin (m2)
    :param perimeter_m: périmètre du bassin (m)
    :return: dict des paramètres
    """
    area_km2 = area_m2 / 1e6
    perimeter_km = perimeter_m / 1000.0

    # Indice de compacité de Gravelius : Kc = 0.28 * P / sqrt(A)  (P en km, A en km2)
    kc = 0.28 * perimeter_km / math.sqrt(area_km2) if area_km2 > 0 else None

    # Rectangle équivalent (L, l) tel que L*l = A et 2(L+l) = P
    # L = Kc*sqrt(A)/1.12 * (1 + sqrt(1-(1.12/Kc)^2))
    L_eq = l_eq = None
    if kc and kc >= 1.0:
        try:
            racine = 1 - (1.12 / kc) ** 2
            racine = max(racine, 0)
            L_eq = (kc * math.sqrt(area_km2) / 1.12) * (1 + math.sqrt(racine))
            l_eq = area_km2 / L_eq if L_eq else None
        except (ValueError, ZeroDivisionError):
            L_eq = l_eq = None

    # Indice d'allongement de Schumm : Re = 1.128 * sqrt(A) / Lmax
    # (Lmax = longueur du bassin, à fournir séparément, voir basin_length)

    # Indice de circularité de Miller : Rc = A / A_cercle_meme_perimetre
    rc = (4 * math.pi * area_m2) / (perimeter_m ** 2) if perimeter_m > 0 else None

    return {
        "surface_m2": area_m2,
        "surface_km2": area_km2,
        "perimetre_m": perimeter_m,
        "perimetre_km": perimeter_km,
        "indice_compacite_gravelius_Kc": kc,
        "rectangle_equivalent_L_km": L_eq,
        "rectangle_equivalent_l_km": l_eq,
        "indice_circularite_miller_Rc": rc,
    }


def elongation_ratio(area_km2, basin_length_km):
    """Indice d'allongement de Schumm : Re = 1.128 * sqrt(A) / Lb"""
    if not basin_length_km:
        return None
    return 1.128 * math.sqrt(area_km2) / basin_length_km


def basin_length_from_geometry(geom, outlet_point=None):
    """
    Estime la longueur du bassin (Lb) comme la plus grande distance entre
    l'exutoire et un sommet du polygone (à défaut d'un tracé de talweg).
    Si un point exutoire est fourni, calcule la distance maximale depuis
    ce point vers le contour du bassin ; sinon utilise la plus grande
    distance entre deux sommets (diamètre du polygone), approximation.

    :param geom: QgsGeometry (polygone du bassin)
    :param outlet_point: QgsPointXY ou None
    :return: longueur en mètres
    """
    vertices = [v for v in geom.vertices()]
    if not vertices:
        return None

    def dist(p1, p2):
        return math.hypot(p1.x() - p2.x(), p1.y() - p2.y())

    if outlet_point is not None:
        return max(dist(outlet_point, v) for v in vertices)

    # Sinon : diamètre approximatif (O(n^2), acceptable pour un contour de bassin)
    max_d = 0.0
    for i in range(len(vertices)):
        for j in range(i + 1, len(vertices)):
            d = dist(vertices[i], vertices[j])
            if d > max_d:
                max_d = d
    return max_d
