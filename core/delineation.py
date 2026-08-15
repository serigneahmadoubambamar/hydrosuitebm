# -*- coding: utf-8 -*-
"""
Délimitation automatique de bassin(s) versant(s) et extraction du réseau
hydrographique à partir d'un MNT, en s'appuyant sur les algorithmes
'processing' du fournisseur GRASS (à activer dans QGIS : Extensions >
Gérer les extensions > provider GRASS actif). Le préfixe exact du
fournisseur ("grass", "grass7" ou "grass8" selon la version de GRASS
installée) est détecté automatiquement par _grass_provider_prefix().

Chaîne de traitement :
  1. Comblement des dépressions du MNT       -> r.fill.dir
  2. Direction / accumulation de flux        -> r.watershed
  3. Extraction du réseau hydrographique     -> r.stream.extract
  4. Vectorisation + ordre de Strahler       -> r.stream.order
  5. Calage (snap) des exutoires sur réseau  -> r.stream.snap
  6. Délimitation du bassin depuis exutoire  -> r.water.outlet
  7. Vectorisation du bassin                 -> gdal:polygonize
  8. Découpage du réseau sur le bassin       -> native:clip

Remarque : les noms exacts de certains paramètres GRASS (stream_vector,
stream_vect...) peuvent varier légèrement selon la version de GRASS
(7.8 vs 8.x) installée avec QGIS. En cas d'erreur "paramètre inconnu",
ouvrez l'algorithme correspondant dans la boîte à outils Traitement pour
vérifier le nom exact et ajustez la clé du dict `params` ci-dessous.
"""
import processing
from qgis.core import (
    QgsRasterLayer,
    QgsVectorLayer,
    QgsProject,
    QgsPointXY,
    QgsApplication,
    QgsRectangle,
    QgsFeature,
    QgsGeometry,
    QgsField,
)
from qgis.PyQt.QtCore import QVariant

# QGIS a renommé le fournisseur GRASS selon les versions : "grass7" pour les
# anciennes installations (GRASS 7.x), "grass" (parfois "grass8") lorsque
# GRASS 8 est installé. On détecte automatiquement le bon préfixe au lieu de
# le coder en dur, pour que le plugin fonctionne quelle que soit la version
# de GRASS présente sur le poste de l'utilisateur.
_GRASS_PREFIX_CACHE = {"prefix": None}
_GRASS_PREFIX_CANDIDATES = ["grass", "grass7", "grass8"]


def _grass_provider_prefix():
    if _GRASS_PREFIX_CACHE["prefix"] is not None:
        return _GRASS_PREFIX_CACHE["prefix"]
    registry = QgsApplication.processingRegistry()
    for prefix in _GRASS_PREFIX_CANDIDATES:
        if registry.providerById(prefix) is not None:
            _GRASS_PREFIX_CACHE["prefix"] = prefix
            return prefix
    _GRASS_PREFIX_CACHE["prefix"] = "grass7"  # valeur par défaut si rien n'est détecté
    return "grass7"


def _run_grass(alg_short_name, params):
    """
    Exécute un algorithme GRASS (ex. 'r.fill.dir') en préfixant automatiquement
    avec le bon fournisseur ('grass', 'grass7' ou 'grass8'). Si le préfixe
    détecté échoue (algorithme introuvable), on retente avec les autres
    préfixes possibles avant d'abandonner.
    """
    prefix = _grass_provider_prefix()
    try:
        return processing.run(f"{prefix}:{alg_short_name}", params)
    except Exception:
        for alt in _GRASS_PREFIX_CANDIDATES:
            if alt == prefix:
                continue
            try:
                result = processing.run(f"{alt}:{alg_short_name}", params)
                _GRASS_PREFIX_CACHE["prefix"] = alt
                return result
            except Exception:
                continue
        raise


def _as_vector_layer(output, name):
    """
    Certains algorithmes 'native:' de QGIS renvoient directement l'objet
    QgsVectorLayer déjà chargé dans le dict résultat (au lieu d'un simple
    chemin de fichier), selon le contexte d'exécution. On distingue les deux
    cas via le type Python (chaîne = chemin à charger, sinon objet déjà
    utilisable) plutôt que isinstance(), pour éviter l'erreur
    "QgsVectorLayer(): argument 1 has unexpected type 'QgsVectorLayer'".
    """
    if isinstance(output, (str, bytes)):
        return QgsVectorLayer(output, name, "ogr")
    # Déjà un objet couche chargé -> on le renomme et on le renvoie tel quel.
    try:
        output.setName(name)
    except Exception:
        pass
    return output


