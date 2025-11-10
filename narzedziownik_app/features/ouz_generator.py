"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
# ***************************************************************************************
# OUZ Generator – uruchamia przetwarzanie i na końcu proponuje zapis raportu XML.
# Po dodaniu warstw tylko "ObszarUzupelnieniaZabudowy" jest włączona (widoczna).
# ***************************************************************************************

from qgis.PyQt.QtCore import QVariant, QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog, QFileDialog
from qgis.PyQt.QtGui import QColor

from qgis.core import (
    QgsProject,
    QgsSpatialIndex,
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsWkbTypes,
    QgsMessageLog,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsSymbol,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
    Qgis,
)

import os
from datetime import datetime
import xml.etree.ElementTree as ET
import networkx as nx


# --- helpers ---------------------------------------------------------------------------

def add_layer_to_group(layer, group_name, visible=False):
    """
    Dodaje warstwę do grupy w drzewku i ustawia jej widoczność (checkbox).
    Nie zmienia widoczności innych warstw.
    """
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.addGroup(group_name)

    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    # sterowanie „oczkiem” (checkbox widoczności)
    try:
        node.setItemVisibilityChecked(visible)
    except Exception:
        # starsze wersje QGIS – awaryjnie: wyłączenie/ włączenie przez root
        if visible:
            root.setHasCustomLayerOrder(True)
        # brak alternatywy API dla samego checkboxa – ignorujemy
        pass


def apply_categorized_symbology(layer, attribute):
    categories = []
    fld_idx = layer.fields().lookupField(attribute)
    unique_values = layer.uniqueValues(fld_idx) if fld_idx != -1 else []
    for value in unique_values:
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        categories.append(QgsRendererCategory(value, symbol, str(value)))
    renderer = QgsCategorizedSymbolRenderer(attribute, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def apply_labeling(layer):
    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = "rodzajWgKST_2015"
    label_settings.enabled = True

    text_format = QgsTextFormat()
    text_format.setSize(10)

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1)
    buffer_settings.setColor(QColor("white"))
    text_format.setBuffer(buffer_settings)

    label_settings.setFormat(text_format)
    labeling = QgsVectorLayerSimpleLabeling(label_settings)
    layer.setLabelsEnabled(True)
    layer.setLabeling(labeling)
    layer.triggerRepaint()


def initialize_progress_dialog(total_steps, parent):
    dlg = QProgressDialog("Przetwarzanie...", "Anuluj", 0, total_steps, parent)
    dlg.setWindowTitle("Postęp obliczeń")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.show()
    return dlg


