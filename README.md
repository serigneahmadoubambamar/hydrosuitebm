# HydroSuiteBM Pro

**Hydrological Analysis Platform for QGIS — édition complète**

Plugin QGIS de délimitation automatique de bassins versants et de calcul de
leurs paramètres géométriques, altimétriques, hydrographiques et
hydrologiques, à partir d'un Modèle Numérique de Terrain (MNT) et de
GRASS GIS.

Cette édition **Pro** ajoute à l'édition Lite : le rapport PDF
méthodologique et interprétatif, l'export CSV, le temps de concentration
par la méthode SCS-CN, et le calcul du Curve Number moyen par bassin.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Guide d'utilisation](#guide-dutilisation)
- [Paramètres calculés](#paramètres-calculés)
- [Formules utilisées](#formules-utilisées)
- [Sorties produites](#sorties-produites)
- [Limitations connues](#limitations-connues)
- [Dépannage](#dépannage)
- [Licence](#licence)

---

## Fonctionnalités

- **Deux modes de délimitation** :
  - *Manuel* : un bassin par point exutoire fourni (calage automatique sur
    l'accumulation de flux maximale, ou sur le réseau extrait).
  - *Automatique* : découpage de tout le MNT en sous-bassins versants
    (équivalent à la sortie `basin` native de `r.watershed`), sans avoir à
    saisir de points.
- **Seuil du réseau et taille minimale des sous-bassins exprimés en ha/km²**
  (conversion automatique en nombre de cellules selon la résolution du MNT
  sélectionné).
- **Choix de l'algorithme de flux** : MFD (directions multiples, par défaut,
  comportement natif de `r.watershed`) ou SFD (direction unique, plus
  rapide).
- **Paramètres géométriques** : surface, périmètre, indice de compacité de
  Gravelius, rectangle équivalent, indice de circularité de Miller, indice
  d'allongement de Schumm.
- **Paramètres altimétriques** : altitudes min/max/moyenne/médiane, courbe
  et intégrale hypsométrique, pente moyenne, indice de pente globale (avec
  classification ORSTOM/IRD du relief), dénivelée spécifique.
- **Paramètres du réseau hydrographique** : longueur totale, nombre de
  tronçons, densité de drainage, fréquence des cours d'eau, ordre de
  Strahler maximal et rapports de confluence/longueur de Horton (si
  l'extension GRASS `r.stream.order` est installée — sinon repli automatique
  sur `r.to.vect`, module du cœur de GRASS).
- **Longueur du talweg principal** : calculée comme le plus long chemin
  hydraulique réel le long du réseau (et non une distance géométrique à vol
  d'oiseau), utilisée dans toutes les formules de temps de concentration.
- **Temps de concentration selon 5 méthodes** : Kirpich, Giandotti, Passini,
  Ventura, et **SCS/NRCS (lag method, TR-55)** si un raster Curve Number
  (CN) est fourni.
- **Curve Number moyen pondéré** par bassin, à partir d'un raster CN — que
  vous pouvez fournir vous-même, ou **construire directement dans le
  plugin** via l'**Assistant CN** intégré (voir ci-dessous).
- **Recommandation automatique** de la formule de Tc la plus adaptée à la
  surface de chaque bassin, selon les domaines de validité usuels de la
  littérature.
- **Rapport PDF complet** : méthodologie, toutes les formules utilisées,
  discussion sur les écarts entre formules de Tc et l'influence de la
  résolution du MNT, interprétation morphométrique automatique par bassin
  (forme, stade géomorphologique, relief, densité de drainage), analyse des
  temps de concentration et recommandation de formule.
- **Export CSV** de tous les résultats numériques.
- **Export Shapefile** : tous les bassins regroupés en une seule couche
  numérotée (`ID_BASSIN`) avec tous les paramètres en table attributaire, et
  tous les réseaux hydrographiques regroupés en une seule couche.
- **Robustesse** : réparation automatique des géométries invalides, isolement
  des erreurs bassin par bassin (un bassin problématique n'interrompt pas le
  traitement des autres), barre de progression.

## Prérequis

- QGIS ≥ 3.16, avec le **fournisseur de traitements GRASS activé**
  (*Extensions > Gérer et installer les extensions > Traitements*, ou
  *Traitement > Options > Fournisseurs*).
- GRASS 7 ou GRASS 8 installé (fourni avec la plupart des distributions
  QGIS standalone ; sous OSGeo4W, vérifier que le paquet GRASS est coché à
  l'installation).
- Optionnel, pour l'ordre de Strahler et les rapports de Horton : extension
  GRASS `r.stream.order` (à installer via `g.extension extension=r.stream.order`
  dans une console GRASS). Sans elle, le plugin utilise automatiquement un
  repli (`r.to.vect`) qui fournit le réseau et la densité de drainage, mais
  pas l'ordre de Strahler.

## Installation

1. Téléchargez le fichier `.zip` de HydroSuiteBM Pro.
2. Dans QGIS : *Extensions > Gérer et installer les extensions > Installer
   depuis un ZIP*, sélectionnez le fichier téléchargé, cliquez sur
   *Installer le plugin*.
3. Activez le plugin dans la liste si nécessaire.
4. Le plugin apparaît dans le menu *HydroSuiteBM Pro* et dans la barre
   d'outils.

## Guide d'utilisation

1. **Sélectionnez le MNT** (raster) à analyser.
2. *(Optionnel)* Sélectionnez un **raster Curve Number (CN)**, si vous en
   disposez déjà un, pour activer le calcul du Tc-SCS — ou construisez-en
   un directement avec l'**Assistant CN** (bouton à côté du sélecteur,
   voir section suivante).
3. **Choisissez le mode** :
   - Mode manuel : sélectionnez une couche de points exutoires (et,
     optionnellement, un champ identifiant chaque bassin).
   - Mode automatique : cochez la case correspondante (aucun point requis).
4. Réglez la **surface minimale des sous-bassins** (ha ou km²) — ce
   paramètre contrôle à la fois la densité du réseau extrait et (en mode
   automatique) la taille des sous-bassins générés.
5. *(Mode manuel uniquement)* Choisissez la **méthode de calage** des
   exutoires (accumulation maximale recommandée, ou réseau extrait).
6. *(Optionnel)* Cochez l'export Shapefile et choisissez un dossier de
   sortie.
7. Cliquez sur **Lancer le calcul**. Suivez la progression dans la barre et
   le journal.
8. Consultez les résultats dans le tableau, puis :
   - **Exporter en CSV** pour les données brutes,
   - **Générer le rapport PDF** pour le document complet (méthodologie +
     analyse interprétée).

## Assistant CN — pourquoi construire son propre raster Curve Number

De nombreux outils calculent automatiquement le Curve Number à partir de
jeux de données mondiaux (occupation du sol satellite × base de sols
mondiale). C'est pratique, mais la fiabilité de ces jeux de données
mondiaux varie fortement selon les régions : les zones les mieux
cartographiées (Amérique du Nord, Europe) sont généralement fiables, mais
les zones moins densément documentées — dont une grande partie de
l'Afrique subsaharienne — peuvent présenter des lacunes, une résolution
insuffisante, ou des combinaisons occupation du sol/sol non couvertes par
la table de correspondance de l'outil. **Exemple observé (2026)** : sur
une zone au Sénégal, l'outil de calcul de Curve Number global d'un plugin
QGIS concurrent (ArcGeek Calculator, module "Global Curve Number") a
échoué avec l'erreur `list indices must be integers or slices, not
NoneType` lors du croisement des données ESA WorldCover et ORNL HYSOG —
signe d'une combinaison occupation du sol/groupe de sol présente
localement mais absente de la table de correspondance interne de l'outil.

HydroSuiteBM Pro prend le parti inverse : plutôt que de dépendre d'un jeu
de données mondial automatique, l'**Assistant CN** (bouton à côté du
sélecteur de raster CN) vous laisse construire le raster CN à partir de
**vos propres couches locales** :

1. Sélectionnez votre raster d'occupation du sol et votre raster de
   groupe hydrologique de sol (A/B/C/D).
2. Cliquez sur **Détecter les classes présentes** : le plugin liste
   automatiquement toutes les valeurs de pixel distinctes trouvées dans
   chaque raster.
3. Associez chaque valeur à une catégorie standard du NRCS (occupation du
   sol) ou à un groupe hydrologique A/B/C/D (sol), via les menus
   déroulants.
4. Cliquez sur **Générer le raster CN**. Le plugin applique la table de
   correspondance NRCS (TR-55) et écrit un raster CN aligné sur votre
   couche d'occupation du sol.

**Toute combinaison non associée à une catégorie est explicitement
comptabilisée et laissée en `nodata`** (avec la liste des codes bruts
concernés affichée à l'écran), plutôt que de provoquer un plantage ou
d'être remplacée silencieusement par une valeur arbitraire. Vous savez
donc toujours précisément quelle proportion de votre zone d'étude est
couverte, et pouvez compléter la correspondance si nécessaire avant de
relancer.

## Paramètres calculés

| Catégorie | Paramètres |
|---|---|
| Géométrie | Surface, périmètre, Kc (Gravelius), rectangle équivalent, Rc (Miller), Re (Schumm) |
| Altimétrie | Altitudes min/max/moyenne/médiane, dénivelée, Hi (intégrale hypsométrique), pente moyenne, Ig (pente globale), Ds (dénivelée spécifique) |
| Réseau | Longueur totale, nombre de tronçons, densité de drainage, fréquence, ordre de Strahler max, Rb et Rl (Horton) |
| Temps de concentration | Kirpich, Giandotti, Passini, Ventura, SCS (si CN fourni), formule recommandée |
| SCS-CN | Curve Number moyen pondéré, rétention potentielle S |

## Formules utilisées

Voir le rapport PDF généré par le plugin (section 2) pour le détail complet
des formules, unités, et domaines de validité usuels de chaque méthode de
temps de concentration. Voir aussi le manuel PDF fourni avec le plugin.

## Sorties produites

- `bassins_versants.shp` (+ `.dbf`, `.shx`, `.prj`) : tous les bassins, un
  enregistrement par bassin, avec tous les paramètres calculés en table
  attributaire (noms de champs abrégés ≤ 10 caractères, contrainte du
  format Shapefile).
- `bassins_versants_legende.csv` : correspondance entre les champs abrégés
  du shapefile et leur nom complet / description.
- `reseaux_hydrographiques.shp` : tous les réseaux hydrographiques
  découpés, regroupés en une seule couche avec un champ `ID_BASSIN`.
- `resultats_bv.csv` (à la demande) : export CSV de tous les résultats.
- `rapport_bv_toolbox.pdf` (à la demande) : rapport complet.

## Limitations connues

- Le calcul du Curve Number nécessite un raster CN : soit fourni
  directement, soit construit avec l'**Assistant CN** à partir de vos
  propres couches d'occupation du sol et de groupe hydrologique de sol.
  Le plugin n'inclut pas de jeu de données mondial automatique (voir la
  section "Assistant CN" pour les raisons de ce choix) : vous devez
  disposer de ces deux couches localement, ou les obtenir par ailleurs
  (classification d'imagerie satellite, cartes pédologiques nationales...).
- Les domaines de validité indiqués pour les formules de Tc sont des ordres
  de grandeur usuels de la littérature, pas une norme universellement
  fixée : ils varient selon les sources.
- L'ordre de Strahler et les rapports de Horton nécessitent l'extension
  GRASS `r.stream.order` (non fournie par défaut avec GRASS).
- La recherche du point d'exutoire (mode automatique) et le calage par
  accumulation maximale (mode manuel) effectuent un balayage de pixels en
  Python : sur de très grands MNT ou de très nombreux sous-bassins, le
  traitement peut être long.

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| "Algorithme grass:r.stream.order not found" | Extension GRASS non installée | Le plugin bascule automatiquement sur `r.to.vect` (repli), ou installez `g.extension extension=r.stream.order` |
| Bassin obtenu minuscule par rapport au MNT | Mauvais calage de l'exutoire ou CRS différent entre MNT et points | Utilisez le calage "accumulation maximale" ; vérifiez le CRS des couches |
| "has invalid geometry" | Géométries auto-intersectantes issues de la vectorisation | Corrigé automatiquement depuis la version 1.0 (réparation systématique) |
| Un seul bassin en mode automatique | Seuil trop élevé, ou SFD au lieu de MFD | Réduire la surface minimale ; cocher "Directions de flux multiples (MFD)" |

## Licence

Ce plugin utilise l'API PyQGIS et est distribué sous licence GPL v2 ou
ultérieure, comme l'exige QGIS pour les extensions utilisant son API.
