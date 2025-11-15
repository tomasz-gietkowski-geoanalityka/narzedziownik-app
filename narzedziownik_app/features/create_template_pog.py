# -*- coding: utf-8 -*-
"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)
"""

import os
import re

from qgis.PyQt.QtWidgets import QMessageBox, QInputDialog
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
)


def _templates_dir(plugin_dir: str) -> str:
    """Zwraca ścieżkę do katalogu z szablonami POG."""
    return os.path.join(plugin_dir, "resources", "templates", "wtyczkaapp2")


def _qml_dir(plugin_dir: str) -> str:
    """Zwraca ścieżkę do katalogu ze stylami QML."""
    return os.path.join(plugin_dir, "resources", "qml")


def _load_template_layers(templates_path: str) -> list[QgsVectorLayer]:
    """
    Wyszukuje i ładuje warstwy-wzorce z katalogu szablonów.

    Założenia:
    - Każdy plik w katalogu reprezentuje pojedynczą warstwę wektorową
      (np. .gpkg, .shp itp.).
    - Warstwy są ładowane przez OGR.
    """
    layers: list[QgsVectorLayer] = []

    if not os.path.isdir(templates_path):
        return layers

    for fname in sorted(os.listdir(templates_path)):
        fpath = os.path.join(templates_path, fname)
        if not os.path.isfile(fpath):
            continue

        if not re.search(r"\.(gpkg|shp|geojson|json|gml|sqlite)$", fname, re.IGNORECASE):
            continue

        lyr = QgsVectorLayer(fpath, os.path.splitext(fname)[0], "ogr")
        if lyr.isValid():
            layers.append(lyr)

    return layers


def _geom_def_from_template(layer: QgsVectorLayer) -> str:
    """
    Na podstawie warstwy-wzorca tworzy definicję geometrii dla providera „memory”.

    Np. MultiPolygonZ -> MultiPolygon (ignorujemy Z/M).
    """
    from qgis.core import QgsWkbTypes

    wkb = layer.wkbType()
    disp = QgsWkbTypes.displayString(wkb)  # np. 'MultiPolygonZ'
    disp = re.sub(r"(Z|M|ZM)$", "", disp)

    if not disp:
        return "Polygon"

    return disp


def _ensure_group(root, name: str):
    """Zapewnia istnienie grupy o danej nazwie i ją zwraca."""
    grp = root.findGroup(name)
    if grp is None:
        grp = root.addGroup(name)
    return grp


def _create_memory_layer_from_template(
    template_layer: QgsVectorLayer,
    crs_authid: str,
) -> QgsVectorLayer | None:
    """
    Tworzy warstwę 'memory' na podstawie warstwy-wzorca:
    - ten sam typ geometrii (bez Z/M),
    - ten sam zestaw pól,
    - nazwa = nazwa warstwy-wzorca,
    - zadany układ współrzędnych.
    """
    geom_def = _geom_def_from_template(template_layer)
    name = template_layer.name()

    uri = f"{geom_def}?crs={crs_authid}"
    mem_layer = QgsVectorLayer(uri, name, "memory")

    if not mem_layer.isValid():
        return None

    dp = mem_layer.dataProvider()
    dp.addAttributes(template_layer.fields())
    mem_layer.updateFields()

    return mem_layer


def _style_path_for_layer(name: str, plugin_dir: str) -> str | None:
    base = _qml_dir(plugin_dir)
    lname = name.lower()

    mapping = {
        "aktplanowaniaprzestrzennego": "styl-AktPlanowaniaPrzestrzennego.qml",
        "obszaruzupelnieniazabudowy": "styl-ObszarUzupelnieniaZabudowy.qml",
        "obszarzabudowysrodmiejskiej": "styl-ObszarZabudowySrodmiejskiej.qml",
        "strefaplanistyczna": "styl-StrefaPlanistyczna.qml",
        "obszarstandardowdostepnosciinfrastrukturyspolecznej":"styl-ObszarStandardowDostepnosciInfrastrukturySpolecznej.qml"
    }

    for key, fname in mapping.items():
        if key in lname:
            path = os.path.join(base, fname)
            if os.path.exists(path):
                return path

    return None


def run(iface, plugin_dir: str):
    """
    Główna funkcja tworząca szablony POG:

    1) Wczytuje warstwy-wzorce z katalogu resources/templates/wtyczkaapp2.
    2) W jednym oknie:
       - informuje, jakie warstwy APP POG zostaną utworzone,
       - prosi o wybór układu współrzędnych (EPSG:2176/2177/2178/2179).
    3) Tworzy w grupie „POG SZABLONY” odpowiednie warstwy tymczasowe (memory)
       w wybranym CRS.
    4) Dla utworzonych warstw stosuje odpowiednie style QML z resources/qml.
    """

    main = iface.mainWindow()
    bar = iface.messageBar()

    templates_path = _templates_dir(plugin_dir)
    template_layers = _load_template_layers(templates_path)

    if not template_layers:
        QMessageBox.warning(
            main,
            "Szablony APP POG",
            (
                "Nie odnaleziono żadnych szablonów w katalogu:<br><br>"
                f"<code>{templates_path}</code><br><br>"
                "Upewnij się, że w katalogu znajdują się pliki z warstwami-wzorcami."
            ),
        )
        return

    # Lista nazw warstw do tekstu w oknie
    names_html = "<br>".join(
        f"&bull; {lyr.name()}" for lyr in template_layers
    )

    items = [
        "EPSG:2176 – Układ 2000 strefa 5",
        "EPSG:2177 – Układ 2000 strefa 6",
        "EPSG:2178 – Układ 2000 strefa 7",
        "EPSG:2179 – Układ 2000 strefa 8",
    ]
    default_index = 1  # np. 2177 jako domyślny

    label_text = (
        "Zostaną stworzone warstwy APP POG zgodne z wymaganiami Wtyczki APP2.<br><br>"
        "Lista tworzonych warstw:<br><br>"
        f"{names_html}<br><br>"
        "Wybierz układ współrzędnych dla tworzonych szablonów:"
    )

    item, ok = QInputDialog.getItem(
        main,
        "Szablony APP POG",
        label_text,
        items,
        current=default_index,
        editable=False,
    )

    if not ok:
        bar.pushInfo("Szablony APP POG", "Tworzenie szablonów zostało przerwane przez użytkownika.")
        return

    m = re.match(r"^(EPSG:\d+)", item.strip())
    if not m:
        QMessageBox.warning(
            main,
            "Szablony APP POG",
            "Nie udało się zidentyfikować wybranego układu współrzędnych."
        )
        return

    crs_authid = m.group(1)

    # Tworzenie warstw pamięciowych w projekcie
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = _ensure_group(root, "POG SZABLONY")

    created_layers = []
    for tmpl in template_layers:
        mem_layer = _create_memory_layer_from_template(tmpl, crs_authid)
        if mem_layer is None:
            continue

        # Dodaj warstwę do projektu i do grupy
        project.addMapLayer(mem_layer, False)
        group.insertLayer(0, mem_layer)

        # Zastosuj styl, jeśli dostępny
        style_path = _style_path_for_layer(mem_layer.name(), plugin_dir)
        if style_path:
            mem_layer.loadNamedStyle(style_path)
            mem_layer.triggerRepaint()

        created_layers.append(mem_layer.name())

    if not created_layers:
        QMessageBox.warning(
            main,
            "Szablony APP POG",
            "Nie udało się utworzyć żadnej warstwy szablonu APP POG.\n"
            "Sprawdź poprawność warstw-wzorców."
        )
        return

    created_html = "<br>".join(f"&bull; {n}" for n in created_layers)
    QMessageBox.information(
        main,
        "Szablony APP POG",
        (
            f"Utworzono warstwy szablonowe w grupie „POG SZABLONY”<br>"
            f"w układzie <b>{crs_authid}</b>:<br><br>"
            f"{created_html}"
        ),
    )
    bar.pushSuccess("Szablony APP POG", "Utworzono warstwy szablonowe w grupie „POG SZABLONY”.")
