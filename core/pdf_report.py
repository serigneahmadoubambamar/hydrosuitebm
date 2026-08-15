# -*- coding: utf-8 -*-
"""
Génération d'un rapport PDF : méthodologie, formules utilisées, et analyse
des résultats (en particulier les écarts entre les différentes formules de
temps de concentration, et l'influence de la résolution du MNT).

On utilise PyQt (QTextDocument + QPrinter) plutôt qu'une bibliothèque tierce
(reportlab...) : PyQt fait partie du cœur de QGIS et est donc TOUJOURS
disponible, sans dépendance supplémentaire à installer sur le poste de
l'utilisateur.
"""
from qgis.PyQt.QtGui import QTextDocument
from qgis.PyQt.QtPrintSupport import QPrinter

CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #222; }
h1 { font-size: 18pt; color: #1a4d6d; border-bottom: 2px solid #1a4d6d; padding-bottom: 4px; }
h2 { font-size: 14pt; color: #1a4d6d; margin-top: 18px; }
h3 { font-size: 11.5pt; color: #2a6d8d; margin-top: 12px; }
h4 { font-size: 10.5pt; color: #2a6d8d; margin-top: 10px; margin-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 14px 0; }
th, td { border: 1px solid #999; padding: 4px 6px; font-size: 9pt; text-align: left; }
th { background-color: #dbe7ef; }
.formule { background-color: #f2f6f8; padding: 6px 10px; border-left: 3px solid #1a4d6d; margin: 6px 0; font-family: monospace; }
.note { background-color: #fff6e0; border-left: 3px solid #d9a300; padding: 6px 10px; margin: 8px 0; }
.small { font-size: 8pt; color: #666; }
"""


# ---------------------------------------------------------------------------
# Interprétation automatique des indices morphométriques
# ---------------------------------------------------------------------------

def _interpret_gravelius(kc):
    if kc is None:
        return None
    if kc < 1.25:
        return (
            f"L'indice de compacité de Gravelius (Kc = {kc:.2f}) indique un bassin de forme "
            f"quasi-circulaire. Cette forme favorise une convergence rapide et quasi simultanée "
            f"des écoulements issus des différentes parties du bassin vers l'exutoire : la réponse "
            f"aux précipitations tend à être brutale, avec un temps de montée court et des débits de "
            f"pointe de crue relativement élevés."
        )
    elif kc < 1.5:
        return (
            f"L'indice de compacité de Gravelius (Kc = {kc:.2f}) indique un bassin de forme ovale à "
            f"ronde, intermédiaire entre une forme compacte et une forme allongée. La réponse "
            f"hydrologique attendue est modérée, sans étalement ni concentration marqués des apports."
        )
    elif kc < 1.75:
        return (
            f"L'indice de compacité de Gravelius (Kc = {kc:.2f}) indique un bassin de forme ovale "
            f"allongée. Les apports issus des différentes parties du bassin atteignent l'exutoire de "
            f"façon plus étalée dans le temps qu'un bassin circulaire équivalent, ce qui tend à "
            f"modérer les débits de pointe de crue."
        )
    else:
        return (
            f"L'indice de compacité de Gravelius (Kc = {kc:.2f}) indique un bassin de forme "
            f"relativement allongée. Cette forme tend à répartir les apports dans le temps et à "
            f"limiter les pics de crue par rapport à un bassin circulaire de même surface : les eaux "
            f"des parties amont et aval du bassin n'arrivent pas simultanément à l'exutoire, ce qui "
            f"étale l'hydrogramme de crue et en réduit le débit de pointe."
        )


def _interpret_miller(rc):
    if rc is None:
        return None
    if rc > 0.7:
        return (
            f"L'indice de circularité de Miller (Rc = {rc:.2f}, proche de 1) confirme une forme "
            f"proche du cercle, cohérente avec une concentration rapide des écoulements et un risque "
            f"de crue éclair plus marqué que pour un bassin allongé de même surface."
        )
    elif rc > 0.4:
        return (
            f"L'indice de circularité de Miller (Rc = {rc:.2f}) traduit une forme intermédiaire, "
            f"ni franchement circulaire ni franchement allongée."
        )
    else:
        return (
            f"L'indice de circularité de Miller (Rc = {rc:.2f}, éloigné de 1) confirme une forme "
            f"allongée, cohérente avec un étalement temporel des apports et une atténuation des "
            f"débits de pointe."
        )


def _interpret_schumm(re):
    if re is None:
        return None
    if re > 0.9:
        return (
            f"L'indice d'allongement de Schumm (Re = {re:.2f}, proche de 1) confirme une forme "
            f"proche du cercle."
        )
    elif re > 0.7:
        return (
            f"L'indice d'allongement de Schumm (Re = {re:.2f}) confirme une forme modérément "
            f"allongée."
        )
    else:
        return (
            f"L'indice d'allongement de Schumm (Re = {re:.2f}, nettement inférieur à 1) confirme une "
            f"forme franchement allongée du bassin."
        )


def _interpret_hypsometric_integral(hi):
    if hi is None:
        return None
    if hi > 0.6:
        return (
            f"L'intégrale hypsométrique (Hi = {hi:.2f}) est élevée, caractéristique d'un bassin au "
            f"stade de jeunesse géomorphologique : le relief reste marqué, l'érosion active domine sur "
            f"la sédimentation, et la réponse hydrologique aux précipitations tend à être rapide avec "
            f"des débits de pointe élevés."
        )
    elif hi > 0.35:
        return (
            f"L'intégrale hypsométrique (Hi = {hi:.2f}) correspond à un bassin au stade de maturité "
            f"géomorphologique : un équilibre relatif s'est établi entre érosion et sédimentation, "
            f"pour une réponse hydrologique ni particulièrement rapide ni particulièrement amortie."
        )
    else:
        return (
            f"L'intégrale hypsométrique (Hi = {hi:.2f}) est faible, caractéristique d'un bassin au "
            f"stade de vieillesse géomorphologique (relief atténué, proche de la peneplaine) : les "
            f"pentes douces et le relief peu marqué favorisent l'infiltration et un écoulement plus "
            f"lent et diffus, avec des débits de pointe généralement plus modérés."
        )


def _interpret_relief_ig(ig):
    """Classification du relief selon l'indice de pente globale Ig (m/km) -- classification ORSTOM/IRD."""
    if ig is None:
        return None
    classes = [
        (2, "R1 - relief très faible"),
        (5, "R2 - relief faible"),
        (10, "R3 - relief assez faible"),
        (20, "R4 - relief modéré"),
        (50, "R5 - relief assez fort"),
        (100, "R6 - relief fort"),
    ]
    classe = "R7 - relief très fort"
    for seuil, label in classes:
        if ig < seuil:
            classe = label
            break
    return (
        f"L'indice de pente globale (Ig = {ig:.1f} m/km) place ce bassin dans la classe de relief "
        f"« {classe} » (classification ORSTOM/IRD). "
        + (
            "Un relief marqué comme celui-ci favorise un ruissellement rapide sur les versants, une "
            "érosion active et des temps de concentration courts."
            if ig >= 20
            else "Un relief modéré à faible comme celui-ci favorise l'infiltration et un ruissellement "
            "plus lent sur les versants, avec des temps de concentration relativement plus longs."
        )
    )


def _interpret_drainage_density(dd):
    if dd is None:
        return None
    if dd > 2.0:
        return (
            f"La densité de drainage (Dd = {dd:.2f} km/km²) est élevée, ce qui suggère un substrat peu "
            f"perméable (roches imperméables, sols peu poreux ou dégradés) et/ou un relief marqué : le "
            f"réseau hydrographique est bien développé, l'écoulement de surface domine sur "
            f"l'infiltration, et la réponse aux précipitations est généralement rapide."
        )
    elif dd > 1.0:
        return (
            f"La densité de drainage (Dd = {dd:.2f} km/km²) est modérée, cohérente avec un équilibre "
            f"entre infiltration et ruissellement de surface."
        )
    else:
        return (
            f"La densité de drainage (Dd = {dd:.2f} km/km²) est faible, ce qui suggère un substrat "
            f"perméable (sols sableux, formations poreuses ou karstiques) et/ou un relief peu marqué : "
            f"l'infiltration tend à dominer sur le ruissellement de surface, avec une réponse aux "
            f"précipitations plus amortie."
        )


def _morphometry_interpretation_html(results):
    interpretations = [
        _interpret_gravelius(results.get("indice_compacite_gravelius_Kc")),
        _interpret_miller(results.get("indice_circularite_miller_Rc")),
        _interpret_schumm(results.get("indice_allongement_schumm_Re")),
        _interpret_hypsometric_integral(results.get("integrale_hypsometrique_Hi")),
        _interpret_relief_ig(results.get("indice_pente_globale_Ig_m_par_km")),
        _interpret_drainage_density(results.get("densite_drainage_km_par_km2")),
    ]
    interpretations = [t for t in interpretations if t]
    if not interpretations:
        return ""
    html = "<h4>Interprétation morphométrique</h4>"
    for text in interpretations:
        html += f"<p>{text}</p>"
    return html


def _html_to_pdf(html, output_path):
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(output_path)
    printer.setPageMargins(15, 15, 15, 15, QPrinter.Millimeter)
    doc = QTextDocument()
    doc.setDefaultStyleSheet(CSS)
    doc.setHtml(f"<html><body>{html}</body></html>")
    doc.print_(printer)


def _methodology_section():
    return """
<h1>Rapport méthodologique — HydroSuiteBM Pro</h1>
<p class="small">Généré automatiquement par HydroSuiteBM Pro (Hydrological Analysis Platform for QGIS) — délimitation de bassins versants et calcul de leurs paramètres sous QGIS/GRASS.</p>

<h2>1. Chaîne de traitement</h2>
<ol>
<li><b>Comblement des dépressions</b> du MNT (r.fill.dir) : élimine les cuvettes artificielles qui interrompraient le calcul du drainage.</li>
<li><b>Direction et accumulation de flux</b> (r.watershed, algorithme MFD par défaut) : pour chaque cellule, détermine vers quelle(s) cellule(s) voisine(s) l'eau s'écoule, et combien de cellules amont contribuent à chaque cellule.</li>
<li><b>Extraction du réseau hydrographique</b> (r.stream.extract) : les cellules dont l'accumulation dépasse un seuil (exprimé en nombre de cellules, converti automatiquement depuis une surface en ha/km² choisie par l'utilisateur) sont considérées comme faisant partie du réseau.</li>
<li><b>Délimitation des bassins</b>, selon le mode choisi :
  <ul>
  <li><i>Mode manuel</i> : un bassin par point exutoire fourni, calé sur le réseau (par recherche de l'accumulation de flux maximale dans un voisinage, ou sur le réseau extrait) puis délimité par r.water.outlet.</li>
  <li><i>Mode automatique</i> : découpage direct de tout le MNT en sous-bassins via la sortie <i>basin</i> de r.watershed (même seuil que pour le réseau) — équivalent au comportement natif de r.watershed lancé sans points exutoires.</li>
  </ul>
</li>
<li><b>Calcul des paramètres géométriques</b> (surface, périmètre, indices de forme) directement sur la géométrie du polygone du bassin.</li>
<li><b>Calcul des paramètres altimétriques</b> (altitudes min/max/moyenne/médiane, courbe et intégrale hypsométrique) et de la <b>pente moyenne</b>, par échantillonnage du MNT sur l'emprise du bassin.</li>
<li><b>Calcul des paramètres du réseau hydrographique</b> (longueur totale, densité de drainage, fréquence, ordre de Strahler et rapports de Horton si l'extension GRASS r.stream.order est installée) sur le réseau découpé pour chaque bassin.</li>
<li><b>Calcul du talweg principal</b> : le réseau hydrographique découpé est traité comme un graphe arborescent enraciné à l'exutoire ; le chemin le plus long depuis l'exutoire (parcours en largeur) donne la longueur du plus long chemin hydraulique réel — c'est ce L, et non une distance géométrique à vol d'oiseau, qui est utilisé dans les formules de temps de concentration.</li>
<li><b>Calcul du Curve Number (CN) moyen</b> du bassin (moyenne surfacique), si un raster CN est fourni par l'utilisateur (préparé au préalable en croisant occupation du sol et groupe hydrologique de sol avec les tables du NRCS).</li>
<li><b>Calcul des temps de concentration</b> selon plusieurs formules empiriques usuelles, dont la méthode SCS si un CN est disponible (voir section 3).</li>
</ol>

<h2>2. Formules utilisées</h2>

<h3>2.1 Paramètres géométriques</h3>
<div class="formule">Indice de compacité de Gravelius : Kc = 0.28 &times; P / &radic;A &nbsp;(P en km, A en km&sup2;)</div>
<div class="formule">Rectangle équivalent (L, l) : L &times; l = A et 2(L + l) = P</div>
<div class="formule">Indice de circularité de Miller : Rc = 4&pi; &times; A / P&sup2;</div>
<div class="formule">Indice d'allongement de Schumm : Re = 1.128 &times; &radic;A / Lb &nbsp;(Lb = longueur géométrique du bassin)</div>

<h3>2.2 Paramètres altimétriques</h3>
<div class="formule">Intégrale hypsométrique : Hi = (Hmoy &minus; Hmin) / (Hmax &minus; Hmin)</div>
<div class="formule">Indice de pente globale : Ig = (H5% &minus; H95%) / L &nbsp;(L = longueur du rectangle équivalent, en km)</div>
<div class="formule">Dénivelée spécifique : Ds = Ig &times; &radic;A</div>

<h3>2.3 Paramètres du réseau hydrographique</h3>
<div class="formule">Densité de drainage : Dd = &Sigma;Li / A &nbsp;(km de réseau par km&sup2;)</div>
<div class="formule">Fréquence des cours d'eau : F = N / A &nbsp;(nombre de tronçons par km&sup2;)</div>
<div class="formule">Rapport de confluence de Horton : Rb = Nu / Nu+1 &nbsp;(moyenné sur les ordres de Strahler successifs)</div>
<div class="formule">Rapport de longueur de Horton : Rl = Lu+1 / Lu</div>

<h3>2.4 Temps de concentration (Tc)</h3>
<p>L = longueur du talweg principal (km, le plus long chemin hydraulique réel, voir étape 8) ; A = surface (km&sup2;) ; S = pente moyenne (m/m) ; Hmoy, Hmin = altitudes moyenne et minimale (m) ; CN = Curve Number moyen pondéré (méthode SCS-CN).</p>
<div class="formule"><b>Kirpich</b> (résultat en minutes) : Tc = 0.01947 &times; L<sup>0.77</sup> &times; S<sup>&minus;0.385</sup> &nbsp;(L converti en mètres dans le calcul)</div>
<div class="formule"><b>Giandotti</b> (résultat en heures) : Tc = (4&radic;A + 1.5&times;L) / (0.8&times;&radic;(Hmoy &minus; Hmin))</div>
<div class="formule"><b>Passini</b> (résultat en heures) : Tc = 0.108 &times; (A&times;L)<sup>1/3</sup> / &radic;S</div>
<div class="formule"><b>Ventura</b> (résultat en heures) : Tc = 0.1272 &times; &radic;(A / S)</div>
<div class="formule"><b>SCS / NRCS</b> (méthode du lag, TR-55 ; résultat en heures) :<br>
S (pouces) = 1000/CN &minus; 10 &nbsp;&nbsp; | &nbsp;&nbsp; Tl (h) = L<sup>0.8</sup> &times; (S+1)<sup>0.7</sup> / (1900 &times; Y<sup>0.5</sup>) &nbsp;&nbsp; | &nbsp;&nbsp; Tc = Tl / 0.6<br>
<span class="small">(L en pieds, Y = pente moyenne en %, formule volontairement gardée en unités impériales d'origine du NRCS)</span></div>
<div class="formule">Rétention potentielle S (mm, forme métrique) : S = 25400/CN &minus; 254</div>

<h3>2.5 Seuils de classification utilisés pour l'interprétation automatique</h3>
<p class="small">Les commentaires interprétatifs générés pour chaque bassin (section 6) s'appuient sur des
seuils usuels de la littérature hydrologique/géomorphologique : classes de Gravelius (Kc &lt; 1.25 quasi-circulaire,
1.25&ndash;1.5 ovale à ronde, 1.5&ndash;1.75 ovale allongée, &gt;1.75 allongée), classes de relief ORSTOM/IRD selon
l'indice de pente globale Ig (R1 à R7), et seuils usuels pour l'intégrale hypsométrique (stades de jeunesse
&gt;0.6, maturité 0.35&ndash;0.6, vieillesse &lt;0.35, d'après Strahler) et la densité de drainage. Ces seuils sont des
repères généraux ; ils gagnent à être recoupés avec la connaissance de terrain et le contexte régional de
l'étude, et ne remplacent pas un avis d'expert.</p>
"""


def _tc_discussion_section(dem_resolution_m2=None, dem_resolution_xy=None):
    resolution_txt = ""
    if dem_resolution_xy:
        px_w, px_h = dem_resolution_xy
        resolution_txt = f"""
<p>Pour ce traitement, le MNT utilisé a une résolution d'environ <b>{px_w:.1f} m &times; {px_h:.1f} m</b> par cellule
(soit {dem_resolution_m2:.0f} m&sup2;/cellule). Gardez cette valeur en tête en lisant l'analyse ci-dessous : elle
détermine directement la précision de la pente et de la longueur de talweg utilisées dans les formules de Tc.</p>
"""
    return f"""
<h2>3. Pourquoi les temps de concentration diffèrent-ils entre les formules ?</h2>

<p>Il est normal — et attendu — d'obtenir des valeurs de Tc sensiblement différentes selon la formule employée
pour un même bassin. Chaque formule est une relation <b>empirique</b>, calée statistiquement sur un échantillon
de bassins réels d'une région et d'une échelle données (Kirpich : petits bassins agricoles pentus des
États-Unis ; Giandotti : bassins italiens ; Passini et Ventura : bassins européens de tailles variées).
Aucune de ces formules n'est universellement "la bonne" : chacune reflète les caractéristiques
physiographiques et climatiques de son échantillon de calage, qui peuvent différer de celles de votre bassin
d'étude. Un écart de 30 à 100% entre les estimations n'est pas rare et ne signale pas une erreur de calcul.
</p>

<table>
<tr><th>Formule</th><th>Domaine de validité usuel (surface)</th><th>Contexte de calage d'origine</th></tr>
<tr><td>Kirpich</td><td>≈ 0.004 &ndash; 1 km²</td><td>Petits bassins agricoles pentus (Tennessee, USA)</td></tr>
<tr><td>SCS (lag, TR-55)</td><td>≈ 0.01 &ndash; 8 km²</td><td>Petits bassins ruraux/urbains (NRCS, USA)</td></tr>
<tr><td>Ventura</td><td>≈ 0.5 &ndash; 700 km²</td><td>Bassins européens de tailles variées</td></tr>
<tr><td>Passini</td><td>≈ 0.5 &ndash; 700 km²</td><td>Bassins européens de tailles variées</td></tr>
<tr><td>Giandotti</td><td>≈ 1.7 &ndash; 700 km²</td><td>Bassins italiens moyens à grands</td></tr>
</table>
<p class="small">Ces ordres de grandeur varient sensiblement selon les sources bibliographiques consultées ;
ils sont donnés ici à titre de repère de cohérence, pas comme une règle stricte et universellement admise.
Le plugin s'en sert pour indiquer, pour chaque bassin, quelle formule est calée sur la gamme de surface la
plus proche de la sienne (section 6) -- ce qui n'exclut pas d'examiner aussi les autres valeurs obtenues.</p>

<div class="note">
<b>Bonne pratique :</b> traitez l'ensemble des valeurs obtenues comme une <b>fourchette d'incertitude</b>
plutôt que de choisir une seule formule "de référence". Si le contexte réglementaire ou le cahier des charges
du projet impose une formule particulière (c'est souvent le cas de Kirpich pour les petits bassins ruraux, ou
de Giandotti dans certains contextes méditerranéens), privilégiez-la, mais vérifiez que les valeurs des autres
formules restent dans un ordre de grandeur cohérent.
</div>

<h2>4. Influence de la résolution du MNT sur le Tc</h2>
{resolution_txt}
<p>Au-delà du choix de la formule, la <b>résolution du MNT</b> (taille de la cellule) influence directement
les deux grandeurs d'entrée communes à toutes les formules de Tc : la longueur du talweg (L) et la pente
moyenne (S). Deux effets se combinent, dans des directions parfois opposées :</p>

<ul>
<li><b>Lissage de la pente :</b> un MNT à résolution grossière moyenne l'altitude sur de grandes cellules,
ce qui atténue les ruptures de pente locales (chutes, ressauts, ravins étroits). La pente moyenne calculée
est alors généralement <b>sous-estimée</b> par rapport à la réalité du terrain. Or, dans les formules de
Kirpich, Passini et Ventura, la pente intervient avec un exposant négatif : une pente sous-estimée
<b>augmente artificiellement le Tc calculé</b> (le bassin paraît répondre plus lentement qu'il ne le fait
réellement).</li>

<li><b>Généralisation du talweg :</b> à résolution grossière, le tracé du plus long chemin hydraulique perd
en sinuosité (les méandres fins ne sont plus représentés), ce qui tend à <b>raccourcir</b> L. Mais l'algorithme
D8/MFD utilisé pour tracer le chemin peut aussi produire un effet d'escalier sur les segments obliques, qui
tend au contraire à <b>rallonger</b> artificiellement le tracé. L'effet net sur L dépend donc de la topographie
locale et n'est pas prévisible a priori sans comparer plusieurs résolutions.</li>

<li><b>Décalage du seuil de réseau :</b> le seuil d'extraction du réseau est fixé en nombre de cellules ; à
résolution grossière, chaque cellule représente une surface au sol plus grande, donc la tête du réseau
(le point de départ du talweg, en amont) se déplace vers l'aval par rapport à ce qu'elle serait avec un MNT
plus fin. Cela raccourcit également L, et donc réduit le Tc calculé pour un même seuil en "nombre de cellules"
(c'est pourquoi le plugin convertit désormais ce seuil en surface réelle -- ha/km² -- afin de limiter cet
artefact lors de changements de résolution).</li>
</ul>

<div class="note">
<b>Recommandation pratique :</b> si vous disposez de MNT à plusieurs résolutions pour la même zone,
comparez la longueur du talweg et la pente moyenne obtenues avec chacun avant de figer un Tc définitif. À
défaut, utilisez la résolution la plus fine disponible et compatible avec la taille de votre bassin (un MNT
de 90 m sur un bassin de quelques km² donne une pente et un talweg peu fiables, quelle que soit la formule de
Tc appliquée ensuite).</div>
"""


def generate_methodology_pdf(output_path):
    """Génère un PDF autonome (méthodologie + formules + discussion Tc/résolution), sans résultats chiffrés."""
    html = _methodology_section() + _tc_discussion_section()
    _html_to_pdf(html, output_path)


def generate_full_report_pdf(output_path, basin_records, run_info=None):
    """
    Génère le rapport PDF complet : méthodologie, formules, discussion sur les
    écarts entre formules de Tc et l'influence de la résolution du MNT, PUIS
    pour chaque bassin un tableau récapitulatif et une analyse automatique de
    la fourchette de Tc obtenue.

    :param basin_records: liste de tuples (basin_id, geometry, results_dict)
        -- la même liste que celle utilisée pour la couche combinée des bassins.
    :param run_info: dict optionnel avec des infos sur le traitement effectué
        (résolution du MNT, seuil utilisé, mode, etc.) pour contextualiser le rapport.
    """
    run_info = run_info or {}
    px_w = run_info.get("px_w")
    px_h = run_info.get("px_h")
    dem_resolution_m2 = (px_w * px_h) if (px_w and px_h) else None
    dem_resolution_xy = (px_w, px_h) if (px_w and px_h) else None

    html = _methodology_section() + _tc_discussion_section(dem_resolution_m2, dem_resolution_xy)

    html += "<h2>5. Paramètres du traitement effectué</h2><table>"
    html += "<tr><th>Paramètre</th><th>Valeur</th></tr>"
    for label, key in [
        ("MNT", "dem_name"),
        ("Résolution du MNT", "resolution_label"),
        ("Mode", "mode_label"),
        ("Surface minimale des sous-bassins", "min_area_label"),
        ("Algorithme de flux", "flow_algo_label"),
        ("Méthode de calage des exutoires", "snap_method_label"),
        ("Nombre de bassins obtenus", "n_basins"),
    ]:
        val = run_info.get(key)
        if val is not None:
            html += f"<tr><td>{label}</td><td>{val}</td></tr>"
    html += "</table>"

    html += "<h2>6. Analyse par bassin</h2>"

    if not basin_records:
        html += "<p><i>Aucun bassin n'a été calculé lors de ce traitement.</i></p>"

    for basin_id, _geom, results in basin_records:
        html += f"<h3>Bassin : {basin_id}</h3>"

        html += "<table><tr><th>Paramètre</th><th>Valeur</th></tr>"
        summary_rows = [
            ("Surface", results.get("surface_km2"), "km²"),
            ("Périmètre", results.get("perimetre_km"), "km"),
            ("Longueur du talweg (L, utilisée pour Tc)", results.get("longueur_talweg_km"), "km"),
            ("Pente moyenne", results.get("pente_moyenne_pct"), "%"),
            ("Altitude min / max", None, None),
            ("Densité de drainage", results.get("densite_drainage_km_par_km2"), "km/km²"),
        ]
        for label, val, unit in summary_rows:
            if label == "Altitude min / max":
                hmin, hmax = results.get("altitude_min_m"), results.get("altitude_max_m")
                if hmin is not None and hmax is not None:
                    html += f"<tr><td>{label}</td><td>{hmin:.0f} m &ndash; {hmax:.0f} m</td></tr>"
                continue
            if val is not None:
                html += f"<tr><td>{label}</td><td>{val:.3f} {unit}</td></tr>"
        html += "</table>"

        html += _morphometry_interpretation_html(results)

        if results.get("curve_number_cn") is not None:
            html += (
                f"<p>Curve Number (CN) moyen pondéré du bassin : <b>{results['curve_number_cn']:.1f}</b> "
                f"(rétention potentielle S = {results.get('retention_potentielle_S_mm', 0):.1f} mm).</p>"
            )

        tc_entries = [
            ("Kirpich", results.get("tc_kirpich_min"), "min", 1.0),
            ("Giandotti", results.get("tc_giandotti_h"), "h", 60.0),
            ("Passini", results.get("tc_passini_h"), "h", 60.0),
            ("Ventura", results.get("tc_ventura_h"), "h", 60.0),
            ("SCS (lag, TR-55)", results.get("tc_scs_h"), "h", 60.0),
        ]
        tc_minutes = [(name, val * factor) for name, val, unit, factor in tc_entries if val is not None]

        if tc_minutes:
            html += "<table><tr><th>Formule</th><th>Tc</th><th>Tc (min, converti)</th></tr>"
            for name, val, unit, factor in tc_entries:
                if val is not None:
                    html += f"<tr><td>{name}</td><td>{val:.2f} {unit}</td><td>{val*factor:.1f} min</td></tr>"
            html += "</table>"

            values = [v for _, v in tc_minutes]
            vmin, vmax, vmean = min(values), max(values), sum(values) / len(values)
            ecart_pct = ((vmax - vmin) / vmean * 100) if vmean else 0
            name_min = next(n for n, v in tc_minutes if v == vmin)
            name_max = next(n for n, v in tc_minutes if v == vmax)

            html += f"""
<div class="note">
<b>Analyse automatique :</b> pour ce bassin (surface = {results.get('surface_km2', 0):.3f} km²), le Tc calculé
varie de <b>{vmin:.1f} min</b> ({name_min}) à <b>{vmax:.1f} min</b> ({name_max}), soit une moyenne de
{vmean:.1f} min et un écart de {ecart_pct:.0f}% entre la formule la plus rapide et la plus lente. """
            if ecart_pct > 60:
                html += (
                    "Cet écart est important : il est cohérent avec un bassin dont les caractéristiques "
                    "(forme, pente, taille) s'éloignent sensiblement de l'échantillon de calage d'au moins "
                    "une des formules ci-dessus -- voir section 3. Il est recommandé de retenir une "
                    "fourchette plutôt qu'une valeur unique, ou de privilégier la formule la plus adaptée "
                    "au contexte régional/réglementaire de l'étude."
                )
            else:
                html += (
                    "Cet écart est modéré et cohérent avec la variabilité normale entre formules empiriques "
                    "(voir section 3)."
                )
            html += "</div>"

            recommended = results.get("tc_formule_recommandee")
            out_of_domain = results.get("tc_formules_hors_domaine")
            if recommended:
                html += f"""
<div class="note">
<b>Formule recommandée pour ce bassin :</b> compte tenu de sa surface ({results.get('surface_km2', 0):.3f} km²)
et des domaines de validité usuels rappelés en section 2.5/3, la formule <b>{recommended}</b> est celle dont
la plage de calage correspond le plus étroitement à l'échelle de ce bassin.
{"Les formules suivantes sont hors de leur domaine de validité usuel pour cette surface : " + out_of_domain + "." if out_of_domain else ""}
Ceci reste une indication d'ordre de grandeur (voir la réserve de la section 2.5), pas une règle absolue.
</div>"""
        else:
            html += "<p><i>Temps de concentration non calculés pour ce bassin (pente ou talweg indisponible).</i></p>"

    _html_to_pdf(html, output_path)
