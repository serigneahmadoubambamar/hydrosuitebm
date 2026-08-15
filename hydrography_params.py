# -*- coding: utf-8 -*-
"""
Calcul des paramètres hydrographiques (réseau de drainage) et
hydrologiques (temps de concentration) d'un bassin versant.
"""
import math
from collections import deque


def longest_flow_path_km(streams_layer, outlet_pt, precision=2):
    """
    Calcule la longueur du plus long chemin hydraulique (talweg principal),
    c'est-à-dire la distance parcourue par une goutte d'eau depuis le point
    le plus hydrauliquement éloigné du bassin jusqu'à l'exutoire, EN SUIVANT
    le réseau hydrographique (et non une distance à vol d'oiseau).

    C'est le L à utiliser dans les formules de temps de concentration
    (Kirpich, Giandotti, Passini, Ventura), par opposition à la longueur
    géométrique du bassin (axe outlet -> sommet le plus éloigné du contour),
    qui elle sert au calcul de l'indice d'allongement de Schumm.

    Principe : le réseau hydrographique découpé sur le bassin forme un
    graphe (quasi) arborescent, enraciné à l'exutoire (pas de boucles pour
    un réseau dérivé d'une direction de flux D8/MFD). On construit ce graphe
    (nœuds = extrémités de tronçons, arêtes = tronçons pondérés par leur
    longueur), on relie l'exutoire donné au nœud du graphe le plus proche,
    puis on cherche par parcours en largeur (BFS) le nœud le plus distant
    de l'exutoire -- la distance jusqu'à ce nœud est le L recherché.

    :param streams_layer: QgsVectorLayer (lignes) du réseau, déjà découpé
        sur le bassin.
    :param outlet_pt: QgsPointXY de l'exutoire du bassin.
    :return: longueur en km, ou None si non calculable (pas de réseau).
    """
    if streams_layer is None or streams_layer.featureCount() == 0 or outlet_pt is None:
        return None

    def node_key(pt):
        return (round(pt.x(), precision), round(pt.y(), precision))

    edges = {}
    nodes_coords = {}

    for feat in streams_layer.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
        for part in parts:
            if len(part) < 2:
                continue
            seg_len = 0.0
            for i in range(len(part) - 1):
                seg_len += math.hypot(part[i].x() - part[i + 1].x(), part[i].y() - part[i + 1].y())
            if seg_len <= 0:
                continue
            k1, k2 = node_key(part[0]), node_key(part[-1])
            nodes_coords.setdefault(k1, part[0])
            nodes_coords.setdefault(k2, part[-1])
            edges.setdefault(k1, []).append((k2, seg_len))
            edges.setdefault(k2, []).append((k1, seg_len))

    if not nodes_coords:
        return None

    # Nœud du graphe le plus proche de l'exutoire fourni (le point calé/trouvé
    # ne tombe pas forcément exactement sur un nœud du vecteur du réseau).
    outlet_key = min(
        nodes_coords.keys(),
        key=lambda k: math.hypot(k[0] - outlet_pt.x(), k[1] - outlet_pt.y()),
    )

    # BFS depuis l'exutoire : dans un arbre, chaque nœud n'a qu'un seul chemin
    # possible depuis la racine, donc la première visite donne la distance finale.
    dist = {outlet_key: 0.0}
    queue = deque([outlet_key])
    while queue:
        node = queue.popleft()
        d0 = dist[node]
        for neighbor, w in edges.get(node, []):
            if neighbor not in dist:
                dist[neighbor] = d0 + w
                queue.append(neighbor)

    if not dist:
        return None
    return max(dist.values()) / 1000.0


def drainage_density(total_stream_length_km, area_km2):
    """Densité de drainage Dd = somme des longueurs des cours d'eau / surface (km/km2)"""
    if not area_km2:
        return None
    return total_stream_length_km / area_km2


def stream_frequency(n_streams, area_km2):
    """Fréquence des cours d'eau F = nombre de tronçons / surface (n/km2)"""
    if not area_km2:
        return None
    return n_streams / area_km2


def bifurcation_ratio(counts_by_order):
    """
    Rapport de confluence moyen (Horton) : Rb = Nu / Nu+1, moyenné sur les ordres.
    :param counts_by_order: dict {ordre_int: nombre_de_troncons}
    :return: rapport moyen
    """
    orders = sorted(counts_by_order.keys())
    if len(orders) < 2:
        return None
    ratios = []
    for i in range(len(orders) - 1):
        n_u = counts_by_order[orders[i]]
        n_u1 = counts_by_order[orders[i + 1]]
        if n_u1 > 0:
            ratios.append(n_u / n_u1)
    return sum(ratios) / len(ratios) if ratios else None