def _as_raster_layer(output, name):
    """Équivalent de _as_vector_layer() pour les sorties raster."""
    if isinstance(output, (str, bytes)):
        return QgsRasterLayer(output, name)
    try:
        output.setName(name)
    except Exception:
        pass
    return output


def fill_sinks(dem_layer, output=None):
    """Comble les dépressions du MNT (pré-requis pour un flux hydrologiquement cohérent)."""
    output = output or "TEMPORARY_OUTPUT"
    params = {
        "input": dem_layer,
        "format": 1,  # 1 = single flow direction (D8)
        "output": output,
        "direction": "TEMPORARY_OUTPUT",
        "areas": "TEMPORARY_OUTPUT",
    }
    result = _run_grass("r.fill.dir", params)
    return _as_raster_layer(result["output"], "dem_filled")


def flow_direction_accumulation(filled_dem_layer, threshold=None, sfd=False):
    """
    Calcule l'accumulation et la direction de flux.
    Si `threshold` est fourni, demande en plus à r.watershed sa sortie
    'basin' : GRASS découpe alors AUTOMATIQUEMENT tout le MNT en sous-bassins
    versants (un identifiant unique par sous-bassin), sans avoir besoin de
    points exutoires. Renvoie (accumulation, drainage, basin_ou_None).

    `sfd` : si True, force l'algorithme SFD (direction de flux unique, plus
    rapide mais peut fusionner beaucoup de sous-bassins en de très grandes
    zones). Par défaut (False), r.watershed utilise son algorithme MFD
    (directions de flux multiples) -- c'est le comportement PAR DÉFAUT de
    r.watershed lorsqu'on le lance depuis la boîte à outils Traitement, et
    celui qui donne un découpage en sous-bassins comparable à un lancement
    manuel de r.watershed.
    """
    params = {
        "elevation": filled_dem_layer,
        "accumulation": "TEMPORARY_OUTPUT",
        "drainage": "TEMPORARY_OUTPUT",
    }
    if sfd:
        params["-s"] = True
    basin_layer = None
    if threshold:
        params["threshold"] = threshold
        params["basin"] = "TEMPORARY_OUTPUT"
    result = _run_grass("r.watershed", params)
    accumulation = _as_raster_layer(result["accumulation"], "accumulation")
    drainage = _as_raster_layer(result["drainage"], "drainage")
    if threshold and result.get("basin"):
        basin_layer = _as_raster_layer(result["basin"], "basins_auto")
    return accumulation, drainage, basin_layer


def extract_stream_network(filled_dem_layer, accumulation_layer, threshold):
    """
    Extrait le réseau hydrographique par seuillage de l'accumulation de flux.
    Le seuil (threshold, en nombre de cellules amont) contrôle la densité
    du réseau extrait : plus il est faible, plus le réseau est dense.
    Renvoie (stream_raster, stream_direction).
    """
    params = {
        "elevation": filled_dem_layer,
        "accumulation": accumulation_layer,
        "threshold": threshold,
        "stream_raster": "TEMPORARY_OUTPUT",
        "direction": "TEMPORARY_OUTPUT",
    }
    result = _run_grass("r.stream.extract", params)
    stream_raster = _as_raster_layer(result["stream_raster"], "stream_raster")
    stream_direction = _as_raster_layer(result["direction"], "stream_direction")
    return stream_raster, stream_direction