def indent_xml(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i
    return elem


# --- main -----------------------------------------------------------------------------

def run(iface, plugin_dir):
    main = iface.mainWindow()

    # PRE-INFO (kontynuuj / anuluj)
    pre = QMessageBox(main)
    pre.setWindowTitle("OUZ Generator")
    pre.setIcon(QMessageBox.Information)
    pre.setTextFormat(Qt.RichText)
    pre.setText(
        "Algorytm tworzenia OUZ wymaga warstwy "
        "<b>budynki_ouz</b> (z polem <b>rodzajWgKST_2025</b>) "
        "oraz warstwy <b>AktPlanowaniaPrzestrzennego</b> (z granicą aktu).<br><br>"
        "Upewnij się, że wymagane warstwy są w projekcie."
    )
    btn_go = pre.addButton("Kontynuuj", QMessageBox.AcceptRole)
    btn_cancel = pre.addButton("Anuluj", QMessageBox.RejectRole)
    pre.exec_()
    if pre.clickedButton() is btn_cancel:
        return

    # Pobranie warstw
    try:
        layer = QgsProject.instance().mapLayersByName('budynki_ouz')[0]
        planning_layer = QgsProject.instance().mapLayersByName('AktPlanowaniaPrzestrzennego')[0]
    except Exception:
        QMessageBox.warning(main, "OUZ Generator",
                            "Brak wymaganych warstw: 'budynki_ouz' i/lub 'AktPlanowaniaPrzestrzennego'.")
        return

    crs = layer.crs()

    # Indeks i graf
    spatial_index = QgsSpatialIndex(layer.getFeatures())
    G = nx.Graph()

    features = list(layer.getFeatures())
    total_features = len(features)
    progress_dialog = initialize_progress_dialog(total_features, main)

    # Węzły grafu (filtr wg rodzajWgKST_2015)
    for i, feature in enumerate(features):
        if feature['rodzajWgKST_2015'] in ('101', '103', '105', '106', '107', '109', '110'):
            geom = feature.geometry()
            if geom and geom.isGeosValid():
                G.add_node(feature.id(), geometry=geom, rodzajWgKST_2015=feature['rodzajWgKST_2015'])
            else:
                QgsMessageLog.logMessage(
                    f"Błąd: brak geometrii dla budynku ID {feature.id()}",
                    level=Qgis.Critical
                )
        progress_dialog.setValue(i)
        QCoreApplication.processEvents()

    # Krawędzie (<=100 m)
    for i, feature in enumerate(features):
        if feature['rodzajWgKST_2015'] in ('101', '103', '105', '106', '107', '109', '110'):
            geometry = feature.geometry()
            if geometry.isGeosValid():
                neighbors_ids = spatial_index.intersects(geometry.buffer(100, 60).boundingBox())
                for neighbor_id in neighbors_ids:
                    if feature.id() == neighbor_id:
                        continue
                    neighbor = layer.getFeature(neighbor_id)
                    if neighbor['rodzajWgKST_2015'] in ('101', '103', '105', '106', '107', '109', '110'):
                        neighbor_geom = neighbor.geometry()
                        if geometry.distance(neighbor_geom) <= 100:
                            G.add_edge(feature.id(), neighbor_id)
        progress_dialog.setValue(i)
        QCoreApplication.processEvents()

    # Komponenty spójne
    connected_components = list(nx.connected_components(G))

    # Warstwa zgrupowań
    grouped_buildings_layer = QgsVectorLayer(
        f'Polygon?crs={crs.authid()}',
        'budynki_w_zgrupowaniach',
        'memory'
    )
    grouped_buildings_provider = grouped_buildings_layer.dataProvider()
    grouped_buildings_provider.addAttributes([
        QgsField("group_id", QVariant.Int),
        QgsField("area", QVariant.Double),
        QgsField("rodzajWgKST_2015", QVariant.String)
    ])
    grouped_buildings_layer.updateFields()

    group_id = 1
    for i, component in enumerate(connected_components):
        if len(component) >= 5:
            for node in component:
                geometry = G.nodes[node]['geometry']
                kst = G.nodes[node]['rodzajWgKST_2015']
                if geometry and geometry.isGeosValid():
                    f = QgsFeature()
                    f.setGeometry(geometry)
                    f.setAttributes([group_id, geometry.area(), kst])
                    grouped_buildings_provider.addFeature(f)
            group_id += 1
        progress_dialog.setValue(i)
        QCoreApplication.processEvents()

    grouped_buildings_layer.updateExtents()
    add_layer_to_group(grouped_buildings_layer, 'OUZ', visible=False)  # wyłączona
    apply_categorized_symbology(grouped_buildings_layer, "group_id")
    apply_labeling(grouped_buildings_layer)

    # Bufory 50 m
    buffer_layer = QgsVectorLayer(
        f'Polygon?crs={crs.authid()}',
        'Zgrupowania_Buffer',
        'memory'
    )
    prov = buffer_layer.dataProvider()
    prov.addAttributes([QgsField("group_id", QVariant.Int), QgsField("area", QVariant.Double)])
    buffer_layer.updateFields()

    all_buffers = []
    for feature in grouped_buildings_layer.getFeatures():
        geometry = feature.geometry()
        if geometry.isGeosValid():
            buffer_geom = geometry.buffer(50, 60)
            if buffer_geom and buffer_geom.isGeosValid():
                all_buffers.append(buffer_geom)

    dissolved_geometry = QgsGeometry.unaryUnion(all_buffers)
    dissolved_geometry_parts = dissolved_geometry.asGeometryCollection() if dissolved_geometry.isMultipart() else [dissolved_geometry]

    # Niedocięta powierzchnia
    before_shrink_layer = QgsVectorLayer(
        f'Polygon?crs={crs.authid()}',
        'powierzchnia_przed_zwezeniem_niedocieta',
        'memory'
    )
    before_prov = before_shrink_layer.dataProvider()
    before_prov.addAttributes([QgsField("area", QVariant.Double)])
    before_shrink_layer.updateFields()

    for geom in dissolved_geometry_parts:
        try:
            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
            else:
                polygons = [geom.asPolygon()]

            cleaned_geometries = []
            for polygon in polygons:
                try:
                    exterior_ring = polygon[0]
                    interior_rings = polygon[1:]
                    base_geom = QgsGeometry.fromPolygonXY([exterior_ring])
                    cleaned_geom = base_geom.removeInteriorRings()

                    for hole in interior_rings:
                        hole_geom = QgsGeometry.fromPolygonXY([hole])
                        hole_area = hole_geom.area()
                        if hole_area > 5000:
                            QgsMessageLog.logMessage(
                                f"Dziura pozostaje, powierzchnia: {hole_area} m²",
                                level=Qgis.Info
                            )
                            cleaned_geom = cleaned_geom.difference(hole_geom)
                        else:
                            QgsMessageLog.logMessage(
                                f"Dziura usunięta, powierzchnia: {hole_area} m²",
                                level=Qgis.Info
                            )

                    if cleaned_geom and cleaned_geom.isGeosValid():
                        cleaned_geometries.append(cleaned_geom)
                    else:
                        QgsMessageLog.logMessage("Błąd geometrii: wynik nieprawidłowy.", level=Qgis.Critical)
                except Exception as e:
                    QgsMessageLog.logMessage(f"Błąd podczas przetwarzania dziur: {str(e)}", level=Qgis.Critical)

            final_geom = (QgsGeometry.unaryUnion(cleaned_geometries)
                          if len(cleaned_geometries) > 1
                          else (cleaned_geometries[0] if cleaned_geometries else None))
            if final_geom and final_geom.isGeosValid():
                dissolved_feature = QgsFeature()
                dissolved_feature.setGeometry(final_geom)
                dissolved_feature.setAttributes([final_geom.area()])
                before_prov.addFeature(dissolved_feature)
            else:
                QgsMessageLog.logMessage("Finalna geometria jest nieprawidłowa.", level=Qgis.Critical)

        except Exception as e:
            QgsMessageLog.logMessage(f"Błąd podczas przetwarzania geometrii wieloczęściowej: {str(e)}", level=Qgis.Critical)

    before_shrink_layer.updateExtents()
    add_layer_to_group(before_shrink_layer, 'OUZ', visible=False)  # wyłączona

    # Docinanie do APP
    docieta_layer = QgsVectorLayer(
        f'Polygon?crs={crs.authid()}',
        'powierzchnia_przed_zwezeniem_docieta',
        'memory'
    )
    docieta_provider = docieta_layer.dataProvider()
    docieta_provider.addAttributes([QgsField("area", QVariant.Double)])
    docieta_layer.updateFields()

    for feature in before_shrink_layer.getFeatures():
        geometry = feature.geometry()
        for planning_feature in planning_layer.getFeatures():
            planning_geometry = planning_feature.geometry()
            intersection_geom = geometry.intersection(planning_geometry)
            if intersection_geom.isGeosValid() and not intersection_geom.isEmpty():
                f = QgsFeature()
                f.setGeometry(intersection_geom)
                f.setAttributes([intersection_geom.area()])
                docieta_provider.addFeature(f)

    docieta_layer.updateExtents()
    add_layer_to_group(docieta_layer, 'OUZ', visible=False)  # wyłączona

    # Final OUZ – CRS = CRS budynków, schemat pól z GPKG template
    tmpl_gpkg_path = os.path.join(plugin_dir, "resources", "templates", "obszaruzupelnieniazabudowy.gpkg")

    final_layer = QgsVectorLayer(
        f'Polygon?crs={crs.authid()}',
        'ObszarUzupelnieniaZabudowy',      # <- NAZWA WARSTWY
        'memory'
    )
    final_provider = final_layer.dataProvider()

    tmpl_layer = None
    if os.path.exists(tmpl_gpkg_path):
        uri1 = f"{tmpl_gpkg_path}|layername=obszaruzupelnieniazabudowy"
        lyr1 = QgsVectorLayer(uri1, "tmpl_ouz", "ogr")
        if lyr1.isValid():
            tmpl_layer = lyr1
        else:
            uri2 = f"{tmpl_gpkg_path}|layername=ObszarUzupelnieniaZabudowy"
            lyr2 = QgsVectorLayer(uri2, "tmpl_ouz", "ogr")
            if lyr2.isValid():
                tmpl_layer = lyr2

    if tmpl_layer and tmpl_layer.isValid():
        final_provider.addAttributes(list(tmpl_layer.fields()))
        final_layer.updateFields()
    else:
        QMessageBox.warning(
            main, "OUZ Generator",
            "Nie udało się wczytać schematu pól z pliku:\n"
            f"{tmpl_gpkg_path}\n\nZastosowano minimalny zestaw pól."
        )
        final_provider.addAttributes([
            QgsField("nazwa", QVariant.String),
            QgsField("symbol", QVariant.String),
            QgsField("oznaczenie", QVariant.String),
            QgsField("lokalnyId", QVariant.String),
        ])
        final_layer.updateFields()

    # Styl QML dla finalnej warstwy
    qml_path = os.path.join(plugin_dir, "resources", "qml", "styl-ObszarUzupelnieniaZabudowy.qml")
    if os.path.exists(qml_path):
        final_layer.loadNamedStyle(qml_path)
        final_layer.triggerRepaint()

    # Wypełnianie final_layer
    unique_id = 1
    for feature in before_shrink_layer.getFeatures():
        geometry = feature.geometry()
        shrunk_geom = geometry.buffer(-40, 60)
        if shrunk_geom.isGeosValid() and not shrunk_geom.isEmpty():
            for planning_feature in planning_layer.getFeatures():
                planning_geometry = planning_feature.geometry()
                intersection_geom = shrunk_geom.intersection(planning_geometry)
                if intersection_geom.isGeosValid() and not intersection_geom.isEmpty():
                    geometries = (intersection_geom.asGeometryCollection()
                                  if intersection_geom.isMultipart()
                                  else [intersection_geom])
                    for geom in geometries:
                        oznaczenie_value = f"{unique_id}OUZ"
                        lokalny_id_value = f"1POG-{oznaczenie_value}"

                        f = QgsFeature(final_layer.fields())
                        f.setGeometry(geom)
                        if final_layer.fields().indexOf("nazwa") != -1:
                            f.setAttribute("nazwa", "Obszar uzupełnienia zabudowy")
                        if final_layer.fields().indexOf("symbol") != -1:
                            f.setAttribute("symbol", "OUZ")
                        if final_layer.fields().indexOf("oznaczenie") != -1:
                            f.setAttribute("oznaczenie", oznaczenie_value)
                        if final_layer.fields().indexOf("lokalnyId") != -1:
                            f.setAttribute("lokalnyId", lokalny_id_value)
                        final_provider.addFeature(f)
                        unique_id += 1

    final_layer.updateExtents()
    add_layer_to_group(final_layer, 'OUZ', visible=True)  # <-- tylko ta warstwa włączona

    # Obliczenia do podsumowania
    powierzchnia_docieta = sum([feat.geometry().area() for feat in docieta_layer.getFeatures()])
    powierzchnia_uzupelnienia = sum([feat.geometry().area() for feat in final_layer.getFeatures()])
    maks_powiekszenie = 0.25 * (powierzchnia_docieta - powierzchnia_uzupelnienia)

    # Zamknięcie postępu
    progress_dialog.close()

    # Popup z wynikami + pytanie o zapis
    summary_html = (
        "<b>Wyniki obliczeń:</b><br><br>"
        f"Powierzchnia przed zwężeniem: <b>{(powierzchnia_docieta/10000):.2f}</b> ha<br>"
        f"Powierzchnia OUZ: <b>{(powierzchnia_uzupelnienia/10000):.2f}</b> ha<br>"
        f"Maksymalne powiększenie (25% różnicy): <b>{(maks_powiekszenie/10000):.2f}</b> ha<br><br>"
        "Czy chcesz <b>zapisać raport XML</b>?"
    )

    ask = QMessageBox(main)
    ask.setWindowTitle("Wyniki obliczeń OUZ")
    ask.setIcon(QMessageBox.Information)
    ask.setTextFormat(Qt.RichText)
    ask.setText(summary_html)
    btn_save = ask.addButton("Zapisz raport", QMessageBox.AcceptRole)
    btn_close = ask.addButton("Zamknij", QMessageBox.RejectRole)
    ask.exec_()

    if ask.clickedButton() is btn_save:
        # Wybór ścieżki zapisu XML (domyślnie: Projekt/Dokumentacja)
        project_dir = QgsProject.instance().homePath() or os.path.expanduser("~")
        domy_dir = os.path.join(project_dir, "Dokumentacja")
        os.makedirs(domy_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M")
        domy_plik = os.path.join(domy_dir, f"Powierzchnie_danych_OUZ_{timestamp}.xml")

        xml_path, _ = QFileDialog.getSaveFileName(
            main,
            "Wybierz lokalizację pliku XML",
            domy_plik,
            "Pliki XML (*.xml)"
        )

        if xml_path:
            root = ET.Element("WynikiOUZ")
            ET.SubElement(root, "PowierzchniaPrzedZwezeniem").text = str(powierzchnia_docieta)
            ET.SubElement(root, "PowierzchniaOUZ").text = str(powierzchnia_uzupelnienia)
            ET.SubElement(root, "MaksymalnaPowierzchniaPowiekszenia").text = str(maks_powiekszenie)
            ET.SubElement(root, "dataObliczen").text = timestamp
            indent_xml(root)
            ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
            QgsMessageLog.logMessage(f"Wyniki zapisane w pliku: {xml_path}", level=Qgis.Info)
        else:
            QgsMessageLog.logMessage("Zapis XML anulowany przez użytkownika.", level=Qgis.Warning)

    # koniec