def length_ratio(lengths_by_order):
    """
    Rapport de longueur moyen (Horton) : Rl = Lu+1 / Lu, moyenné sur les ordres.
    :param lengths_by_order: dict {ordre_int: longueur_cumulee_km}
    """
    orders = sorted(lengths_by_order.keys())
    if len(orders) < 2:
        return None
    ratios = []
    for i in range(len(orders) - 1):
        l_u = lengths_by_order[orders[i]]
        l_u1 = lengths_by_order[orders[i + 1]]
        if l_u > 0:
            ratios.append(l_u1 / l_u)
    return sum(ratios) / len(ratios) if ratios else None


def compute_network_stats(clipped_streams_layer, area_km2, order_field_candidates=("strahler", "strahler_o", "strahle")):
    """
    Calcule l'ensemble des statistiques du réseau hydrographique découpé sur
    un bassin : longueur totale, longueur par ordre, nombre de tronçons par
    ordre, densité de drainage, fréquence, rapports de confluence et de
    longueur de Horton.

    :param clipped_streams_layer: QgsVectorLayer (lignes) découpée sur le bassin,
        attribuée par un champ d'ordre de Strahler (produit par
        delineation.stream_order_network / clip_streams_to_basin).
    :param area_km2: superficie du bassin (km2)
    :param order_field_candidates: noms de champ possibles pour l'ordre de
        Strahler selon la version de GRASS utilisée.
    :return: dict de statistiques.
    """
    if clipped_streams_layer is None or clipped_streams_layer.featureCount() == 0:
        return {
            "longueur_reseau_km": 0.0,
            "nb_troncons": 0,
            "densite_drainage_km_par_km2": 0.0,
            "frequence_cours_deau_par_km2": 0.0,
        }

    existing_fields = [f.name() for f in clipped_streams_layer.fields()]
    order_field = next((f for f in order_field_candidates if f in existing_fields), None)

    total_length_m = 0.0
    n_streams = 0
    lengths_by_order = {}
    counts_by_order = {}

    for feat in clipped_streams_layer.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        length_m = geom.length()
        total_length_m += length_m
        n_streams += 1

        if order_field:
            try:
                order = int(feat[order_field])
            except (TypeError, ValueError):
                order = None
            if order is not None:
                lengths_by_order[order] = lengths_by_order.get(order, 0.0) + length_m / 1000.0
                counts_by_order[order] = counts_by_order.get(order, 0) + 1

    total_length_km = total_length_m / 1000.0

    stats = {
        "longueur_reseau_km": total_length_km,
        "nb_troncons": n_streams,
        "densite_drainage_km_par_km2": drainage_density(total_length_km, area_km2),
        "frequence_cours_deau_par_km2": stream_frequency(n_streams, area_km2),
    }

    if lengths_by_order:
        ordre_max = max(lengths_by_order.keys())
        stats["ordre_strahler_max"] = ordre_max
        stats["longueur_par_ordre_km"] = dict(sorted(lengths_by_order.items()))
        stats["nb_troncons_par_ordre"] = dict(sorted(counts_by_order.items()))
        stats["rapport_confluence_moyen_Rb"] = bifurcation_ratio(counts_by_order)
        stats["rapport_longueur_moyen_Rl"] = length_ratio(lengths_by_order)

    return stats


# ---------------------------------------------------------------------------
# Temps de concentration (plusieurs formules empiriques usuelles)
# ---------------------------------------------------------------------------

def tc_kirpich(length_talweg_km, slope_m_per_m):
    """
    Formule de Kirpich (min). L en km, pente moyenne du talweg en m/m.
    Tc = 0.01947 * L^0.77 * S^-0.385   (L en m dans la formule originale ;
    ici on convertit L (km) -> m avant application).
    """
    if not slope_m_per_m or slope_m_per_m <= 0:
        return None
    L_m = length_talweg_km * 1000.0
    return 0.01947 * (L_m ** 0.77) * (slope_m_per_m ** -0.385)


def tc_giandotti(area_km2, length_talweg_km, hmean_m, hmin_m):
    """
    Formule de Giandotti (heures).
    Tc = (4*sqrt(A) + 1.5*L) / (0.8*sqrt(Hmoy - Hmin))
    A en km2, L en km, altitudes en m.
    """
    denom = 0.8 * math.sqrt(max(hmean_m - hmin_m, 0.001))
    if denom == 0:
        return None
    return (4 * math.sqrt(area_km2) + 1.5 * length_talweg_km) / denom


def tc_passini(area_km2, length_talweg_km, slope_m_per_m):
    """
    Formule de Passini (heures).
    Tc = (0.108 * (A*L)^(1/3)) / sqrt(S)
    A en km2, L en km, S pente moyenne en m/m.
    """
    if not slope_m_per_m or slope_m_per_m <= 0:
        return None
    return (0.108 * (area_km2 * length_talweg_km) ** (1 / 3)) / math.sqrt(slope_m_per_m)