def stream_order_network(filled_dem_layer, accumulation_layer, stream_raster_layer, stream_direction_layer):
    """
    Calcule les ordres de classification du réseau (Strahler, Horton, Shreve,
    Hack) et renvoie une couche VECTEUR ligne attribuée (colonnes strahler,
    horton, shreve, hack...), via r.stream.order.

    r.stream.order fait partie de l'extension GRASS "r.stream.*" (paquet
    d'addons de Jarek Jasiewicz), qui n'est PAS installée par défaut avec
    GRASS -- contrairement à r.watershed, r.stream.extract ou r.fill.dir qui
    sont des modules du cœur de GRASS. Si elle n'est pas installée, on
    bascule automatiquement sur r.to.vect (module du cœur de GRASS, toujours
    disponible) : le réseau est alors récupéré SANS ordre de Strahler -- la
    densité de drainage et la fréquence des cours d'eau restent calculables,
    mais pas les rapports de Horton (Rb, Rl).

    Pour activer le calcul complet avec ordre de Strahler, installez
    l'extension depuis QGIS (Traitement > Boîte à outils > GRASS) ou une
    console GRASS :
        g.extension extension=r.stream.order

    Renvoie (couche_reseau, ordre_disponible: bool).
    """
    params = {
        "stream_rast": stream_raster_layer,
        "direction": stream_direction_layer,
        "elevation": filled_dem_layer,
        "accumulation": accumulation_layer,
        "stream_vector": "TEMPORARY_OUTPUT",
    }
    try:
        result = _run_grass("r.stream.order", params)
        out_key = "stream_vector" if "stream_vector" in result else "stream_vect"
        return _as_vector_layer(result[out_key], "reseau_hydrographique"), True
    except Exception as e:
        if "not found" not in str(e).lower():
            raise  # une vraie erreur d'exécution ne doit pas être masquée silencieusement

    # Repli : r.to.vect (module du cœur de GRASS), réseau sans ordre de Strahler.
    fallback_params = {
        "input": stream_raster_layer,
        "type": 0,  # ligne
        "output": "TEMPORARY_OUTPUT",
    }
    result = _run_grass("r.to.vect", fallback_params)
    layer = _as_vector_layer(result["output"], "reseau_hydrographique")
    return layer, False


def snap_outlets_to_stream(outlets_layer, stream_raster_layer, radius_cells=5):
    """
    Cale (snap) les points exutoires sur la cellule de réseau la plus proche,
    dans un rayon de `radius_cells` cellules. Indispensable pour que
    r.water.outlet délimite le bon bassin (un point exutoire situé hors du
    réseau donne un bassin faux ou vide).
    """
    params = {
        "input": outlets_layer,
        "stream_rast": stream_raster_layer,
        "radius": radius_cells,
        "output": "TEMPORARY_OUTPUT",
    }
    result = _run_grass("r.stream.snap", params)
    return _as_vector_layer(result["output"], "exutoires_calés")


def snap_outlets_to_max_accumulation(outlets_layer, accumulation_layer, search_radius_cells=10):
    """
    Cale chaque point exutoire sur la cellule d'accumulation de flux MAXIMALE
    trouvée dans un voisinage carré de `search_radius_cells` cellules autour
    du point saisi. Contrairement au calage sur le réseau extrait (qui dépend
    du seuil de r.stream.extract), cette méthode s'appuie directement sur la
    carte d'accumulation brute : elle est donc fiable même si le point est
    légèrement à côté du chenal réel, sans dépendre du choix du seuil.

    Renvoie une nouvelle couche mémoire de points, avec les mêmes attributs
    que `outlets_layer`, plus un champ "acc_maxi" contenant la valeur
    d'accumulation trouvée à la position calée (utile pour diagnostic).
    """
    provider = accumulation_layer.dataProvider()
    extent = accumulation_layer.extent()
    width_px = accumulation_layer.width()
    height_px = accumulation_layer.height()
    px_w = extent.width() / width_px
    px_h = extent.height() / height_px

    out_layer = QgsVectorLayer(
        f"Point?crs={outlets_layer.crs().authid()}", "exutoires_calés_accumulation", "memory"
    )
    out_provider = out_layer.dataProvider()
    out_provider.addAttributes(outlets_layer.fields())
    out_provider.addAttributes([QgsField("acc_maxi", QVariant.Double)])
    out_layer.updateFields()

    new_feats = []
    for feat in outlets_layer.getFeatures():
        pt = feat.geometry().asPoint()
        result = find_max_accumulation_point(
            accumulation_layer, pt.x(), pt.y(), search_radius_cells, px_w, px_h, extent
        )
        new_feat = QgsFeature(out_layer.fields())
        attrs = list(feat.attributes()) + [None]
        if result is not None:
            snapped_x, snapped_y, acc_value = result
            new_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(snapped_x, snapped_y)))
            attrs[-1] = float(acc_value)
        else:
            # Aucune cellule valide trouvée dans le voisinage (hors emprise, tout nodata...)
            # -> on conserve le point d'origine pour ne pas perdre l'exutoire.
            new_feat.setGeometry(feat.geometry())
        new_feat.setAttributes(attrs)
        new_feats.append(new_feat)

    out_provider.addFeatures(new_feats)
    out_layer.updateExtents()
    return out_layer


