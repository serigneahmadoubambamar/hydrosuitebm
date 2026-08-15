# -*- coding: utf-8 -*-
"""
Export des résultats calculés : CSV, couche combinée de tous les bassins
(avec table attributaire), et légende des champs abrégés (contrainte
Shapefile : noms de champs limités à 10 caractères).
"""
import csv
from qgis.core import QgsField, QgsFeature, QgsVectorLayer
from qgis.PyQt.QtCore import QVariant

# Correspondance nom_complet_du_paramètre -> nom de champ abrégé (<=10
# caractères, unique en ignorant la casse -- contrainte du format DBF des
# Shapefiles). L'ordre de ce dict fixe l'ordre des colonnes dans la couche.
FIELD_ALIASES = {
    "surface_m2": "SURF_M2",
    "surface_km2": "SURF_KM2",
    "perimetre_m": "PERIM_M",
    "perimetre_km": "PERIM_KM",
    "indice_compacite_gravelius_Kc": "KC_GRAVEL",
    "rectangle_equivalent_L_km": "RECT_LNG",
    "rectangle_equivalent_l_km": "RECT_LRG",
    "indice_circularite_miller_Rc": "RC_MILLER",
    "longueur_bassin_km": "LNG_BASS",
    "indice_allongement_schumm_Re": "RE_SCHUMM",
    "pente_moyenne_pct": "PENTE_PCT",
    "altitude_min_m": "ALT_MIN",
    "altitude_max_m": "ALT_MAX",
    "altitude_moyenne_m": "ALT_MOY",
    "altitude_mediane_m": "ALT_MED",
    "denivelee_m": "DENIV_M",
    "integrale_hypsometrique_Hi": "HI_HYPSO",
    "indice_pente_globale_Ig_m_par_km": "IG_PENTE",
    "denivelee_specifique_Ds": "DS_SPEC",
    "longueur_reseau_km": "LNG_RESO",
    "nb_troncons": "NB_TRONC",
    "densite_drainage_km_par_km2": "DENS_DRAI",
    "frequence_cours_deau_par_km2": "FREQ_COUR",
    "ordre_strahler_max": "ORD_STRAH",
    "rapport_confluence_moyen_Rb": "RB_CONFLU",
    "rapport_longueur_moyen_Rl": "RL_LONG",
    "longueur_talweg_km": "LNG_TALW",
    "longueur_utilisee_pour_tc_km": "LNG_TC",
    "tc_kirpich_min": "TC_KIRP_M",
    "tc_giandotti_h": "TC_GIAN_H",
    "tc_passini_h": "TC_PASS_H",
    "tc_ventura_h": "TC_VENT_H",
    "curve_number_cn": "CN_MOYEN",
    "retention_potentielle_S_mm": "S_RETENT",
    "tc_scs_h": "TC_SCS_H",
}