def tc_ventura(area_km2, slope_m_per_m):
    """
    Formule de Ventura (heures).
    Tc = 0.1272 * sqrt(A / S)
    """
    if not slope_m_per_m or slope_m_per_m <= 0:
        return None
    return 0.1272 * math.sqrt(area_km2 / slope_m_per_m)


def scs_retention_s_mm(curve_number):
    """
    Rétention potentielle maximale S (méthode SCS-CN), en mm.
    S = 25400/CN - 254   (équivalent métrique de S = 1000/CN - 10, en pouces)
    """
    if not curve_number or curve_number <= 0 or curve_number > 100:
        return None
    return 25400.0 / curve_number - 254.0


def tc_scs_lag(length_talweg_km, curve_number, slope_pct):
    """
    Temps de concentration par la méthode SCS (méthode du "lag time" du
    Natural Resources Conservation Service / Soil Conservation Service,
    formule TR-55) -- résultat en heures.

    Tl (temps de décalage, h) = L^0.8 * (S+1)^0.7 / (1900 * Y^0.5)
        L = longueur hydraulique du bassin, en PIEDS
        S = rétention potentielle max, en POUCES = 1000/CN - 10
        Y = pente moyenne du bassin, en %
    Tc = Tl / 0.6   (relation usuelle Tl ≈ 0.6 * Tc du NRCS)

    :param length_talweg_km: longueur du talweg principal (km)
    :param curve_number: Curve Number moyen pondéré du bassin (0-100)
    :param slope_pct: pente moyenne du bassin (%)
    :return: Tc en heures, ou None si un paramètre est invalide/manquant.
    """
    if not length_talweg_km or not slope_pct or slope_pct <= 0:
        return None
    if not curve_number or curve_number <= 0 or curve_number >= 100:
        return None

    L_ft = length_talweg_km * 3280.8399  # km -> pieds
    S_in = 1000.0 / curve_number - 10.0  # pouces (formule US originale, volontairement gardée en unités impériales)
    Y_pct = slope_pct

    Tl_h = (L_ft ** 0.8) * ((S_in + 1) ** 0.7) / (1900.0 * (Y_pct ** 0.5))
    return Tl_h / 0.6


# ---------------------------------------------------------------------------
# Domaine de validité usuel des formules de Tc (ordres de grandeur -- les
# seuils varient selon les sources ; à utiliser comme repère indicatif, pas
# comme règle stricte).
# ---------------------------------------------------------------------------
TC_VALIDITY_DOMAINS_KM2 = {
    "Kirpich": (0.004, 1.0),
    "SCS (lag)": (0.01, 8.0),
    "Ventura": (0.5, 700.0),
    "Passini": (0.5, 700.0),
    "Giandotti": (1.7, 700.0),
}


def recommend_tc_formula(area_km2):
    """
    Évalue, pour la surface donnée, quelles formules de Tc sont dans leur
    domaine de validité usuel, et propose la formule la plus adaptée.

    :return: dict {
        "in_domain": [noms de formules dans leur domaine usuel],
        "out_of_domain": [noms de formules hors domaine usuel],
        "recommended": nom de la formule recommandée (la plus étroitement
            calée pour cette gamme de surface parmi celles en domaine), ou None
    }
    """
    if not area_km2 or area_km2 <= 0:
        return {"in_domain": [], "out_of_domain": list(TC_VALIDITY_DOMAINS_KM2.keys()), "recommended": None}

    in_domain, out_of_domain = [], []
    for name, (amin, amax) in TC_VALIDITY_DOMAINS_KM2.items():
        if amin <= area_km2 <= amax:
            in_domain.append(name)
        else:
            out_of_domain.append(name)

    recommended = None
    if in_domain:
        # Parmi les formules en domaine, on privilégie celle dont la plage de
        # calage est la plus étroite / la plus proche de l'échelle du bassin
        # (une formule à domaine large est moins spécifique qu'une formule
        # à domaine ciblé qui inclut cette surface).
        def span_and_centering(name):
            amin, amax = TC_VALIDITY_DOMAINS_KM2[name]
            span = math.log10(amax / amin) if amin > 0 else float("inf")
            return span
        recommended = min(in_domain, key=span_and_centering)

    return {"in_domain": in_domain, "out_of_domain": out_of_domain, "recommended": recommended}


# ---------------------------------------------------------------------------
# Débit de pointe - méthode rationnelle (optionnelle, nécessite intensité pluie)
# ---------------------------------------------------------------------------

def peak_flow_rational(runoff_coefficient, rainfall_intensity_mm_h, area_km2):
    """
    Méthode rationnelle : Q = C * I * A / 3.6  (Q en m3/s, I en mm/h, A en km2)
    """
    if None in (runoff_coefficient, rainfall_intensity_mm_h, area_km2):
        return None
    return runoff_coefficient * rainfall_intensity_mm_h * area_km2 / 3.6
