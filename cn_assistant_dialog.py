# -*- coding: utf-8 -*-
"""
Assistant de construction d'un raster Curve Number (CN) à partir de
couches locales (occupation du sol + groupe hydrologique de sol),
fournies par l'utilisateur -- voir core/curve_number.py pour le
raisonnement derrière ce choix de conception.
"""
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QFileDialog, QMessageBox,
    QDialogButtonBox, QHeaderView
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapLayerComboBox
from qgis.core import QgsMapLayerProxyModel, QgsProject, QgsRasterLayer

from .core import curve_number


class CNAssistantDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assistant Curve Number (CN)")
        self.resize(720, 560)
        self.output_raster_path = None

        main_layout = QVBoxLayout(self)

        intro = QLabel(
            "Construisez un raster Curve Number à partir de VOS couches d'occupation du sol "
            "et de groupe hydrologique de sol (plutôt que d'un jeu de données mondial "
            "automatique, dont la fiabilité varie selon les régions). Associez chaque valeur "
            "brute de vos rasters à une catégorie standard NRCS ci-dessous, puis générez le CN."
        )
        intro.setWordWrap(True)
        main_layout.addWidget(intro)

        form = QFormLayout()
        self.cbo_land_use = QgsMapLayerComboBox()
        self.cbo_land_use.setFilters(QgsMapLayerProxyModel.RasterLayer)
        form.addRow("Raster d'occupation du sol :", self.cbo_land_use)

        self.cbo_soil = QgsMapLayerComboBox()
        self.cbo_soil.setFilters(QgsMapLayerProxyModel.RasterLayer)
        form.addRow("Raster de groupe hydrologique de sol :", self.cbo_soil)
        main_layout.addLayout(form)

        self.btn_detect = QPushButton("Détecter les classes présentes dans les deux rasters")
        self.btn_detect.clicked.connect(self.detect_classes)
        main_layout.addWidget(self.btn_detect)

        main_layout.addWidget(QLabel("Occupation du sol -- correspondance vers une catégorie NRCS :"))
        self.table_land_use = QTableWidget(0, 2)
        self.table_land_use.setHorizontalHeaderLabels(["Valeur brute", "Catégorie NRCS"])
        self.table_land_use.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        main_layout.addWidget(self.table_land_use)

        main_layout.addWidget(QLabel("Groupe de sol -- correspondance vers A / B / C / D :"))
        self.table_soil = QTableWidget(0, 2)
        self.table_soil.setHorizontalHeaderLabels(["Valeur brute", "Groupe hydrologique"])
        self.table_soil.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        main_layout.addWidget(self.table_soil)

        out_row = QHBoxLayout()
        self.btn_choose_output = QPushButton("Choisir le fichier de sortie (.tif)...")
        self.btn_choose_output.clicked.connect(self.choose_output)
        self.lbl_output = QLabel("(aucun fichier choisi)")
        out_row.addWidget(self.btn_choose_output)
        out_row.addWidget(self.lbl_output)
        main_layout.addLayout(out_row)

        self.btn_generate = QPushButton("Générer le raster CN")
        self.btn_generate.clicked.connect(self.generate)
        main_layout.addWidget(self.btn_generate)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self.accept)
        main_layout.addWidget(self.buttons)

        self.generated_layer = None  # rempli après une génération réussie

    # ------------------------------------------------------------------
    def detect_classes(self):
        land_use = self.cbo_land_use.currentLayer()
        soil = self.cbo_soil.currentLayer()
        if land_use is None or soil is None:
            QMessageBox.warning(self, "Assistant CN", "Sélectionnez les deux rasters d'abord.")
            return

        try:
            lu_values, lu_nodata, lu_truncated = curve_number.read_unique_values(land_use.source())
            soil_values, soil_nodata, soil_truncated = curve_number.read_unique_values(soil.source())
        except Exception as e:
            QMessageBox.critical(self, "Assistant CN", f"Échec de la lecture des rasters : {e}")
            return

        if lu_truncated or soil_truncated:
            QMessageBox.warning(
                self, "Assistant CN",
                "Plus de 200 valeurs distinctes détectées sur au moins un raster : "
                "vérifiez qu'il s'agit bien d'une carte catégorielle (occupation du sol / "
                "groupe de sol) et non d'un raster continu (ex. un MNT)."
            )

        self._populate_table(self.table_land_use, lu_values, curve_number.CATEGORY_LABELS)
        self._populate_table(self.table_soil, soil_values, curve_number.SOIL_GROUP_DESCRIPTIONS)

    def _populate_table(self, table, values, options_dict):
        table.setRowCount(0)
        for value in values:
            row = table.rowCount()
            table.insertRow(row)
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, item)

            combo = QComboBox()
            combo.addItem("-- non mappé --", None)
            for key, label in options_dict.items():
                combo.addItem(label, key)
            table.setCellWidget(row, 1, combo)

    def _read_mapping(self, table):
        mapping = {}
        for row in range(table.rowCount()):
            raw_value_text = table.item(row, 0).text()
            try:
                raw_value = float(raw_value_text)
                if raw_value.is_integer():
                    raw_value = int(raw_value)
            except ValueError:
                raw_value = raw_value_text
            combo = table.cellWidget(row, 1)
            key = combo.currentData()
            if key is not None:
                mapping[raw_value] = key
        return mapping

    # ------------------------------------------------------------------
    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Fichier de sortie", "curve_number.tif", "GeoTIFF (*.tif)")
        if path:
            self.output_raster_path = path
            self.lbl_output.setText(path)

    def generate(self):
        land_use = self.cbo_land_use.currentLayer()
        soil = self.cbo_soil.currentLayer()
        if land_use is None or soil is None:
            QMessageBox.warning(self, "Assistant CN", "Sélectionnez les deux rasters.")
            return
        if not self.output_raster_path:
            QMessageBox.warning(self, "Assistant CN", "Choisissez un fichier de sortie.")
            return
        if self.table_land_use.rowCount() == 0 or self.table_soil.rowCount() == 0:
            QMessageBox.warning(self, "Assistant CN", "Cliquez d'abord sur « Détecter les classes ».")
            return

        land_use_mapping = self._read_mapping(self.table_land_use)
        soil_mapping = self._read_mapping(self.table_soil)

        if not land_use_mapping:
            QMessageBox.warning(
                self, "Assistant CN",
                "Aucune classe d'occupation du sol n'est mappée à une catégorie NRCS."
            )
            return
        if not soil_mapping:
            QMessageBox.warning(
                self, "Assistant CN",
                "Aucune classe de sol n'est mappée à un groupe hydrologique (A/B/C/D)."
            )
            return

        try:
            result = curve_number.build_cn_raster(
                land_use.source(), soil.source(),
                land_use_mapping, soil_mapping,
                self.output_raster_path,
            )
        except Exception as e:
            QMessageBox.critical(self, "Assistant CN", f"Échec de la génération : {e}")
            return

        msg = f"Raster CN généré : {result['n_valid']} pixels calculés."
        warnings = []
        if result["n_unmapped_land_use"]:
            warnings.append(
                f"{result['n_unmapped_land_use']} pixels avec un code d'occupation du sol non "
                f"mappé (valeurs : {result['unmapped_land_use_codes']})"
            )
        if result["n_unmapped_soil"]:
            warnings.append(
                f"{result['n_unmapped_soil']} pixels avec un code de groupe de sol non mappé "
                f"(valeurs : {result['unmapped_soil_codes']})"
            )
        if warnings:
            msg += (
                "\n\nAttention -- laissés en nodata (non forcés à une valeur arbitraire) : \n- "
                + "\n- ".join(warnings)
                + "\n\nComplétez la correspondance ci-dessus si ces zones doivent être couvertes, "
                "puis relancez la génération."
            )

        self.generated_layer = QgsRasterLayer(self.output_raster_path, "curve_number")
        if self.generated_layer.isValid():
            QgsProject.instance().addMapLayer(self.generated_layer)

        QMessageBox.information(self, "Assistant CN", msg)
