# -*- coding: utf-8 -*-
import os
import traceback

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QFileDialog, QMessageBox, QTabWidget, QWidget, QHeaderView, QComboBox,
    QCheckBox, QProgressBar, QApplication, QLineEdit
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox
from qgis.core import (
    QgsMapLayerProxyModel, QgsProject, QgsWkbTypes, QgsVectorLayer,
    QgsFeature, QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsVectorFileWriter
)

from .core import geometry_params, morphometry_params, hydrography_params, delineation, report, pdf_report, symbology
from .cn_assistant_dialog import CNAssistantDialog


class HydroSuiteBMProDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("HydroSuiteBM Pro - Analyse de bassin(s) versant(s)")
        self.resize(760, 620)
        self.results_by_basin = {}
        self.basin_records = []
        self.last_run_info = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        form = QFormLayout()

        self.cbo_dem = QgsMapLayerComboBox()
        self.cbo_dem.setFilters(QgsMapLayerProxyModel.RasterLayer)
        form.addRow("MNT (raster) :", self.cbo_dem)

        cn_row = QHBoxLayout()
        self.cbo_cn = QgsMapLayerComboBox()
        self.cbo_cn.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.cbo_cn.setAllowEmptyLayer(True)
        self.cbo_cn.setLayer(None)
        self.cbo_cn.setToolTip(
            "Optionnel. Raster où chaque pixel porte déjà la valeur du Curve Number (CN, "
            "méthode SCS-CN), préparé au préalable en croisant occupation du sol et groupe "
            "hydrologique de sol avec les tables du NRCS. Si fourni, le plugin calcule la "
            "moyenne pondérée du CN sur chaque bassin, puis le temps de concentration par la "
            "méthode SCS (lag method, TR-55). Laissez vide si vous n'avez pas cette donnée : "
            "le calcul du Tc-SCS et du CN sera simplement absent des résultats."
        )
        self.btn_cn_assistant = QPushButton("Assistant CN...")
        self.btn_cn_assistant.setToolTip(
            "Construire un raster CN à partir de vos propres couches d'occupation du sol et "
            "de groupe hydrologique de sol (recommandé plutôt qu'un jeu de données mondial "
            "automatique, de fiabilité variable selon les régions)."
        )
        self.btn_cn_assistant.clicked.connect(self._open_cn_assistant)
        cn_row.addWidget(self.cbo_cn)
        cn_row.addWidget(self.btn_cn_assistant)
        form.addRow("Raster Curve Number (CN, optionnel) :", cn_row)

        self.chk_auto_mode = QCheckBox(
            "Mode automatique : découper tout le MNT en sous-bassins versants "
            "(comme la sortie 'basin' de r.watershed, sans points exutoires)"
        )
        self.chk_auto_mode.setToolTip(
            "Si coché, aucun point exutoire n'est nécessaire : le plugin délimite "
            "automatiquement TOUS les sous-bassins versants du MNT en fonction du "
            "seuil d'accumulation ci-dessous (un sous-bassin par tronçon de réseau "
            "exutoire). Si décoché (comportement historique), un bassin est calculé "
            "par point exutoire fourni."
        )
        self.chk_auto_mode.toggled.connect(self._on_auto_mode_toggled)
        form.addRow(self.chk_auto_mode)

        self.cbo_outlets = QgsMapLayerComboBox()
        self.cbo_outlets.setFilters(QgsMapLayerProxyModel.PointLayer)
        form.addRow("Points exutoires (couche ponctuelle) :", self.cbo_outlets)

        self.cbo_name_field = QgsFieldComboBox()
        self.cbo_name_field.setLayer(self.cbo_outlets.currentLayer())
        self.cbo_outlets.layerChanged.connect(self.cbo_name_field.setLayer)
        form.addRow("Champ identifiant le bassin (optionnel) :", self.cbo_name_field)

        area_row = QHBoxLayout()
        self.spin_min_area = QDoubleSpinBox()
        self.spin_min_area.setRange(0.001, 1000000)
        self.spin_min_area.setDecimals(3)
        self.spin_min_area.setValue(5.0)
        self.cbo_min_area_unit = QComboBox()
        self.cbo_min_area_unit.addItem("ha", "ha")
        self.cbo_min_area_unit.addItem("km²", "km2")
        area_row.addWidget(self.spin_min_area)
        area_row.addWidget(self.cbo_min_area_unit)
        self.lbl_min_area_cells = QLabel("")
        self.lbl_min_area_cells.setStyleSheet("color: grey; font-style: italic;")
        area_row_widget = QWidget()
        area_col = QVBoxLayout()
        area_col.setContentsMargins(0, 0, 0, 0)
        area_col.addLayout(area_row)
        area_col.addWidget(self.lbl_min_area_cells)
        area_row_widget.setLayout(area_col)
        self.spin_min_area.valueChanged.connect(self._update_min_area_preview)
        self.cbo_min_area_unit.currentIndexChanged.connect(self._update_min_area_preview)
        self.cbo_dem.layerChanged.connect(self._update_min_area_preview)
        self.spin_min_area.setToolTip(
            "Contrôle à la fois la densité du réseau extrait ET, en mode automatique, "
            "la taille minimale de chaque sous-bassin généré : plus la valeur est basse, "
            "plus vous obtenez de sous-bassins, petits ; plus elle est haute, moins vous "
            "en obtenez, mais plus grands. Convertie en interne en nombre de cellules "
            "selon la résolution du MNT sélectionné."
        )
        form.addRow("Surface minimale des sous-bassins :", area_row_widget)

        self.chk_mfd = QCheckBox("Directions de flux multiples (MFD) — comportement par défaut de r.watershed")
        self.chk_mfd.setChecked(True)
        self.chk_mfd.setToolTip(
            "Coché (recommandé) : utilise l'algorithme MFD de r.watershed, celui utilisé "
            "par défaut quand on lance r.watershed depuis la boîte à outils Traitement. "
            "Décoché : force le mode SFD (direction de flux unique), plus rapide mais qui "
            "tend à fusionner beaucoup de sous-bassins en quelques très grandes zones — "
            "décochez uniquement si vous cherchez la vitesse plutôt qu'un découpage fidèle."
        )
        form.addRow(self.chk_mfd)

        self.cbo_snap_method = QComboBox()
        self.cbo_snap_method.addItem(
            "Accumulation de flux maximale (recommandé, robuste au seuil)", "max_accum"
        )
        self.cbo_snap_method.addItem(
            "Réseau extrait par seuillage (r.stream.snap)", "stream_snap"
        )
        self.cbo_snap_method.addItem("Aucun calage (point saisi tel quel)", "none")
        self.cbo_snap_method.setToolTip(
            "Accumulation de flux maximale : cherche, dans un voisinage autour du point "
            "saisi, la cellule ayant la plus forte accumulation de flux amont, et y déplace "
            "l'exutoire. Ne dépend pas du seuil du réseau, donc plus fiable si le point est "
            "proche d'un chenal mais pas capté par le réseau extrait.\n\n"
            "Réseau extrait (r.stream.snap) : cale le point sur la cellule du réseau "
            "vectorisé la plus proche (comportement historique du plugin)."
        )
        form.addRow("Méthode de calage de l'exutoire :", self.cbo_snap_method)

        self.spin_snap_radius = QSpinBox()
        self.spin_snap_radius.setRange(0, 200)
        self.spin_snap_radius.setValue(10)
        self.spin_snap_radius.setToolTip(
            "Rayon de recherche (en cellules du MNT) autour du point saisi pour le calage, "
            "quelle que soit la méthode choisie ci-dessus."
        )
        form.addRow("Rayon de calage (cellules) :", self.spin_snap_radius)

        self.chk_export_shp = QCheckBox(
            "Enregistrer aussi les bassins et réseaux hydrographiques en Shapefile (.shp)"
        )
        self.chk_export_shp.setToolTip(
            "Sans cette option, les couches de bassins et de réseaux ne sont ajoutées "
            "à la carte que temporairement (elles disparaissent si vous ne les "
            "enregistrez pas manuellement)."
        )
        self.chk_export_shp.toggled.connect(self._on_export_shp_toggled)
        form.addRow(self.chk_export_shp)

        folder_row = QHBoxLayout()
        self.txt_output_folder = QLineEdit()
        self.txt_output_folder.setReadOnly(True)
        self.txt_output_folder.setPlaceholderText("Dossier de sortie des shapefiles...")
        self.btn_browse_folder = QPushButton("Parcourir...")
        self.btn_browse_folder.clicked.connect(self._choose_output_folder)
        folder_row.addWidget(self.txt_output_folder)
        folder_row.addWidget(self.btn_browse_folder)
        self.lbl_folder_row = QLabel("Dossier de sortie :")
        form.addRow(self.lbl_folder_row, folder_row)
        self._on_export_shp_toggled(False)  # désactivé tant que la case n'est pas cochée

        main_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("Lancer le calcul")
        self.btn_run.clicked.connect(self.run_analysis)
        self.btn_export_csv = QPushButton("Exporter en CSV")
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_csv.setEnabled(False)
        self.btn_export_pdf = QPushButton("Générer le rapport PDF")
        self.btn_export_pdf.clicked.connect(self.export_pdf_report)
        self.btn_export_pdf.setEnabled(False)
        btn_layout.addWidget(self.btn_run)
        btn_layout.addWidget(self.btn_export_csv)
        btn_layout.addWidget(self.btn_export_pdf)
        main_layout.addLayout(btn_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("En attente...")
        main_layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.table_results = QTableWidget()
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.table_results, "Résultats")
        self.tabs.addTab(self.log, "Journal")
        main_layout.addWidget(self.tabs)

    def _dem_pixel_area_m2(self):
        """Surface (m²) d'une cellule du MNT actuellement sélectionné, ou None."""
        dem_layer = self.cbo_dem.currentLayer()
        if dem_layer is None or dem_layer.width() == 0 or dem_layer.height() == 0:
            return None
        extent = dem_layer.extent()
        px_w = extent.width() / dem_layer.width()
        px_h = extent.height() / dem_layer.height()
        return px_w * px_h

    def _min_area_to_cells(self):
        """Convertit la surface minimale saisie (ha ou km²) en nombre de cellules du MNT."""
        pixel_area_m2 = self._dem_pixel_area_m2()
        if not pixel_area_m2:
            return None
        unit = self.cbo_min_area_unit.currentData()
        area_m2 = self.spin_min_area.value() * (10000 if unit == "ha" else 1_000_000)
        return max(1, round(area_m2 / pixel_area_m2))

    def _update_min_area_preview(self, *args):
        cells = self._min_area_to_cells()
        if cells is None:
            self.lbl_min_area_cells.setText("(sélectionnez un MNT pour voir l'équivalence en cellules)")
        else:
            self.lbl_min_area_cells.setText(f"≈ {cells} cellules du MNT sélectionné")

    def _keep_on_top(self):
        """
        Remet la fenêtre du plugin au premier plan. Nécessaire car certaines
        opérations (ajout de couche au projet, rafraîchissement du canevas
        QGIS déclenché par GRASS/processing) peuvent faire repasser la
        fenêtre principale de QGIS devant cette boîte de dialogue non
        modale, donnant l'impression qu'elle "disparaît" pendant le calcul.
        """
        self.raise_()
        self.activateWindow()

    def _set_progress_raw(self, pct, msg):
        self.progress.setValue(pct)
        self.progress.setFormat(f"{msg} (%p%)")
        self.log_msg(msg)
        QApplication.processEvents()
        self._keep_on_top()

    def _set_progress(self, done, total, basin_id=""):
        # Les étapes de prétraitement (comblement, accumulation, réseau...) occupent
        # 0-40% ; la boucle de traitement bassin par bassin occupe les 40-100% restants.
        frac = (done / total) if total else 1.0
        pct = 40 + int(round(frac * 60))
        self.progress.setValue(pct)
        if basin_id:
            self.progress.setFormat(f"{done}/{total} — {basin_id} (%p%)")
        else:
            self.progress.setFormat(f"Terminé ({total}/{total})" if total else "Terminé")
        QApplication.processEvents()  # garde l'interface réactive pendant le traitement
        self._keep_on_top()

    def log_msg(self, msg):
        self.log.append(msg)

    def _on_export_shp_toggled(self, checked):
        self.txt_output_folder.setEnabled(checked)
        self.btn_browse_folder.setEnabled(checked)
        self.lbl_folder_row.setEnabled(checked)

    def _choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de sortie des shapefiles")
        if folder:
            self.txt_output_folder.setText(folder)

    def _export_shp(self, layer, filename):
        """Écrit `layer` en Shapefile dans le dossier de sortie choisi, si l'option est active."""
        if not self.chk_export_shp.isChecked():
            return None
        folder = self.txt_output_folder.text().strip()
        if not folder:
            self.log_msg("  [!] Export shapefile activé mais aucun dossier de sortie choisi -> ignoré.")
            return None
        if layer is None or layer.featureCount() == 0:
            return None
        if not filename.lower().endswith(".shp"):
            filename += ".shp"
        # Noms de fichiers Windows/shapefile : on évite les caractères problématiques.
        safe_filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
        path = os.path.join(folder, safe_filename)
        try:
            result = QgsVectorFileWriter.writeAsVectorFormat(
                layer, path, "UTF-8", layer.crs(), "ESRI Shapefile"
            )
            error_code = result[0] if isinstance(result, tuple) else result
            if error_code != QgsVectorFileWriter.NoError:
                self.log_msg(f"  [!] Échec de l'export '{safe_filename}' (code {error_code}).")
                return None
            self.log_msg(f"  Exporté : {path}")
            return path
        except Exception as e:
            self.log_msg(f"  [!] Échec de l'export '{safe_filename}' : {e}")
            return None

    def _open_cn_assistant(self):
        dlg = CNAssistantDialog(self)
        dlg.exec_()
        if dlg.generated_layer is not None and dlg.generated_layer.isValid():
            # Sélectionne automatiquement le raster CN qui vient d'être généré.
            self.cbo_cn.setLayer(dlg.generated_layer)

    def _on_auto_mode_toggled(self, checked):
        """En mode automatique, les points exutoires et le calage n'ont plus de sens."""
        self.cbo_outlets.setEnabled(not checked)
        self.cbo_name_field.setEnabled(not checked)
        self.cbo_snap_method.setEnabled(not checked)
        self.spin_snap_radius.setEnabled(not checked)

    # ------------------------------------------------------------------
    # Traitement principal
    # ------------------------------------------------------------------
    def run_analysis(self):
        self._keep_on_top()
        dem_layer = self.cbo_dem.currentLayer()
        auto_mode = self.chk_auto_mode.isChecked()
        outlets_layer = self.cbo_outlets.currentLayer()

        if dem_layer is None:
            QMessageBox.warning(self, "HydroSuiteBM Pro", "Sélectionnez un MNT.")
            return
        if not auto_mode and outlets_layer is None:
            QMessageBox.warning(
                self, "HydroSuiteBM Pro",
                "Sélectionnez une couche de points exutoires, ou cochez le mode automatique."
            )
            return

        name_field = self.cbo_name_field.currentField()
        threshold = self._min_area_to_cells()
        if not threshold:
            QMessageBox.warning(self, "HydroSuiteBM Pro", "Impossible de déterminer la résolution du MNT sélectionné.")
            return
        unit_label = "ha" if self.cbo_min_area_unit.currentData() == "ha" else "km²"
        self.log_msg(
            f"Surface minimale des sous-bassins : {self.spin_min_area.value()} {unit_label} "
            f"(≈ {threshold} cellules du MNT, résolution {self._dem_pixel_area_m2():.1f} m²/cellule)."
        )
        snap_radius = self.spin_snap_radius.value()
        crs = dem_layer.crs()
        epsg = crs.postgisSrid() if crs.postgisSrid() else int(crs.authid().split(":")[-1])

        self.results_by_basin = {}
        self.basin_records = []  # (basin_id, geometry, results) -- pour la couche combinée finale
        self.stream_records = []  # (basin_id, streams_clip_layer) -- pour le réseau combiné final
        self.log.clear()
        self.progress.setValue(0)
        self.progress.setFormat("Démarrage...")
        QApplication.processEvents()

        # Reprojection des points exutoires vers le CRS du MNT (mode manuel uniquement).
        if not auto_mode and outlets_layer.crs() != crs:
            self.log_msg(
                f"Reprojection des points exutoires ({outlets_layer.crs().authid()} -> {crs.authid()})..."
            )
            transform = QgsCoordinateTransform(outlets_layer.crs(), crs, QgsProject.instance())
            reproj_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "exutoires_reprojetes", "memory")
            reproj_provider = reproj_layer.dataProvider()
            reproj_provider.addAttributes(outlets_layer.fields())
            reproj_layer.updateFields()
            new_feats = []
            for feat in outlets_layer.getFeatures():
                geom = QgsGeometry(feat.geometry())
                geom.transform(transform)
                new_feat = QgsFeature(reproj_layer.fields())
                new_feat.setGeometry(geom)
                new_feat.setAttributes(feat.attributes())
                new_feats.append(new_feat)
            reproj_provider.addFeatures(new_feats)
            reproj_layer.updateExtents()
            outlets_layer = reproj_layer

        try:
            self._set_progress_raw(5, "Comblement des dépressions du MNT...")
            dem_filled = delineation.fill_sinks(dem_layer)

            self._set_progress_raw(15, "Calcul de la direction / accumulation de flux...")
            # En mode automatique, on demande directement à r.watershed sa sortie
            # 'basin' (découpage automatique en sous-bassins), avec le même seuil
            # que celui utilisé pour le réseau -- cohérence entre réseau et bassins.
            accumulation, drainage, basin_raster_auto = delineation.flow_direction_accumulation(
                dem_filled, threshold=threshold if auto_mode else None, sfd=not self.chk_mfd.isChecked()
            )

            self._set_progress_raw(30, "Extraction du réseau hydrographique...")
            stream_raster, stream_dir = delineation.extract_stream_network(
                dem_filled, accumulation, threshold
            )

            self._set_progress_raw(40, "Vectorisation du réseau et calcul de l'ordre de Strahler...")
            try:
                streams_network, has_strahler_order = delineation.stream_order_network(
                    dem_filled, accumulation, stream_raster, stream_dir
                )
                # Cette couche complète n'est pas ajoutée à la carte ni exportée : elle sert
                # uniquement de base interne pour découper le réseau par bassin (couche
                # "reseaux_hydrographiques" finale, non redondante) et calculer le talweg.
                if not has_strahler_order:
                    self.log_msg(
                        "  [!] Extension GRASS 'r.stream.order' non installée : réseau généré via "
                        "r.to.vect à la place (module du cœur de GRASS). La densité de drainage et "
                        "la longueur du réseau restent calculées ; seuls les rapports de Horton (Rb, Rl) "
                        "et l'ordre de Strahler max sont absents des résultats."
                    )
                    self.log_msg(
                        "      -> Pour les obtenir, installez l'extension : ouvrez une console GRASS "
                        "(ou Traitement > Boîte à outils > GRASS) et exécutez : "
                        "g.extension extension=r.stream.order"
                    )
            except Exception as e:
                streams_network = None
                self.log_msg(f"  [!] Réseau hydrographique non généré : {e}")
                self.log_msg("      -> la densité de drainage et les rapports de Horton seront absents des résultats.")

            # Surface totale du MNT, pour comparer avec la surface des bassins obtenus
            dem_extent = dem_layer.extent()
            dem_area_km2 = (dem_extent.width() * dem_extent.height()) / 1e6

            if auto_mode:
                self._run_auto_mode(
                    dem_layer, epsg, accumulation, drainage, basin_raster_auto,
                    streams_network, dem_area_km2
                )
            else:
                self._run_manual_mode(
                    dem_layer, epsg, outlets_layer, name_field, threshold, snap_radius,
                    accumulation, drainage, stream_raster, streams_network, dem_area_km2
                )

            if self.basin_records:
                self.log_msg("Construction de la couche combinée de tous les bassins...")
                basins_layer, used_keys = report.build_basins_layer(self.basin_records, dem_layer.crs())
                basins_layer.setName("bassins_versants")
                QgsProject.instance().addMapLayer(basins_layer)
                try:
                    symbology.style_basins_by_surface(basins_layer)
                except Exception as e:
                    self.log_msg(f"  [i] Symbologie automatique par surface non appliquée ({e}).")
                self._keep_on_top()
                exported_path = self._export_shp(basins_layer, "bassins_versants.shp")
                if exported_path:
                    legend_path = os.path.join(os.path.dirname(exported_path), "bassins_versants_legende.csv")
                    report.write_field_legend(used_keys, legend_path)
                    self.log_msg(f"  Légende des champs : {legend_path}")

            if self.stream_records:
                self.log_msg("Construction de la couche combinée des réseaux hydrographiques...")
                streams_layer = report.build_combined_lines_layer(self.stream_records, dem_layer.crs())
                if streams_layer is not None and streams_layer.featureCount() > 0:
                    streams_layer.setName("reseaux_hydrographiques")
                    QgsProject.instance().addMapLayer(streams_layer)
                    self._keep_on_top()
                    self._export_shp(streams_layer, "reseaux_hydrographiques.shp")

            self._populate_table()
            self.btn_export_csv.setEnabled(bool(self.results_by_basin))
            self.btn_export_pdf.setEnabled(bool(self.basin_records))

            dem_extent_for_info = dem_layer.extent()
            px_w = dem_extent_for_info.width() / dem_layer.width() if dem_layer.width() else None
            px_h = dem_extent_for_info.height() / dem_layer.height() if dem_layer.height() else None
            unit_label = "ha" if self.cbo_min_area_unit.currentData() == "ha" else "km²"
            self.last_run_info = {
                "dem_name": dem_layer.name(),
                "px_w": px_w,
                "px_h": px_h,
                "resolution_label": f"{px_w:.1f} m x {px_h:.1f} m" if px_w and px_h else "inconnue",
                "mode_label": "Automatique (tout le MNT)" if auto_mode else "Manuel (points exutoires)",
                "min_area_label": f"{self.spin_min_area.value()} {unit_label} (≈ {threshold} cellules)",
                "flow_algo_label": "MFD (directions multiples)" if self.chk_mfd.isChecked() else "SFD (direction unique)",
                "snap_method_label": self.cbo_snap_method.currentText() if not auto_mode else "n/a (mode automatique)",
                "n_basins": len(self.basin_records),
            }

            self.progress.setValue(100)
            self.progress.setFormat(f"Terminé — {len(self.results_by_basin)} bassin(s) (%p%)")
            self.log_msg("Calcul terminé.")
            self._keep_on_top()

        except Exception as e:
            self.progress.setFormat("Échec du traitement")
            self.log_msg("ERREUR : " + str(e))
            self.log_msg(traceback.format_exc())
            self._keep_on_top()
            QMessageBox.critical(
                self, "HydroSuiteBM Pro",
                "Une erreur est survenue pendant le traitement.\n"
                "Vérifiez que le fournisseur GRASS est activé dans "
                "Extensions > Gérer et installer les extensions > Traitements.\n\n"
                f"Détail : {e}"
            )

    # ------------------------------------------------------------------
    # Mode manuel : un bassin par point exutoire fourni
    # ------------------------------------------------------------------
    def _run_manual_mode(self, dem_layer, epsg, outlets_layer, name_field, threshold, snap_radius,
                          accumulation, drainage, stream_raster, streams_network, dem_area_km2):
        # Calage des exutoires (méthode choisie dans l'UI)
        snap_method = self.cbo_snap_method.currentData()
        positioned_outlets = outlets_layer
        if snap_method == "max_accum" and snap_radius > 0:
            try:
                self.log_msg(
                    f"Calage des exutoires sur l'accumulation de flux maximale "
                    f"(rayon de recherche = {snap_radius} cellules)..."
                )
                positioned_outlets = delineation.snap_outlets_to_max_accumulation(
                    outlets_layer, accumulation, snap_radius
                )
            except Exception as e:
                self.log_msg(f"  [!] Calage par accumulation impossible ({e}), utilisation des points d'origine.")
                positioned_outlets = outlets_layer
        elif snap_method == "stream_snap" and snap_radius > 0:
            try:
                self.log_msg(f"Calage des points exutoires sur le réseau (rayon = {snap_radius} cellules)...")
                positioned_outlets = delineation.snap_outlets_to_stream(
                    outlets_layer, stream_raster, snap_radius
                )
            except Exception as e:
                self.log_msg(
                    f"  [!] Calage des exutoires impossible ({e}), utilisation des points d'origine. "
                    f"(Si l'erreur mentionne 'not found', 'r.stream.snap' fait partie du même paquet "
                    f"d'extensions GRASS que 'r.stream.order' -- utilisez plutôt la méthode "
                    f"'Accumulation de flux maximale', qui ne nécessite aucune extension.)"
                )
                positioned_outlets = outlets_layer
        else:
            self.log_msg("Aucun calage appliqué : utilisation des points exutoires tels que saisis.")

        # Points d'origine (avant calage), pour mesurer la distance de calage
        original_points = [feat.geometry().asPoint() for feat in outlets_layer.getFeatures()]

        n_outlets = positioned_outlets.featureCount()
        seen_basin_ids = {}
        for i, feat in enumerate(positioned_outlets.getFeatures()):
            pt = feat.geometry().asPoint()
            basin_id = str(feat[name_field]) if (name_field and name_field in feat.fields().names()) else f"bassin_{i+1}"
            basin_id = self._unique_basin_id(basin_id, seen_basin_ids, name_field)

            self._set_progress(i, n_outlets, basin_id)
            self.log_msg(f"--- Traitement de '{basin_id}' ({i+1}/{n_outlets}) ---")

            try:
                # --- Diagnostic : accumulation de flux au point + distance de calage ---
                acc_value = delineation.sample_raster_value(accumulation, pt.x(), pt.y())
                acc_txt = f"{acc_value:.0f} cellules" if acc_value is not None else "indisponible (hors emprise ?)"
                self.log_msg(f"  Accumulation de flux au point utilisé : {acc_txt}")
                if i < len(original_points):
                    orig_pt = original_points[i]
                    dist = ((pt.x() - orig_pt.x()) ** 2 + (pt.y() - orig_pt.y()) ** 2) ** 0.5
                    self.log_msg(f"  Distance de calage par rapport au point saisi : {dist:.1f} m")
                if acc_value is not None and threshold and acc_value < threshold:
                    self.log_msg(
                        f"  [!] Attention : l'accumulation au point ({acc_value:.0f}) est inférieure "
                        f"au seuil du réseau ({threshold}) -> le point n'est probablement pas sur le "
                        f"chenal principal, le bassin délimité risque d'être minuscule."
                    )

                basin_raster = delineation.delineate_basin_raster(drainage, pt.x(), pt.y())
                basin_vector = delineation.raster_basin_to_polygon(basin_raster)

                if basin_vector.featureCount() == 0:
                    self.log_msg(f"  [!] Aucun bassin délimité pour '{basin_id}' (vérifier le point exutoire).")
                    continue

                basin_feat = next(basin_vector.getFeatures())
                geom = basin_feat.geometry()
                if geom is None or geom.isEmpty() or geom.area() <= 0:
                    self.log_msg(f"  [!] Géométrie vide/dégénérée pour '{basin_id}' -> ignoré.")
                    continue

                self._process_one_basin(
                    basin_id, geom, QgsPointXY(pt.x(), pt.y()), basin_vector,
                    dem_layer, epsg, streams_network, dem_area_km2
                )
            except Exception as e:
                # Une erreur sur UN exutoire ne doit pas interrompre le traitement des autres.
                self.log_msg(f"  [!] Erreur sur '{basin_id}', bassin ignoré : {e}")
                self.log_msg("      " + traceback.format_exc().replace("\n", "\n      "))

        self._set_progress(n_outlets, n_outlets, "")

    # ------------------------------------------------------------------
    # Mode automatique : tous les sous-bassins du MNT (façon r.watershed)
    # ------------------------------------------------------------------
    def _run_auto_mode(self, dem_layer, epsg, accumulation, drainage, basin_raster_auto,
                        streams_network, dem_area_km2):
        if basin_raster_auto is None:
            self.log_msg("[!] r.watershed n'a pas produit de sortie 'basin'. Vérifiez le seuil et la version de GRASS.")
            return

        self.log_msg("Vectorisation des sous-bassins automatiques (sortie 'basin' de r.watershed)...")
        basin_polygons = delineation.polygonize_basins(basin_raster_auto)
        n_basins = basin_polygons.featureCount()
        self.log_msg(f"{n_basins} sous-bassin(s) détecté(s) pour ce seuil.")
        if n_basins == 0:
            self.log_msg("[!] Aucun sous-bassin détecté : essayez de réduire le seuil d'accumulation.")
            return
        if n_basins > 200:
            self.log_msg(
                f"  [!] Attention : {n_basins} sous-bassins, le traitement peut être long. "
                f"Augmentez le seuil pour en réduire le nombre si besoin."
            )

        seen_basin_ids = {}
        for i, feat in enumerate(basin_polygons.getFeatures()):
            dn = feat["DN"]
            basin_id = f"sous_bassin_{dn}"
            basin_id = self._unique_basin_id(basin_id, seen_basin_ids, "DN")
            geom = feat.geometry()

            self._set_progress(i, n_basins, basin_id)
            self.log_msg(f"--- Traitement de '{basin_id}' ({i+1}/{n_basins}) ---")

            if geom is None or geom.isEmpty() or geom.area() <= 0:
                self.log_msg(f"  [!] Géométrie vide/dégénérée pour '{basin_id}' -> ignoré.")
                continue

            try:
                outlet_info = delineation.find_outlet_in_polygon(accumulation, geom)
                if outlet_info is None:
                    self.log_msg(
                        f"  [!] Exutoire introuvable pour '{basin_id}' (sous-bassin trop grand ou "
                        f"entièrement en nodata) -> ignoré."
                    )
                    continue
                outlet_x, outlet_y, acc_value = outlet_info
                self.log_msg(f"  Exutoire détecté (accumulation = {acc_value:.0f} cellules).")

                # On matérialise le polygone dans une couche mono-entité pour réutiliser
                # les mêmes fonctions de découpage/statistiques que le mode manuel.
                single_basin_layer = QgsVectorLayer(f"Polygon?crs={dem_layer.crs().authid()}", basin_id, "memory")
                single_basin_layer.dataProvider().addFeatures([feat])

                self._process_one_basin(
                    basin_id, geom, QgsPointXY(outlet_x, outlet_y), single_basin_layer,
                    dem_layer, epsg, streams_network, dem_area_km2
                )
            except Exception as e:
                # Une erreur sur UN sous-bassin (géométrie dégénérée, cas limite...) ne
                # doit pas interrompre le traitement des autres sous-bassins.
                self.log_msg(f"  [!] Erreur sur '{basin_id}', bassin ignoré : {e}")
                self.log_msg("      " + traceback.format_exc().replace("\n", "\n      "))

        self._set_progress(n_basins, n_basins, "")

    # ------------------------------------------------------------------
    # Logique commune de calcul des paramètres pour UN bassin (manuel ou auto)
    # ------------------------------------------------------------------
    def _unique_basin_id(self, basin_id, seen_basin_ids, field_label):
        if basin_id in seen_basin_ids:
            seen_basin_ids[basin_id] += 1
            original_basin_id = basin_id
            basin_id = f"{basin_id}_{seen_basin_ids[original_basin_id]}"
            self.log_msg(
                f"  [!] Identifiant de bassin '{original_basin_id}' déjà utilisé "
                f"(champ '{field_label}' non unique) -> renommé en '{basin_id}'."
            )
        else:
            seen_basin_ids[basin_id] = 1
        return basin_id

    def _process_one_basin(self, basin_id, geom, outlet_pt, basin_vector,
                            dem_layer, epsg, streams_network, dem_area_km2):
        area_m2 = geom.area()
        perimeter_m = geom.length()

        basin_area_km2 = area_m2 / 1e6
        ratio_pct = (basin_area_km2 / dem_area_km2 * 100) if dem_area_km2 else 0
        self.log_msg(
            f"  Surface du bassin : {basin_area_km2:.3f} km²  "
            f"(≈ {ratio_pct:.2f} % de l'emprise du MNT, {dem_area_km2:.1f} km²)"
        )

        results = {}
        results.update(geometry_params.geometric_parameters(area_m2, perimeter_m))

        # Longueur géométrique (axe outlet -> point du contour le plus éloigné) : utilisée
        # pour l'indice d'allongement de Schumm. Ce n'est PAS le talweg hydraulique réel
        # (voir longueur_talweg_km plus bas, calculé le long du réseau, pour les Tc).
        basin_length_m = geometry_params.basin_length_from_geometry(geom, outlet_pt)
        basin_length_km = basin_length_m / 1000.0 if basin_length_m else None
        results["longueur_bassin_km"] = basin_length_km
        results["indice_allongement_schumm_Re"] = geometry_params.elongation_ratio(
            results["surface_km2"], basin_length_km
        )

        self.log_msg("  Calcul des paramètres d'altitude / hypsométrie...")
        try:
            alt_stats = morphometry_params.altitude_and_hypsometric_stats(
                dem_layer.source(), geom.asWkt(), epsg
            )
            if alt_stats:
                results.update(alt_stats)
        except Exception as e:
            self.log_msg(f"  [!] Altitude/hypsométrie non calculée : {e}")

        self.log_msg("  Calcul de la pente moyenne...")
        try:
            slope_pct = morphometry_params.mean_slope_percent(
                dem_layer.source(), geom.asWkt(), epsg
            )
            results["pente_moyenne_pct"] = slope_pct
        except Exception as e:
            self.log_msg(f"  [!] Pente moyenne non calculée : {e}")

        talweg_length_km = None
        if streams_network is not None:
            try:
                self.log_msg("  Découpage du réseau hydrographique sur le bassin...")
                streams_clip = delineation.clip_streams_to_basin(streams_network, basin_vector)
                net_stats = hydrography_params.compute_network_stats(
                    streams_clip, results["surface_km2"]
                )
                results.update(net_stats)
                streams_clip.setName(f"reseau_{basin_id}")
                self.stream_records.append((basin_id, streams_clip))

                talweg_length_km = hydrography_params.longest_flow_path_km(streams_clip, outlet_pt)
                results["longueur_talweg_km"] = talweg_length_km
                if talweg_length_km:
                    self.log_msg(
                        f"  Longueur du talweg principal (chemin hydraulique le plus long "
                        f"le long du réseau) : {talweg_length_km:.3f} km"
                    )
            except Exception as e:
                self.log_msg(f"  [!] Statistiques du réseau non calculées : {e}")

        if results.get("altitude_max_m") is not None and basin_length_km:
            ig = morphometry_params.global_slope_index(
                results["altitude_max_m"], results["altitude_min_m"], basin_length_km
            )
            results["indice_pente_globale_Ig_m_par_km"] = ig
            results["denivelee_specifique_Ds"] = morphometry_params.specific_denivelation(
                ig, results["surface_km2"]
            )

        # L pour les temps de concentration : on privilégie le talweg réel (le long du
        # réseau hydrographique) ; à défaut (réseau non disponible), on retombe sur la
        # longueur géométrique du bassin, moins fidèle hydrauliquement mais préférable
        # à l'absence de résultat -- avec un avertissement clair dans le journal.
        tc_length_km = talweg_length_km if talweg_length_km else basin_length_km
        if tc_length_km and not talweg_length_km:
            self.log_msg(
                "  [!] Talweg réel indisponible (pas de réseau hydrographique) : les temps "
                "de concentration utilisent la longueur géométrique du bassin en repli, "
                "moins précise que le plus long chemin hydraulique réel."
            )
        results["longueur_utilisee_pour_tc_km"] = tc_length_km

        if tc_length_km and results.get("pente_moyenne_pct"):
            slope_frac = results["pente_moyenne_pct"] / 100.0
            results["tc_kirpich_min"] = hydrography_params.tc_kirpich(tc_length_km, slope_frac)
            if results.get("altitude_moyenne_m") is not None and results.get("altitude_min_m") is not None:
                results["tc_giandotti_h"] = hydrography_params.tc_giandotti(
                    results["surface_km2"], tc_length_km,
                    results["altitude_moyenne_m"], results["altitude_min_m"]
                )
            results["tc_passini_h"] = hydrography_params.tc_passini(
                results["surface_km2"], tc_length_km, slope_frac
            )
            results["tc_ventura_h"] = hydrography_params.tc_ventura(
                results["surface_km2"], slope_frac
            )

        # Curve Number (CN) moyen pondéré et Tc-SCS (méthode du lag, TR-55) --
        # uniquement si l'utilisateur a fourni un raster CN.
        cn_layer = self.cbo_cn.currentLayer()
        if cn_layer is not None:
            self.log_msg("  Calcul du Curve Number (CN) moyen du bassin...")
            try:
                cn_mean = morphometry_params.mean_raster_value(cn_layer.source(), geom.asWkt(), epsg)
                results["curve_number_cn"] = cn_mean
                if cn_mean is not None:
                    self.log_msg(f"  Curve Number moyen (pondéré surfaciquement) : {cn_mean:.1f}")
                    results["retention_potentielle_S_mm"] = hydrography_params.scs_retention_s_mm(cn_mean)
                    if tc_length_km and results.get("pente_moyenne_pct"):
                        results["tc_scs_h"] = hydrography_params.tc_scs_lag(
                            tc_length_km, cn_mean, results["pente_moyenne_pct"]
                        )
            except Exception as e:
                self.log_msg(f"  [!] Curve Number / Tc-SCS non calculés : {e}")

        # Recommandation automatique de la formule de Tc la plus adaptée à la
        # surface de CE bassin, selon les domaines de validité usuels.
        reco = hydrography_params.recommend_tc_formula(results.get("surface_km2"))
        results["tc_formule_recommandee"] = reco.get("recommended")
        results["tc_formules_hors_domaine"] = ", ".join(reco.get("out_of_domain", [])) or None
        if reco.get("recommended"):
            self.log_msg(
                f"  Formule de Tc recommandée pour ce bassin (surface = "
                f"{results.get('surface_km2', 0):.3f} km²) : {reco['recommended']}"
            )
            if reco.get("out_of_domain"):
                self.log_msg(
                    f"      Hors domaine de validité usuel pour cette surface : "
                    f"{', '.join(reco['out_of_domain'])}"
                )

        self.results_by_basin[basin_id] = results
        self.basin_records.append((basin_id, QgsGeometry(geom), dict(results)))

        self.log_msg(f"  -> Terminé pour '{basin_id}'.")

    def _populate_table(self):
        if not self.results_by_basin:
            return
        all_keys = []
        for res in self.results_by_basin.values():
            flat = report.flatten_results(res)
            for k in flat.keys():
                if k not in all_keys:
                    all_keys.append(k)

        self.table_results.setColumnCount(len(all_keys) + 1)
        self.table_results.setHorizontalHeaderLabels(["Bassin"] + all_keys)
        self.table_results.setRowCount(len(self.results_by_basin))

        for row, (basin_id, res) in enumerate(self.results_by_basin.items()):
            flat = report.flatten_results(res)
            self.table_results.setItem(row, 0, QTableWidgetItem(basin_id))
            for col, key in enumerate(all_keys, start=1):
                val = flat.get(key)
                val_str = f"{val:.4f}" if isinstance(val, float) else ("" if val is None else str(val))
                self.table_results.setItem(row, col, QTableWidgetItem(val_str))

    def export_csv(self):
        if not self.results_by_basin:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en CSV", "resultats_bv.csv", "CSV (*.csv)")
        if not path:
            return
        if os.path.exists(path):
            os.remove(path)
        for basin_id, res in self.results_by_basin.items():
            report.export_to_csv(basin_id, res, path)
        QMessageBox.information(self, "HydroSuiteBM Pro", f"Résultats exportés vers :\n{path}")

    def export_pdf_report(self):
        if not self.basin_records:
            QMessageBox.warning(self, "HydroSuiteBM Pro", "Lancez d'abord un calcul avant de générer le rapport.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Générer le rapport PDF", "rapport_hydrosuitebm_pro.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            pdf_report.generate_full_report_pdf(path, self.basin_records, self.last_run_info)
            QMessageBox.information(self, "HydroSuiteBM Pro", f"Rapport PDF généré :\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "HydroSuiteBM Pro", f"Échec de la génération du rapport PDF :\n{e}")