FIELD_DESCRIPTIONS = {
    "SURF_M2": "Surface du bassin (m²)",
    "SURF_KM2": "Surface du bassin (km²)",
    "PERIM_M": "Périmètre du bassin (m)",
    "PERIM_KM": "Périmètre du bassin (km)",
    "KC_GRAVEL": "Indice de compacité de Gravelius (Kc)",
    "RECT_LNG": "Longueur du rectangle équivalent (km)",
    "RECT_LRG": "Largeur du rectangle équivalent (km)",
    "RC_MILLER": "Indice de circularité de Miller (Rc)",
    "LNG_BASS": "Longueur géométrique du bassin, axe exutoire -> point le plus éloigné (km) -- utilisée pour l'indice de Schumm",
    "RE_SCHUMM": "Indice d'allongement de Schumm (Re)",
    "PENTE_PCT": "Pente moyenne du bassin (%)",
    "ALT_MIN": "Altitude minimale (m)",
    "ALT_MAX": "Altitude maximale (m)",
    "ALT_MOY": "Altitude moyenne (m)",
    "ALT_MED": "Altitude médiane (m)",
    "DENIV_M": "Dénivelée du bassin (m)",
    "HI_HYPSO": "Intégrale hypsométrique (Hi)",
    "IG_PENTE": "Indice de pente globale (Ig, m/km)",
    "DS_SPEC": "Dénivelée spécifique (Ds)",
    "LNG_RESO": "Longueur totale du réseau hydrographique dans le bassin (km)",
    "NB_TRONC": "Nombre de tronçons du réseau",
    "DENS_DRAI": "Densité de drainage (km/km²)",
    "FREQ_COUR": "Fréquence des cours d'eau (nb/km²)",
    "ORD_STRAH": "Ordre de Strahler maximal du réseau",
    "RB_CONFLU": "Rapport de confluence moyen de Horton (Rb)",
    "RL_LONG": "Rapport de longueur moyen de Horton (Rl)",
    "LNG_TALW": "Longueur du talweg principal = plus long chemin hydraulique le long du réseau (km)",
    "LNG_TC": "Longueur (L) effectivement utilisée pour les temps de concentration (km) : talweg si disponible, sinon longueur géométrique en repli",
    "TC_KIRP_M": "Temps de concentration, formule de Kirpich (minutes)",
    "TC_GIAN_H": "Temps de concentration, formule de Giandotti (heures)",
    "TC_PASS_H": "Temps de concentration, formule de Passini (heures)",
    "TC_VENT_H": "Temps de concentration, formule de Ventura (heures)",
    "CN_MOYEN": "Curve Number (CN) moyen pondéré du bassin (méthode SCS-CN)",
    "S_RETENT": "Rétention potentielle maximale S (méthode SCS-CN, mm)",
    "TC_SCS_H": "Temps de concentration, méthode SCS (lag method, TR-55, heures)",
}


