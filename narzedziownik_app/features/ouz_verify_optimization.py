"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)
"""

# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox, QMessageBox,
    QSizePolicy, QTextBrowser, QWidget, QDoubleSpinBox, QHBoxLayout,
    QApplication, QProgressDialog
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsMapLayer, QgsFeatureRequest, QgsGeometry, QgsFeature,
    QgsVectorLayer, QgsCoordinateTransform, QgsSpatialIndex,
    QgsCoordinateReferenceSystem
)

from typing import Optional, List, Tuple, Callable
import html
from datetime import datetime
import re


# ========== Prosty, wieloetapowy pasek postępu ==========

class MultiStageProgress:
    def __init__(self, parent: QWidget, title: str = "Postęp", cancellable: bool = True):
        self.dlg = QProgressDialog(parent)
        self.dlg.setWindowTitle(title)
        self.dlg.setModal(True)
        self.dlg.setAutoClose(True)   # auto-zamknięcie po osiągnięciu maksimum
        self.dlg.setAutoReset(True)   # reset po zamknięciu
        self.dlg.setMinimumDuration(0)
        if cancellable:
            self.dlg.setCancelButtonText("Przerwij")
        else:
            self.dlg.setCancelButton(None)
        self._max = 0
        self._val = 0

    def start(self, label: str, maximum: int):
        if maximum < 0:
            maximum = 0
        self._max = maximum
        self._val = 0
        self.dlg.setLabelText(label)
        # Uwaga: gdy maximum == 0, QProgressDialog przechodzi w tryb "busy"
        self.dlg.setRange(0, maximum if maximum > 0 else 0)
        self.dlg.setValue(0)
        QApplication.processEvents()
        if self.dlg.wasCanceled():
            raise RuntimeError("cancelled")

    def step(self, value: int):
        if self.dlg.wasCanceled():
            raise RuntimeError("cancelled")
        self._val = min(max(0, value), self._max)
        self.dlg.setValue(self._val)
        QApplication.processEvents()
        if self.dlg.wasCanceled():
            raise RuntimeError("cancelled")

    def bump(self, inc: int = 1):
        self.step(self._val + inc)

    def pulse(self):
        QApplication.processEvents()
        if self.dlg.wasCanceled():
            raise RuntimeError("cancelled")

    def set_label(self, text: str):
        self.dlg.setLabelText(text)
        QApplication.processEvents()

    def finish(self):
        # Idempotentne domknięcie – można wywołać wielokrotnie
        try:
            self.dlg.setValue(self._max)
        finally:
            try:
                self.dlg.reset()   # przy AutoClose zamyka okno
                self.dlg.close()   # upewnij się, że okno zniknie
            except Exception:
                pass
            QApplication.processEvents()


# ========== Dialog wyboru wejść ==========

class OUZVerifyDialog(QDialog):
    def __init__(self, parent, current_layer_name: str, ouz_layers: List[str], akt_layers: List[str]):
        super().__init__(parent)
        self.setWindowTitle("Weryfikacja OUZ – wybór danych")

        # okno rozszerzalne + sensowny start
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, False)
        self.setSizeGripEnabled(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # Info o warstwie kontrolowanej – z kolorem
        color = "#7137c8"
        info_html = (
            f"<b>Warstwa kontrolowana (optymalizowana) to:</b><br>"
            f"<span style='color:{color};'>{current_layer_name if current_layer_name else '<i>(brak aktywnej warstwy)</i>'}</span>"
        )
        info = QLabel(info_html)
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        # Wybierak OUZ pierwotny
        layout.addSpacing(8)
        layout.addWidget(QLabel("Wybierz OUZ pierwotny (warstwy z ciągiem „uzu” w nazwie):"))
        self.comboOuz = QComboBox(self)
        self.comboOuz.setEditable(False)
        self.comboOuz.addItems(ouz_layers)
        layout.addWidget(self.comboOuz)

        # Wybierak granicy aktu
        layout.addSpacing(8)
        layout.addWidget(QLabel("Wybierz granicę aktu (warstwy z ciągiem „akt” w nazwie):"))
        self.comboAkt = QComboBox(self)
        self.comboAkt.setEditable(False)
        self.comboAkt.addItems(akt_layers)
        layout.addWidget(self.comboAkt)

        # Pole MPP (ha)
        layout.addSpacing(8)
        hl = QHBoxLayout()
        lbl_mpp = QLabel("Maksymalna powierzchnia powiększenia (MPP) [ha]:")
        self.spinMPP = QDoubleSpinBox(self)
        self.spinMPP.setDecimals(4)
        self.spinMPP.setRange(0.0, 1_000_000.0)  # do 1 mln ha
        self.spinMPP.setSingleStep(0.1)
        self.spinMPP.setValue(0.0)
        self.spinMPP.setSuffix(" ha")
        self.spinMPP.setMinimumWidth(180)
        hl.addWidget(lbl_mpp)
        hl.addWidget(self.spinMPP, 1)
        layout.addLayout(hl)

        # Przyciski OK / Anuluj
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # wymuś startową szerokość po zbudowaniu widżetów
        self.layout().activate()
        self.resize(max(700, self.sizeHint().width()), self.sizeHint().height())

    def selected_ouz_name(self) -> Optional[str]:
        return self.comboOuz.currentText() if self.comboOuz.count() else None

    def selected_akt_name(self) -> Optional[str]:
        return self.comboAkt.currentText() if self.comboAkt.count() else None

    def mpp_value_ha(self) -> float:
        return float(self.spinMPP.value())


# ========== Dialog raportu (zamiast QMessageBox) ==========

class ReportDialog(QDialog):
    """Własne okno raportu: duże, rozszerzalne, z HTML w QTextBrowser."""
    def __init__(self, parent: QWidget, html_content: str, title: str = "Weryfikacja OUZ – podsumowanie"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, False)
               # allow resize
        self.setSizeGripEnabled(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumSize(1000, 500)

        layout = QVBoxLayout(self)

        view = QTextBrowser(self)
        view.setOpenExternalLinks(True)
        view.setReadOnly(True)
        view.setHtml(html_content)
        view.setLineWrapMode(QTextBrowser.WidgetWidth)
        layout.addWidget(view)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, self)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.layout().activate()
        self.resize(max(1000, self.sizeHint().width()), max(700, self.sizeHint().height()))


# ===== Pomocnicze =====

def _find_layers_with_substring(substr: str) -> List[str]:
    s = substr.lower()
    layers = []
    for lyr in QgsProject.instance().mapLayers().values():
        name = lyr.name() if isinstance(lyr, QgsMapLayer) else ""
        if s in name.lower():
            layers.append(name)
    layers.sort(key=lambda x: x.lower())
    return layers


def _get_layer_by_name(name: str) -> Optional[QgsMapLayer]:
    for lyr in QgsProject.instance().mapLayers().values():
        if isinstance(lyr, QgsMapLayer) and lyr.name() == name:
            return lyr
    return None


def _exists_by_expression(layer, expr: str) -> bool:
    req = QgsFeatureRequest().setFilterExpression(expr).setLimit(1)
    return any(True for _ in layer.getFeatures(req))


def _unary_union(layer: QgsMapLayer, progress_cb: Optional[Callable[[int, int], None]] = None) -> Optional[QgsGeometry]:
    """Zbiera geometrie z warstwy i wykonuje unaryUnion. Jeśli podano progress_cb(i, n), aktualizuje postęp."""
    geoms = []
    n = 0
    for _ in layer.getFeatures():
        n += 1
    i = 0
    for f in layer.getFeatures():
        g = f.geometry()
        if g and not g.isEmpty():
            geoms.append(g)
        i += 1
        if progress_cb:
            progress_cb(i, n)
    if not geoms:
        return None
    try:
        return QgsGeometry.unaryUnion(geoms)
    except Exception:
        # fallback: łącz kolejno
        u = geoms[0]
        for k, g in enumerate(geoms[1:], start=1):
            u = u.combine(g)
            if progress_cb:
                progress_cb(min(n, i + k), n)
        return u


def _transform(geom: QgsGeometry, src, dst) -> QgsGeometry:
    if src == dst:
        return geom
    ct = QgsCoordinateTransform(src, dst, QgsProject.instance())
    g = QgsGeometry(geom)
    g.transform(ct)
    return g


def _ensure_group(name: str):
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(name)
    if group is None:
        group = root.addGroup(name)
    return group


def _replace_layer_by_name(name: str):
    proj = QgsProject.instance()
    for lyr_id, lyr in list(proj.mapLayers().items()):
        if lyr.name() == name:
            proj.removeMapLayer(lyr_id)


def _area_ha(geom: QgsGeometry, src_crs) -> float:
    """
    Pole w hektarach (ha).
    - jeśli CRS geograficzny (stopnie) → transformacja do EPSG:3035 (LAEA Europe) i planar area()
    - w przeciwnym razie → planar area() w jednostkach CRS (zakładamy metry; typowo 2180/3857 itp.)
    """
    if not geom or geom.isEmpty():
        return 0.0

    g = QgsGeometry(geom)
    try:
        if src_crs.isGeographic():
            laea = QgsCoordinateReferenceSystem("EPSG:3035")  # equal-area dla Europy
            ct = QgsCoordinateTransform(src_crs, laea, QgsProject.instance())
            g.transform(ct)
        a_m2 = abs(g.area())
        return a_m2 / 10000.0  # m² -> ha
    except Exception:
        return 0.0


# ===== Raport wyników (3 kolumny) =====

def _show_final_report_table(rows: List[Tuple[str, str, Optional[str]]],
                             parent,
                             title: str,
                             header_layer_current: str,
                             header_layer_ouz: str):
    """
    Okno z tabelą wyników: 3 kolumny (Kontrola, Status, Warstwa z błędami)
    + nagłówek w jednym wierszu.
    """
    ts = datetime.now().strftime("%Y:%m:%d  %H:%M:%S")

    hdr_html = (
        "<div style='margin-bottom:10px; line-height:1.2; white-space:nowrap;'>"
         f"<h2><b>RAPORT KONTROLI OPTYMALIZACJI OUZ</b></h2>"
        "</div>"
        "<div style='margin-bottom:10px; line-height:1.2; white-space:nowrap; color:#ff0000; background-color: yellow'>"
         f"<b>UWAGA!</b><br>"
         f"Kontola optymalizacji OUZ zakłada na wejściu poprawność techniczną warstw (geometria obiektów, topologia).<br>"
         f"Jeśli przed tą kontrolą nie wykonano analizy natywnym narzędziem <b>SPRAWDZANIE TOPOLOGII</b><br>"
         f"i nie usunięto wskazanych tam błędów, poniższe wyniki <b><u>mogą być niepoprawne!</b></u>"
         "</div>"
        "</div>"
         "<div style='margin-bottom:10px; line-height:1.2; white-space:nowrap;'>"
         f"<b>Data wykonania:</b> {ts}<br>"
         f"<b>Warstwa kontrolowana</b> <span style='color:#7137c8;'>{html.escape(header_layer_current)}</span><br>"
         f"<b>Warstwa OUZ pierwotny:</b> <span style='color:#7137c8;'>{html.escape(header_layer_ouz)}</span><br>"
        "</div>"
    )

    html_out = f"""
    <div style="font-size:12px; min-width:1000px;">
      {hdr_html}
      <table cellspacing="0" cellpadding="8" style="border-collapse:collapse; width:100%;">
        <tr>
          <th align="left" style="border-bottom:1px solid #ccc; white-space:nowrap; padding-right:20px; width:35%;">Kontrola</th>
          <th align="left" style="border-bottom:1px solid #ccc; width:45%;">Status</th>
          <th align="left" style="border-bottom:1px solid #ccc; width:20%;">Warstwa z błędami</th>
        </tr>
    """
    for label, status, err_layer in rows:
        safe_label = html.escape(str(label))
        layer_text = f"<span style='color:#7137c8;'>{html.escape(err_layer)}</span>" if err_layer else "—"
        html_out += f"""
        <tr>
          <td style="vertical-align:top; white-space:nowrap; padding-right:24px;">{safe_label}</td>
          <td style="vertical-align:top; white-space:normal; word-break:break-word; line-height:1.2;">{status}</td>
          <td style="vertical-align:top; white-space:nowrap;">{layer_text}</td>
        </tr>
        """
    html_out += "</table></div>"

    ReportDialog(parent, html_out, title).exec_()


# ===== Okienko informacyjne PRZED analizą (zwykły alert) =====

def _show_precheck_warning(parent: QWidget):
    text = (
        "UWAGA!\n\n"
        "Kontrola optymalizacji OUZ zakłada na wejściu poprawność techniczną warstw "
        "(geometria obiektów, topologia).\n"
        "Jeśli przed tą kontrolą nie wykonano analizy natywnym narzędziem "
        "SPRAWDZANIE GEOMETRII i nie usunięto wskazanych tam błędów, "
        "poniższe wyniki mogą być niepoprawne!"
    )
    QMessageBox.warning(parent, "Ważna informacja", text)


# ===== Główna funkcja =====

def run(iface, plugin_dir):
    # aktywna warstwa wymagana na starcie (popup)
    active = iface.activeLayer()
    if not active:
        QMessageBox.information(
            iface.mainWindow(),
            "Weryfikacja OUZ",
            "Zaznacz kontrolowaną warstwę i zacznij jeszcze raz"
        )
        return
    current_name = active.name()

    # wybór warstw referencyjnych
    ouz_candidates = _find_layers_with_substring("uzu")
    akt_candidates = _find_layers_with_substring("akt")

    if not ouz_candidates:
        iface.messageBar().pushWarning("Weryfikacja OUZ", "Nie znaleziono warstw zawierających w nazwie ciąg „uzu”.")
        return
    if not akt_candidates:
        iface.messageBar().pushWarning("Weryfikacja OUZ", "Nie znaleziono warstw zawierających w nazwie ciąg „akt”.")
        return

    dlg = OUZVerifyDialog(iface.mainWindow(), current_name, ouz_candidates, akt_candidates)
    if dlg.exec_() != QDialog.Accepted:
        return

    selected_ouz_name = dlg.selected_ouz_name()
    selected_akt_name = dlg.selected_akt_name()
    mpp_ha = dlg.mpp_value_ha()
    if not selected_ouz_name or not selected_akt_name:
        iface.messageBar().pushWarning("Weryfikacja OUZ", "Nie wybrano wymaganych warstw.")
        return

    ouz_layer = _get_layer_by_name(selected_ouz_name)          # OUZ pierwotny (wzorcowa)
    akt_layer = _get_layer_by_name(selected_akt_name)          # granica aktu
    if not ouz_layer or not akt_layer:
        iface.messageBar().pushWarning("Weryfikacja OUZ", "Nie udało się odnaleźć wskazanych warstw.")
        return

    # >>> zwykły popup przed analizą <<<
    _show_precheck_warning(iface.mainWindow())

    rows: List[Tuple[str, str, Optional[str]]] = []
    mp = MultiStageProgress(iface.mainWindow(), "Weryfikacja OUZ – postęp")

    try:
        # 1) Obiekty bez geometrii
        mp.start("Krok 1/7 – sprawdzanie brakujących geometrii…", maximum=0)
        if _exists_by_expression(active, "$geometry IS NULL"):
            rows.append(("Obiekty bez geometrii", "<span style='color:#c0392b;'>❗ W tabeli atrybutów wykryto obiekty bez geometrii</span>", current_name))
        else:
            rows.append(("Obiekty bez geometrii", "<span style='color:#2e8b57;'>✅ Wszystkie obiekty mają geometrię</span>", None))
        mp.pulse()

        # 2) Obiekty o powierzchni ≤ 0
        mp.start("Krok 2/7 – sprawdzanie powierzchni ≤ 0…", maximum=0)
        if _exists_by_expression(active, "$area <= 0"):
            rows.append(("Powierzchnia obiektów ≤ 0", "<span style='color:#c0392b;'>❗ Występują obiekty o powierzchni ≤ 0</span>", current_name))
        else:
            rows.append(("Powierzchnia obiektów ≤ 0", "<span style='color:#2e8b57;'>✅ Brak obiektów o powierzchni ≤ 0</span>", None))
        mp.pulse()

        # 3) Położenie względem granic aktu
        # 3a. Unia granicy aktu (z postępem) – start RAZ przed pętlą unii
        n_akt = sum(1 for _ in akt_layer.getFeatures())
        mp.start("Krok 3/7 – przygotowanie granicy aktu (unary union)…", maximum=max(1, n_akt))
        akt_union = _unary_union(akt_layer, progress_cb=lambda i, n: mp.step(i))
        if not akt_union or akt_union.isEmpty():
            QMessageBox.critical(
                iface.mainWindow(),
                "Weryfikacja OUZ",
                "Nie udało się zbudować geometrii granicy aktu (warstwa pusta?)."
            )
            mp.finish()
            return

        mp.start("Krok 3/7 – transformacja granicy aktu do CRS warstwy kontrolowanej…", maximum=0)
        akt_union_trans = _transform(akt_union, akt_layer.crs(), active.crs())
        mp.pulse()

        # 3b. Sprawdzenie różnic względem aktu
        n_feats = sum(1 for _ in active.getFeatures())
        mp.start("Krok 3/7 – sprawdzanie położenia względem granic aktu…", maximum=max(1, n_feats))
        outside_geoms: List[QgsGeometry] = []
        i = 0
        for f in active.getFeatures():
            g = f.geometry()
            if g and not g.isEmpty():
                diff = g.difference(akt_union_trans)
                if diff and not diff.isEmpty():
                    outside_geoms.append(diff)
            i += 1
            mp.step(i)

        if outside_geoms:
            tmp_name = "ouzopt_poza_app"
            _replace_layer_by_name(tmp_name)

            crs_auth = active.crs().authid() or active.crs().toWkt()
            uri = f"Polygon?crs={crs_auth}"
            tmp = QgsVectorLayer(uri, tmp_name, "memory")
            pr = tmp.dataProvider()
            tmp.updateFields()

            mp.start("Krok 3/7 – budowanie warstwy części poza granicą aktu…", maximum=len(outside_geoms))
            feats = []
            for k, geom in enumerate(outside_geoms, start=1):
                feat = QgsFeature()
                feat.setGeometry(geom)
                feats.append(feat)
                if (k % 50) == 0 or k == len(outside_geoms):
                    pr.addFeatures(feats)
                    feats = []
                mp.step(k)
            tmp.updateExtents()

            proj = QgsProject.instance()
            group = _ensure_group("OUZ KONTROLA")
            proj.addMapLayer(tmp, False)
            group.addLayer(tmp)

            rows.append(("Położenie w granicach aktu", "<span style='color:#c0392b;'>❗ Przynajmniej część OUZ znajduje się poza granicą aktu</span>", tmp_name))
        else:
            rows.append(("Położenie w granicach aktu", "<span style='color:#2e8b57;'>✅ Obszary OUZ znajdują się w granicach aktu</span>", None))

        # 4) Kontakt z OUZ pierwotnym
        n_ouz = sum(1 for _ in ouz_layer.getFeatures())
        mp.start("Krok 4/7 – przygotowanie OUZ pierwotnego (unary union)…", maximum=max(1, n_ouz))
        ouz_union = _unary_union(ouz_layer, progress_cb=lambda i, n: mp.step(i))
        if not ouz_union or ouz_union.isEmpty():
            QMessageBox.critical(
                iface.mainWindow(),
                "Weryfikacja OUZ",
                "Nie udało się zbudować geometrii warstwy OUZ pierwotny (warstwa pusta?)."
            )
            mp.finish()
            return

        mp.start("Krok 4/7 – transformacja OUZ pierwotnego do CRS warstwy kontrolowanej…", maximum=0)
        ouz_union_trans = _transform(ouz_union, ouz_layer.crs(), active.crs())
        mp.pulse()

        tol = 1e-7 if active.crs().isGeographic() else 0.001  # ~0.001 m
        n_feats = sum(1 for _ in active.getFeatures())
        mp.start("Krok 4/7 – sprawdzanie kontaktu z OUZ pierwotnym…", maximum=max(1, n_feats))
        no_contact_geoms: List[QgsGeometry] = []
        i = 0
        for f in active.getFeatures():
            g = f.geometry()
            if g and not g.isEmpty():
                inter = g.intersection(ouz_union_trans)
                contact = False
                if inter and not inter.isEmpty() and inter.area() > 0:
                    contact = True
                else:
                    try:
                        if g.touches(ouz_union_trans):
                            contact = True
                    except Exception:
                        pass
                    if not contact and inter and not inter.isEmpty():
                        try:
                            if inter.length() > 0:
                                contact = True
                        except Exception:
                            pass
                    if not contact:
                        try:
                            if g.distance(ouz_union_trans) <= tol:
                                contact = True
                        except Exception:
                            pass
                if not contact:
                    no_contact_geoms.append(g)
            i += 1
            mp.step(i)

        if no_contact_geoms:
            tmp_name = "ouzopt_bez_kontaktu_z_pierwotnym_ouz"
            _replace_layer_by_name(tmp_name)

            crs_auth = active.crs().authid() or active.crs().toWkt()
            uri = f"Polygon?crs={crs_auth}"
            tmp = QgsVectorLayer(uri, tmp_name, "memory")
            pr = tmp.dataProvider()
            tmp.updateFields()

            mp.start("Krok 4/7 – budowanie warstwy braku kontaktu…", maximum=len(no_contact_geoms))
            feats = []
            for k, geom in enumerate(no_contact_geoms, start=1):
                feat = QgsFeature()
                feat.setGeometry(geom)
                feats.append(feat)
                if (k % 50) == 0 or k == len(no_contact_geoms):
                    pr.addFeatures(feats)
                    feats = []
                mp.step(k)
            tmp.updateExtents()

            proj = QgsProject.instance()
            group = _ensure_group("OUZ KONTROLA")
            proj.addMapLayer(tmp, False)
            group.addLayer(tmp)

            rows.append(("Kontakt z OUZ pierwotnym",
                         "<span style='color:#c0392b;'>❗ Występują obiekty, dla których brak części wspólnej ani styku krawędziowego z OUZ pierwotnym</span>",
                         tmp_name))
        else:
            rows.append(("Kontakt z OUZ pierwotnym",
                         "<span style='color:#2e8b57;'>✅ Wszystkie obiekty mają część wspólną lub styk krawędziowy z OUZ pierwotnym</span>",
                         None))

        # 5) Styk między obiektami OUZ (wewnątrz warstwy)
        mp.start("Krok 5/7 – budowa indeksu przestrzennego…", maximum=0)
        idx = QgsSpatialIndex()
        feats_cache = {}
        n_feats = sum(1 for _ in active.getFeatures())
        mp.start("Krok 5/7 – wczytywanie obiektów do indeksu…", maximum=max(1, n_feats))
        i = 0
        for f in active.getFeatures():
            feats_cache[f.id()] = f
            idx.addFeature(f)
            i += 1
            mp.step(i)

        touching_ids = set()
        mp.start("Krok 5/7 – analiza styku między obiektami…", maximum=max(1, len(feats_cache)))
        for j, (fid, f) in enumerate(feats_cache.items(), start=1):
            g = f.geometry()
            if g and not g.isEmpty():
                for nid in idx.intersects(g.boundingBox()):
                    if nid == fid:
                        continue
                    nf = feats_cache.get(nid)
                    if not nf:
                        continue
                    ng = nf.geometry()
                    if not ng or ng.isEmpty():
                        continue
                    try:
                        if g.touches(ng):
                            touching_ids.add(fid)
                            touching_ids.add(nid)
                    except Exception:
                        inter = g.intersection(ng)
                        try:
                            if inter and not inter.isEmpty() and inter.length() > 0 and inter.area() == 0:
                                touching_ids.add(fid)
                                touching_ids.add(nid)
                        except Exception:
                            pass
            mp.step(j)

        if touching_ids:
            tmp_name = "obiekty_ouzopt_ze_wspolna_granica"
            _replace_layer_by_name(tmp_name)

            crs_auth = active.crs().authid() or active.crs().toWkt()
            uri = f"Polygon?crs={crs_auth}"
            tmp = QgsVectorLayer(uri, tmp_name, "memory")
            pr = tmp.dataProvider()
            tmp.updateFields()

            mp.start("Krok 5/7 – budowanie warstwy styku…", maximum=len(touching_ids))
            out_feats = []
            for k, tid in enumerate(touching_ids, start=1):
                feat = QgsFeature()
                feat.setGeometry(feats_cache[tid].geometry())
                out_feats.append(feat)
                if (k % 100) == 0 or k == len(touching_ids):
                    pr.addFeatures(out_feats)
                    out_feats = []
                mp.step(k)
            tmp.updateExtents()

            proj = QgsProject.instance()
            group = _ensure_group("OUZ KONTROLA")
            proj.addMapLayer(tmp, False)
            group.addLayer(tmp)

            rows.append(("Styk między obiektami OUZ (wewnątrz warstwy)",
                         "<span style='color:#c0392b;'>❗ Wykryto obiekty stykające się wspólną granicą</span>",
                         tmp_name))
        else:
            rows.append(("Styk między obiektami OUZ (wewnątrz warstwy)",
                         "<span style='color:#2e8b57;'>✅ Brak obiektów stykających się wspólną granicą</span>",
                         None))

        # 6) Ciągłość oznaczeń (pole 'oznaczenie')
        mp.start("Krok 6/7 – analiza pola „oznaczenie”…", maximum=0)
        nums = set()
        has_field = active.fields().indexFromName('oznaczenie') != -1
        if has_field:
            n_feats = sum(1 for _ in active.getFeatures())
            mp.start("Krok 6/7 – zbieranie numerów z pola „oznaczenie”…", maximum=max(1, n_feats))
            i = 0
            for f in active.getFeatures():
                val = f['oznaczenie']
                if val is not None:
                    for m in re.findall(r'\d+', str(val)):
                        try:
                            nums.add(int(m))
                        except Exception:
                            pass
                i += 1
                mp.step(i)

            if nums:
                seq = sorted(nums)
                missing = [str(n) for n in range(seq[0], seq[-1] + 1) if n not in nums]
                if missing:
                    rows.append((
                        "Ciągłość oznaczeń (pole „oznaczenie”)",
                        "<span style='color:#c0392b;'>❗ Wykryto następujące brakujące wartości w liczbach porządkowych pola „oznaczenie”: "
                        + ", ".join(missing) + "</span>",
                        current_name
                    ))
                else:
                    rows.append((
                        "Ciągłość oznaczeń (pole „oznaczenie”)",
                        "<span style='color:#2e8b57;'>✅ Nie wykryto nieciągłości w liczbach porządkowych w polu „oznaczenie”.</span>",
                        None
                    ))
            else:
                rows.append((
                    "Ciągłość oznaczeń (pole „oznaczenie”)",
                    "<span style='background-color:#fff3cd; color:#8a6d3b; padding:2px 4px; border-radius:3px;'>"
                    "⚠️ Nie wykryto żadnych cyfr w polu „oznaczenie” – kontrola ciągłości została pominięta."
                    "</span>",
                    None
                ))
        else:
            rows.append((
                "Ciągłość oznaczeń (pole „oznaczenie”)",
                "<span style='color:#c0392b;'>❗ Brak pola „oznaczenie” w warstwie kontrolowanej</span>",
                current_name
            ))

        # 7) Kontrola powierzchni (MPP) + warstwa części poza OUZ pierwotnym
        n_feats = sum(1 for _ in active.getFeatures())
        mp.start("Krok 7/7 – obliczanie powierzchni i MPP…", maximum=max(1, n_feats))
        pow_A = 0.0
        pow_B = 0.0
        parts_outside_feats: List[QgsFeature] = []
        i = 0

        for f in active.getFeatures():
            g = f.geometry()
            if g and not g.isEmpty():
                pow_A += _area_ha(g, active.crs())
                diff = g.difference(ouz_union_trans)
                if diff and not diff.isEmpty():
                    pow_B += _area_ha(diff, active.crs())
                    feat = QgsFeature()
                    feat.setGeometry(diff)
                    parts_outside_feats.append(feat)
            i += 1
            mp.step(i)

        if parts_outside_feats:
            tmp_name = "ouzopt_poza_pierwotnym_ouz"
            _replace_layer_by_name(tmp_name)
            crs_auth = active.crs().authid() or active.crs().toWkt()
            uri = f"Polygon?crs={crs_auth}"
            tmp = QgsVectorLayer(uri, tmp_name, "memory")
            pr = tmp.dataProvider()
            tmp.updateFields()

            mp.start("Krok 7/7 – budowanie warstwy części poza OUZ pierwotnym…", maximum=len(parts_outside_feats))
            batch = []
            for k, feat in enumerate(parts_outside_feats, start=1):
                batch.append(feat)
                if (k % 100) == 0 or k == len(parts_outside_feats):
                    pr.addFeatures(batch)
                    batch = []
                mp.step(k)
            tmp.updateExtents()
            proj = QgsProject.instance()
            group = _ensure_group("OUZ KONTROLA")
            proj.addMapLayer(tmp, False)
            group.addLayer(tmp)

        # komunikaty MPP
        def _fmt(x: float) -> str:
            return f"{x:.2f} ha"

        info_lines = (
            f"Powierzchnia OUZ po optymalizacji: {_fmt(pow_A)}",
            f"Powierzchnia dodana ponad OUZ pierwotny: {_fmt(pow_B)}",
            f"Maksymalna Powierzchnia Powiększenia: {_fmt(max(0.0, mpp_ha))}",
        )
        info_html = "<br>".join(info_lines)

        err_layer_for_mpp: Optional[str] = None
        if pow_B == 0.0:
            status_html = (
                f"{info_html}<br>"
                f"<span style='color:#2e8b57;'>✅ Nie dokonano powiększenia poza pierwotny OUZ</span>"
            )
        else:
            if mpp_ha <= 0.0:
                status_html = (
                    f"{info_html}<br>"
                    f"<span style='color:#c0392b;'>❗ Przekroczono Maksymlaną Powierzchnię Powiększenia (MPP = 0 ha)</span>"
                )
                err_layer_for_mpp = current_name
            else:
                used_pct = (pow_B / mpp_ha) * 100.0
                used_txt = f"Wykorzystano {used_pct:.1f}% Maksymalnej Powierzchni Powiększenia"
                if mpp_ha > pow_B:
                    status_html = f"{info_html}<br><span style='color:#2e8b57;'>✅ {used_txt}</span>"
                elif mpp_ha < pow_B:
                    status_html = f"{info_html}<br><span style='color:#c0392b;'>❗ {used_txt}</span>"
                    err_layer_for_mpp = current_name
                else:
                    status_html = f"{info_html}<br><span style='color:#2e8b57;'>✅ {used_txt}</span>"

        rows.append(("Kontrola powierzchni (MPP)", status_html, err_layer_for_mpp))

    except RuntimeError:
        # użytkownik anulował
        iface.messageBar().pushWarning("Weryfikacja OUZ", "Operacja przerwana przez użytkownika.")
        return
    finally:
        # zawsze zamknij pasek
        try:
            mp.finish()
        except Exception:
            pass

    # --- Okno końcowe ---
    _show_final_report_table(
        rows,
        iface.mainWindow(),
        title="Weryfikacja OUZ – podsumowanie",
        header_layer_current=current_name,
        header_layer_ouz=selected_ouz_name,
    )
