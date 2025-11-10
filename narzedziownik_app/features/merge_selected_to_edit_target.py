"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes, QgsGeometry, QgsFeature,
    QgsCoordinateTransform, Qgis
)

def _is_poly(layer: QgsVectorLayer) -> bool:
    return isinstance(layer, QgsVectorLayer) and \
           QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry

def _collect_selected_polys():
    """Zbierz (layer, feature) dla wszystkich ZAZNACZONYCH poligonów/multipoligonów w projekcie."""
    out = []
    for lyr in QgsProject.instance().mapLayers().values():
        if not _is_poly(lyr):
            continue
        sel = lyr.selectedFeatures()
        for f in sel:
            g = f.geometry()
            if g and not g.isEmpty():
                out.append((lyr, f))
    return out

def _to_target_crs(geom: QgsGeometry, src_crs, dst_crs) -> QgsGeometry:
    if src_crs == dst_crs:
        return geom
    ct = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance().transformContext())
    g = QgsGeometry(geom)
    ok = g.transform(ct)  # 0 = OK
    return g if ok == 0 else geom

def _fix(geom: QgsGeometry) -> QgsGeometry:
    try:
        fixed = geom.buffer(0, 0)
        if fixed and not fixed.isEmpty():
            return fixed
    except Exception:
        pass
    return geom

def _clear_all_selections():
    """Usuń zaznaczenia ze wszystkich warstw wektorowych w projekcie."""
    for lyr in QgsProject.instance().mapLayers().values():
        if isinstance(lyr, QgsVectorLayer):
            try:
                if lyr.selectedFeatureCount():
                    lyr.removeSelection()   # szybkie czyszczenie zaznaczeń
            except Exception:
                pass

def run(iface, plugin_dir):
    bar = iface.messageBar()
    main = iface.mainWindow()

    # 0) Warstwa docelowa = JEDYNA włączona do edycji
    editable_layers = [
        l for l in QgsProject.instance().mapLayers().values()
        if isinstance(l, QgsVectorLayer) and l.isEditable()
    ]

    if len(editable_layers) == 0:
        bar.pushWarning("Scalanie do edycji", "Żadna warstwa nie jest włączona do edycji")
        return

    if len(editable_layers) > 1:
        bar.pushWarning("Scalanie do edycji", "Do edycji włączonych jest więcej niż jedna warstwa")
        return

    target = editable_layers[0]

    if not _is_poly(target):
        bar.pushWarning("Scalanie do edycji", f"Jedyna warstwa w edycji („{target.name()}”) nie jest poligonowa.")
        return

    # 1) Zaznaczenia z poligonów/multipoligonów
    selected = _collect_selected_polys()
    if not selected:
        bar.pushInfo("Scalanie do edycji", "Brak zaznaczonych obiektów na warstwach poligonowych.")
        return

    total = len(selected)
    progress = QProgressDialog("Scalanie zaznaczonych geometrii…", "Anuluj", 0, total, main)
    progress.setWindowModality(Qt.WindowModal)
    progress.setWindowTitle("Scalanie do warstwy edytowanej")
    progress.show()

    # 2) Transformacja do CRS docelowego + naprawa
    parts = []
    for i, (lyr, feat) in enumerate(selected, start=1):
        if progress.wasCanceled():
            progress.close()
            bar.pushWarning("Scalanie do edycji", "Przerwano przez użytkownika.")
            return
        g = _to_target_crs(feat.geometry(), lyr.crs(), target.crs())
        g = _fix(g)
        if g and not g.isEmpty() and \
           QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.PolygonGeometry:
            parts.append(g)
        progress.setValue(i)

    if not parts:
        progress.close()
        bar.pushWarning("Scalanie do edycji", "Nie udało się przygotować żadnej poprawnej geometrii.")
        return

    # 3) Unary union
    try:
        unioned = QgsGeometry.unaryUnion(parts)
    except Exception:
        base = parts[0]
        for g in parts[1:]:
            base = base.combine(g)
        unioned = base

    if not unioned or unioned.isEmpty():
        progress.close()
        bar.pushWarning("Scalanie do edycji", "Wynik scalenia jest pusty.")
        return

    unioned = _fix(unioned)

    # 4) Wstaw do warstwy docelowej (MultiPolygon → 1 obiekt, Polygon → rozbicie)
    feats_to_add = []
    if QgsWkbTypes.isMultiType(target.wkbType()):
        if not unioned.isMultipart():
            unioned = QgsGeometry.collectGeometry([unioned])
        f = QgsFeature(target.fields())
        f.setGeometry(unioned)
        feats_to_add.append(f)
    else:
        if unioned.isMultipart():
            for g in unioned.asGeometryCollection():
                if QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.PolygonGeometry:
                    f = QgsFeature(target.fields())
                    f.setGeometry(g)
                    feats_to_add.append(f)
        else:
            f = QgsFeature(target.fields())
            f.setGeometry(unioned)
            feats_to_add.append(f)

    if not feats_to_add:
        progress.close()
        bar.pushWarning("Scalanie do edycji", "Brak geometrii do dodania (niedopasowany typ?).")
        return

    # 5) Zapis w jednej komendzie edycyjnej
    target.beginEditCommand("Scal i wstaw zaznaczenia do warstwy")
    ok = target.addFeatures(feats_to_add)
    if not ok:
        target.destroyEditCommand()
        progress.close()
        bar.pushCritical("Scalanie do edycji", "Nie udało się dodać obiektów do warstwy.")
        return
    target.endEditCommand()

    # NOWOŚĆ: wyczyszczenie zaznaczeń na wszystkich warstwach
    _clear_all_selections()

    progress.close()
    bar.pushSuccess("Scalanie do edycji", f"Dodano {len(feats_to_add)} obiekt(ów) do „{target.name()}”. Zaznaczenia wyczyszczono.")