def find_max_accumulation_point(accumulation_layer, x, y, search_radius_cells, px_w, px_h, raster_extent):
    """
    Cherche, dans un carré de (2*search_radius_cells+1) cellules de côté
    centré sur (x, y), la cellule ayant la valeur d'accumulation la plus
    élevée. Renvoie (x_calé, y_calé, valeur) ou None si rien de valide
    n'a été trouvé (fenêtre hors emprise, uniquement du nodata...).
    """
    half_w = search_radius_cells * px_w
    half_h = search_radius_cells * px_h
    window = QgsRectangle(x - half_w, y - half_h, x + half_w, y + half_h)
    window = window.intersect(raster_extent)
    if window.isEmpty():
        return None

    cols = max(1, int(round(window.width() / px_w)))
    rows = max(1, int(round(window.height() / px_h)))

    provider = accumulation_layer.dataProvider()
    block = provider.block(1, window, cols, rows)
    if block is None or not block.isValid():
        return None

    best_val = None
    best_row = best_col = None
    for row in range(rows):
        for col in range(cols):
            if block.isNoData(row, col):
                continue
            val = block.value(row, col)
            if best_val is None or val > best_val:
                best_val = val
                best_row, best_col = row, col

    if best_val is None:
        return None

    cell_w = window.width() / cols
    cell_h = window.height() / rows
    snapped_x = window.xMinimum() + (best_col + 0.5) * cell_w
    snapped_y = window.yMaximum() - (best_row + 0.5) * cell_h
    return snapped_x, snapped_y, best_val


def polygonize_basins(basin_raster_layer):
    """
    Vectorise la sortie 'basin' de r.watershed (un identifiant entier par
    sous-bassin) en polygones -- un polygone par sous-bassin (fusion des
    fragments partageant le même identifiant DN, au cas où GRASS produirait
    des fragments non contigus pour un même identifiant).
    """
    params = {
        "INPUT": basin_raster_layer,
        "BAND": 1,
        "FIELD": "DN",
        "EIGHT_CONNECTEDNESS": True,
        "OUTPUT": "TEMPORARY_OUTPUT",
    }
    result = processing.run("gdal:polygonize", params)
    raw_layer = _as_vector_layer(result["OUTPUT"], "sous_bassins_bruts")

    # gdal:polygonize produit parfois des polygones à géométrie invalide
    # (auto-intersections), surtout avec beaucoup de petits sous-bassins
    # fins (seuil bas). native:dissolve refuse ces géométries par défaut :
    # on les répare systématiquement avant de poursuivre. L'identifiant de
    # cet algorithme a changé selon les versions de QGIS (qgis: -> native:).
    try:
        fixed = processing.run("native:fixgeometries", {"INPUT": raw_layer, "OUTPUT": "TEMPORARY_OUTPUT"})
    except Exception:
        fixed = processing.run("qgis:fixgeometries", {"INPUT": raw_layer, "OUTPUT": "TEMPORARY_OUTPUT"})
    raw_layer = _as_vector_layer(fixed["OUTPUT"], "sous_bassins_bruts_corriges")

    dissolve_params = {
        "INPUT": raw_layer,
        "FIELD": ["DN"],
        "OUTPUT": "TEMPORARY_OUTPUT",
    }
    dissolved = processing.run("native:dissolve", dissolve_params)
    layer = _as_vector_layer(dissolved["OUTPUT"], "sous_bassins")

    # DN = -1 ou nodata correspond aux zones hors bassin (bords du MNT non drainés) : à exclure.
    layer.startEditing()
    to_delete = [f.id() for f in layer.getFeatures() if f["DN"] is None or f["DN"] < 0]
    layer.dataProvider().deleteFeatures(to_delete)
    layer.commitChanges()
    return layer


