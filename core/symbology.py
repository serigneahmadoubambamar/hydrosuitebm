# -*- coding: utf-8 -*-
"""
Symbologie automatique de la couche de bassins versants : classée par
surface (SURF_M2), pour une lecture immédiate des tailles relatives des
(sous-)bassins sans configuration manuelle dans QGIS.
"""
from qgis.core import QgsRuleBasedRenderer, QgsSymbol, QgsGradientColorRamp
from qgis.PyQt.QtGui import QColor


def _color_ramp_bleu_vert():
    """Dégradé jaune pâle (petits bassins) -> vert foncé (grands bassins)."""
    return QgsGradientColorRamp(QColor(255, 255, 204), QColor(0, 90, 50))


def compute_class_edges(values, n_classes=5):
    """
    Calcule les bornes de classes par quantiles (classes à effectif égal
    de bassins), en dédupliquant les bornes identiques -- fonction pure,
    testable indépendamment de QGIS.

    :param values: liste de valeurs numériques (déjà filtrées, sans None).
    :return: liste de bornes [e0, e1, ..., ek] définissant k classes
        [e0,e1], ]e1,e2], ..., ]e(k-1),ek] -- ou liste vide si `values` est vide.
    """
    if not values:
        return []
    values = sorted(values)
    n = len(values)
    n_classes = max(1, min(n_classes, len(set(values))))

    edges = [values[0]]
    for i in range(1, n_classes):
        idx = min(int(i * n / n_classes), n - 1)
        edges.append(values[idx])
    edges.append(values[-1])

    # Dédoublonnage (valeurs très regroupées pouvant donner des bornes identiques).
    edges = sorted(set(edges))
    return edges


def style_basins_by_surface(layer, field_name="SURF_M2", n_classes=5):
    """
    Applique une symbologie graduée à la couche de bassins, classée par
    surface croissante, en calculant les classes directement depuis les
    valeurs réelles de la couche (quantiles -- classes équilibrées en
    nombre de bassins plutôt qu'en étendue de valeurs, plus lisible
    quand quelques bassins sont beaucoup plus grands que les autres).
    """
    values = [f[field_name] for f in layer.getFeatures() if f[field_name] is not None]
    edges = compute_class_edges(values, n_classes)
    if len(edges) < 2:
        return

    n_classes_reel = len(edges) - 1
    ramp = _color_ramp_bleu_vert()
    root_rule = QgsRuleBasedRenderer.Rule(None)

    for i in range(n_classes_reel):
        lo, hi = edges[i], edges[i + 1]
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        frac = i / max(1, n_classes_reel - 1)
        symbol.setColor(ramp.color(frac))
        symbol.setOpacity(0.75)

        if i == 0:
            expr = f'"{field_name}" <= {hi}'
        elif i == n_classes_reel - 1:
            expr = f'"{field_name}" > {lo}'
        else:
            expr = f'"{field_name}" > {lo} AND "{field_name}" <= {hi}'

        rule = QgsRuleBasedRenderer.Rule(symbol)
        rule.setFilterExpression(expr)
        if field_name == "SURF_M2":
            rule.setLabel(f"{lo/1e6:.3f} - {hi/1e6:.3f} km²")
        else:
            rule.setLabel(f"{lo:.2f} - {hi:.2f}")
        root_rule.appendChild(rule)

    layer.setRenderer(QgsRuleBasedRenderer(root_rule))
    layer.triggerRepaint()
