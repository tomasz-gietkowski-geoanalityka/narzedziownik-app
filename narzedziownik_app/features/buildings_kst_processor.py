"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
# Tworzy warstwę tymczasową "budynki_ouz" na podstawie aktywnej warstwy,
# dodaje pole 'rodzajWgKST_2015' wyliczone z wybranego pola,
# nakłada styl z resources/qml/styl-budynki_ouz.qml
# Jedno okno: informacja o wybranej warstwie + wybór pola (bez dodatkowego potwierdzenia)

import os
from qgis.core import (
    QgsField, QgsVectorLayer, QgsFields, QgsFeature,
    QgsWkbTypes, QgsProject, QgsLayerTreeLayer,
)
from PyQt5.QtCore import QVariant, Qt
from PyQt5.QtWidgets import (
    QProgressDialog, QMessageBox, QDialog, QVBoxLayout,
    QLabel, QComboBox, QDialogButtonBox, QSizePolicy, QLayout
)

# --- Jedno okno: informacja + wybór pola ---
class FieldSelectionDialog(QDialog):
    def __init__(self, parent, layer_name, items, default_index=0, has_rodz_fields=True):
        super().__init__(parent)
        self.setWindowTitle("Narzędziownik APP")
        self.setModal(True)

        layout = QVBoxLayout(self)

        lbl = QLabel()
        lbl.setTextFormat(Qt.RichText)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if has_rodz_fields:
            info_html = (
                f"<div><b>Do analizy budynków wskazałeś warstwę:</b> "
                f"<span style='color:#0066cc'>{layer_name}</span></div><br>"
                "<b>Wybierz pole</b> zawierające symbol lub kod rodzaju budynku.<br>"
                "Wyświetlono tylko pola zawierające ciąg "
                "<span style='background:#ffee99;padding:2px 4px;border-radius:4px'>„rodz”</span>."
            )
        else:
            info_html = (
                f"<div><b>Do analizy budynków wskazałeś warstwę:</b> "
                f"<span style='color:#0066cc'>{layer_name}</span></div><br>"
                "<b>Wybierz pole</b> zawierające symbol lub kod rodzaju budynku.<br>"
                "Nie znaleziono pól zawierających ciąg "
                "<span style='background:#ffee99;padding:2px 4px;border-radius:4px'>„rodz”</span> — "
                "pokazano wszystkie pola."
            )

        lbl.setText(info_html)
        layout.addWidget(lbl)

        self.combo = QComboBox()
        self.combo.addItems(items)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo.setMinimumContentsLength(28)
        if 0 <= default_index < len(items):
            self.combo.setCurrentIndex(default_index)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Dopasowanie szerokości
        self.setMinimumWidth(560)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.resize(max(560, self.sizeHint().width()), self.sizeHint().height())

    @property
    def selected_text(self):
        return self.combo.currentText()