def find_outlet_in_polygon(accumulation_layer, polygon_geom):
    """
    Cherche, dans l'emprise (bounding box) du polygone donné, la cellule
    d'accumulation de flux MAXIMALE dont le centre tombe réellement à
    l'intérieur du polygone. Il s'agit du point de sortie (exutoire réel)
    du sous-bassin, utilisé ensuite pour calculer la longueur du bassin,
    les temps de concentration, etc.
    Renvoie (x, y, valeur_accumulation) ou None si rien de valide trouvé.

    Attention : le balayage se fait pixel par pixel en Python sur l'emprise
    du polygone ; pour de très grands sous-bassins (MNT haute résolution +
    seuil élevé), ceci peut prendre du temps. Augmenter le seuil réduit le
    nombre et la taille... en fait augmente la taille des sous-bassins mais
    réduit leur nombre ; à ajuster selon les besoins de performance.
    """
    provider = accumulation_layer.dataProvider()
    raster_extent = accumulation_layer.extent()
    px_w = raster_extent.width() / accumulation_layer.width()
    px_h = raster_extent.height() / accumulation_layer.height()

    bbox = polygon_geom.boundingBox()
    bbox = bbox.intersect(raster_extent)
    if bbox.isEmpty():
        return None

    cols = max(1, int(round(bbox.width() / px_w)))
    rows = max(1, int(round(bbox.height() / px_h)))
    # Garde-fou : on plafonne le nombre de pixels balayés pour éviter un blocage
    # de l'interface sur un sous-bassin anormalement grand (ex. seuil trop bas).
    max_cells = 4_000_000
    if cols * rows > max_cells:
        return None

    block = provider.block(1, bbox, cols, rows)
    if block is None or not block.isValid():
        return None

    cell_w = bbox.width() / cols
    cell_h = bbox.height() / rows

    best_val = None
    best_x = best_y = None
    for row in range(rows):
        for col in range(cols):
            if block.isNoData(row, col):
                continue
            val = block.value(row, col)
            if best_val is not None and val <= best_val:
                continue
            x = bbox.xMinimum() + (col + 0.5) * cell_w
            y = bbox.yMaximum() - (row + 0.5) * cell_h
            if polygon_geom.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                best_val = val
                best_x, best_y = x, y

    if best_val is None:
        return None
    return best_x, best_y, best_val


def sample_raster_value(raster_layer, x, y):
    """
    Renvoie la valeur du raster (ex. accumulation de flux) à la position (x, y),
    dans le CRS du raster. Renvoie None si le point est hors emprise ou nodata.
    Utile pour diagnostiquer si un point exutoire tombe bien sur un chenal
    à forte accumulation (donc plausible) ou sur une cellule marginale
    (souvent la cause d'un bassin anormalement petit).
    """
    provider = raster_layer.dataProvider()
    value, ok = provider.sample(QgsPointXY(x, y), 1)
    if not ok:
        return None
    return value


def delineate_basin_raster(drainage_layer, outlet_x, outlet_y, output=None):
    """
    Délimite le bassin versant en amont d'un point exutoire (coordonnées dans
    le CRS du projet) à partir de la carte de direction de drainage.
    """
    output = output or "TEMPORARY_OUTPUT"
    params = {
        "input": drainage_layer,
        "coordinates": f"{outlet_x},{outlet_y}",
        "output": output,
    }
    result = _run_grass("r.water.outlet", params)
    return _as_raster_layer(result["output"], "bassin_raster")


def raster_basin_to_polygon(basin_raster_layer):
    """Vectorise le raster binaire du bassin en polygone(s), ne garde que DN=1."""
    params = {
        "INPUT": basin_raster_layer,
        "BAND": 1,
        "FIELD": "DN",
        "EIGHT_CONNECTEDNESS": True,
        "OUTPUT": "TEMPORARY_OUTPUT",
    }
    result = processing.run("gdal:polygonize", params)
    layer = _as_vector_layer(result["OUTPUT"], "bassin")

    # Répare les géométries invalides (auto-intersections) que gdal:polygonize
    # peut produire, avant qu'elles ne fassent échouer une étape ultérieure
    # (ex. native:clip pour découper le réseau sur ce bassin).
    try:
        fixed = processing.run("native:fixgeometries", {"INPUT": layer, "OUTPUT": "TEMPORARY_OUTPUT"})
    except Exception:
        fixed = processing.run("qgis:fixgeometries", {"INPUT": layer, "OUTPUT": "TEMPORARY_OUTPUT"})
    layer = _as_vector_layer(fixed["OUTPUT"], "bassin")

    layer.startEditing()
    to_delete = [f.id() for f in layer.getFeatures() if f["DN"] != 1]
    layer.dataProvider().deleteFeatures(to_delete)
    layer.commitChanges()
    return layer


def clip_streams_to_basin(streams_layer, basin_polygon_layer):
    """Découpe le réseau hydrographique (lignes) sur l'emprise du bassin."""
    params = {
        "INPUT": streams_layer,
        "OVERLAY": basin_polygon_layer,
        "OUTPUT": "TEMPORARY_OUTPUT",
    }
    result = processing.run("native:clip", params)
    return _as_vector_layer(result["OUTPUT"], "reseau_clip")