def build_basins_layer(basin_records, crs, id_field_name="ID_BASSIN"):
    """
    Construit UNE SEULE couche polygone regroupant tous les bassins, avec un
    champ identifiant + un champ par paramètre calculé (noms abrégés, <=10
    caractères pour compatibilité Shapefile).

    :param basin_records: liste de tuples (basin_id: str, geometry: QgsGeometry, results: dict)
    :param crs: QgsCoordinateReferenceSystem des géométries fournies
    :return: (QgsVectorLayer, liste des clés complètes effectivement utilisées)
    """
    layer = QgsVectorLayer(f"Polygon?crs={crs.authid()}", "bassins_versants", "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(id_field_name, QVariant.String, len=50)])

    used_keys = []
    for _, _, results in basin_records:
        for k in results:
            if k in FIELD_ALIASES and k not in used_keys:
                used_keys.append(k)

    provider.addAttributes([QgsField(FIELD_ALIASES[k], QVariant.Double) for k in used_keys])
    layer.updateFields()

    feats = []
    for basin_id, geom, results in basin_records:
        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        attrs = [basin_id]
        for k in used_keys:
            v = results.get(k)
            attrs.append(float(v) if isinstance(v, (int, float)) else None)
        feat.setAttributes(attrs)
        feats.append(feat)

    provider.addFeatures(feats)
    layer.updateExtents()
    return layer, used_keys


def write_field_legend(used_keys, csv_path, id_field_name="ID_BASSIN"):
    """Écrit un fichier CSV expliquant à quoi correspond chaque champ abrégé du shapefile."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["champ_shapefile", "nom_complet_du_parametre", "description"])
        writer.writerow([id_field_name, "identifiant_bassin", "Identifiant unique du bassin ou sous-bassin"])
        for k in used_keys:
            alias = FIELD_ALIASES[k]
            writer.writerow([alias, k, FIELD_DESCRIPTIONS.get(alias, "")])


def build_combined_lines_layer(records, crs, id_field_name="ID_BASSIN"):
    """
    Fusionne les réseaux hydrographiques découpés de plusieurs bassins en
    UNE SEULE couche ligne, avec un champ identifiant le bassin d'origine
    de chaque tronçon. Les champs d'origine (ex. 'strahler', 'horton'...
    produits par r.stream.order, ou 'value' par r.to.vect) sont conservés,
    en tronquant leurs noms à 10 caractères si besoin (contrainte Shapefile),
    avec suffixe numérique en cas de collision après troncature.

    :param records: liste de tuples (basin_id: str, streams_layer: QgsVectorLayer ou None)
    :return: QgsVectorLayer (lignes) ou None si `records` est vide.
    """
    if not records:
        return None

    layer = QgsVectorLayer(f"LineString?crs={crs.authid()}", "reseaux_hydrographiques", "memory")
    provider = layer.dataProvider()
    provider.addAttributes([QgsField(id_field_name, QVariant.String, len=50)])

    # Union des champs des couches sources -> nom de champ abrégé unique.
    field_map = {}  # nom_original -> QgsField (nom éventuellement tronqué)
    used_names = {id_field_name.lower()}
    for _, src_layer in records:
        if src_layer is None:
            continue
        for f in src_layer.fields():
            if f.name() in field_map:
                continue
            short = f.name()[:10]
            base, i = short, 1
            while short.lower() in used_names:
                suffix = str(i)
                short = base[: 10 - len(suffix)] + suffix
                i += 1
            used_names.add(short.lower())
            field_map[f.name()] = QgsField(short, f.type())

    provider.addAttributes(list(field_map.values()))
    layer.updateFields()

    feats_out = []
    for basin_id, src_layer in records:
        if src_layer is None:
            continue
        for feat in src_layer.getFeatures():
            new_feat = QgsFeature(layer.fields())
            new_feat.setGeometry(feat.geometry())
            attrs = [basin_id]
            for orig_name in field_map:
                idx = feat.fields().indexFromName(orig_name)
                attrs.append(feat[idx] if idx != -1 else None)
            new_feat.setAttributes(attrs)
            feats_out.append(new_feat)

    if feats_out:
        provider.addFeatures(feats_out)
    layer.updateExtents()
    return layer


def flatten_results(results_dict):
    """
    Aplati un dict de résultats (potentiellement imbriqué, ex. courbe
    hypsométrique = liste de tuples) en paires clé/valeur exportables en CSV
    et en table attributaire.
    """
    flat = {}
    for k, v in results_dict.items():
        if isinstance(v, dict):
            # petits dicts (ex. longueur_par_ordre_km = {1: 3.2, 2: 1.1, ...})
            # -> conservés sous forme de chaîne compacte plutôt que supprimés
            flat[k] = "; ".join(f"{ok}:{ov:.2f}" if isinstance(ov, float) else f"{ok}:{ov}"
                                 for ok, ov in sorted(v.items()))
        elif isinstance(v, (list, tuple)):
            continue  # séries longues (ex. courbe hypsométrique) exportées à part
        else:
            flat[k] = v
    return flat


def export_to_csv(basin_name, results_dict, csv_path):
    """Ajoute/écrit une ligne de résultats pour un bassin donné dans un CSV."""
    flat = flatten_results(results_dict)
    fieldnames = ["bassin"] + list(flat.keys())
    write_header = True
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            write_header = False
    except FileNotFoundError:
        pass

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        row = {"bassin": basin_name}
        row.update(flat)
        writer.writerow(row)


def add_results_to_layer(vector_layer, feature_id, results_dict):
    """
    Ajoute les champs manquants à la couche et remplit les valeurs pour
    l'entité (bassin) correspondante.
    """
    flat = flatten_results(results_dict)
    provider = vector_layer.dataProvider()
    existing_fields = [f.name() for f in vector_layer.fields()]

    new_fields = []
    for key, val in flat.items():
        if key not in existing_fields:
            field_type = QVariant.Double if isinstance(val, (int, float)) else QVariant.String
            new_fields.append(QgsField(key[:10], field_type))  # 10 car. max (shapefile)

    if new_fields:
        provider.addAttributes(new_fields)
        vector_layer.updateFields()

    vector_layer.startEditing()
    feat = vector_layer.getFeature(feature_id)
    for key, val in flat.items():
        idx = vector_layer.fields().indexFromName(key[:10])
        if idx != -1:
            vector_layer.changeAttributeValue(feat.id(), idx, val)
    vector_layer.commitChanges()