def run(iface, plugin_dir):
    main = iface.mainWindow()

    # 1) Aktywna warstwa
    src_layer = iface.activeLayer()
    if not isinstance(src_layer, QgsVectorLayer):
        QMessageBox.warning(
            main, "Narzędziownik APP",
            "Nie wybrano żadnej warstwy wektorowej.\nZaznacz w panelu warstw warstwę budynków i spróbuj ponownie."
        )
        return

    # 2) Lista pól
    all_fields = [f.name() for f in src_layer.fields()]
    if not all_fields:
        QMessageBox.warning(main, "Narzędziownik APP", "Warstwa nie posiada żadnych pól.")
        return

    rodz_fields = [n for n in all_fields if "rodz" in n.lower()]
    field_list = rodz_fields if rodz_fields else all_fields

    # domyślny wybór
    default_index = 0
    for i, nm in enumerate(field_list):
        if nm.upper() == "RODZAJ":
            default_index = i
            break

    # 3) Połączone okno: informacja + wybór pola
    dlg = FieldSelectionDialog(main, src_layer.name(), field_list, default_index, has_rodz_fields=bool(rodz_fields))
    if dlg.exec_() != QDialog.Accepted:
        return

    selected_field = dlg.selected_text
    if not selected_field:
        return
    idx_src = src_layer.fields().indexOf(selected_field)
    if idx_src < 0:
        QMessageBox.warning(main, "Narzędziownik APP", f"Nie znaleziono pola „{selected_field}”.")
        return

    # 4) Warstwa tymczasowa
    geom_str = QgsWkbTypes.displayString(src_layer.wkbType())
    crs_authid = src_layer.crs().authid()
    mem_uri = f"{geom_str}?crs={crs_authid}"
    mem_layer = QgsVectorLayer(mem_uri, "budynki_ouz", "memory")
    if not mem_layer.isValid():
        QMessageBox.warning(main, "Narzędziownik APP", "Nie udało się utworzyć warstwy tymczasowej.")
        return

    # 5) Pola
    mem_fields = QgsFields()
    for f in src_layer.fields():
        mem_fields.append(f)
    target_field_name = "rodzajWgKST_2015"
    mem_fields.append(QgsField(target_field_name, QVariant.String))
    mem_pr = mem_layer.dataProvider()
    mem_pr.addAttributes(list(mem_fields))
    mem_layer.updateFields()
    idx_target = mem_layer.fields().indexOf(target_field_name)

    # 6) Mapowanie wartości
    value_map = {
        'p': '101', 't': '102', 'h': '103', 's': '104',
        'b': '105', 'z': '106', 'k': '107', 'g': '108',
        'i': '109', 'm': '110',
        '101': '101', '102': '102', '103': '103', '104': '104',
        '105': '105', '106': '106', '107': '107', '108': '108',
        '109': '109', '110': '110'
    }

    total = src_layer.featureCount()
    progress_dialog = QProgressDialog("Tworzenie warstwy 'budynki_ouz'...", "Anuluj", 0, total, main)
    progress_dialog.setWindowTitle("Proszę czekać")
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.show()

    # 7) Przetwarzanie
    missing_src_cnt = 0
    new_features = []
    for i, feat in enumerate(src_layer.getFeatures()):
        if progress_dialog.wasCanceled():
            break
        new_feat = QgsFeature(mem_layer.fields())
        new_feat.setGeometry(feat.geometry())
        attrs = feat.attributes()[:]
        raw_val = feat.attributes()[idx_src]
        if raw_val is None or str(raw_val).strip() == "":
            missing_src_cnt += 1
        norm_val = (str(raw_val).strip().lower() if raw_val is not None else "")
        mapped_value = value_map.get(norm_val, None)
        if len(attrs) < mem_layer.fields().count():
            attrs.extend([None] * (mem_layer.fields().count() - len(attrs)))
        attrs[idx_target] = mapped_value
        new_feat.setAttributes(attrs)
        new_features.append(new_feat)
        progress_dialog.setValue(i + 1)

    if new_features:
        mem_pr.addFeatures(new_features)
        mem_layer.updateExtents()
    progress_dialog.close()

    # 8) Styl
    style_path = os.path.normpath(os.path.join(plugin_dir, "resources", "qml", "styl-budynki_ouz.qml"))
    if os.path.isfile(style_path):
        mem_layer.loadNamedStyle(style_path)
        mem_layer.triggerRepaint()
    else:
        QMessageBox.warning(main, "Narzędziownik APP", f"Nie znaleziono pliku stylu:\n{style_path}")

    # 9) Dodanie do grupy OUZ
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup("OUZ") or root.addGroup("OUZ")
    project.addMapLayer(mem_layer, False)
    group.insertChildNode(0, QgsLayerTreeLayer(mem_layer))

    # 10) Finał — sformatowany komunikat wynikowy
    msg = QMessageBox(main)
    msg.setWindowTitle("Zakończono")
    msg.setIcon(QMessageBox.Information)
    msg.setTextFormat(Qt.RichText)
    msg.setText(
        "Utworzono warstwę tymczasową <b>„budynki_ouz”</b> w grupie <b>„OUZ”</b>."
        "<br><br>"
        "Obiekty bez wartości w polu "
        f"<b>{selected_field}</b>: "
        f"<span style='color:red;font-weight:bold'>{missing_src_cnt}</span>"
    )
    msg.exec_()
