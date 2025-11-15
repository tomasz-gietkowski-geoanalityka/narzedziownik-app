# -*- coding: utf-8 -*-
"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)
"""

import re
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    edit,
)


def _find_lokalny_field(layer: QgsVectorLayer) -> str | None:
    """
    Znajduje pole lokalnego identyfikatora.
    Priorytet: 'lokalnyId', ewentualnie 'loklaneId' (dla starszych warstw z literówką).
    """
    field_names = [f.name() for f in layer.fields()]
    for cand in ("lokalnyId", "loklaneId"):
        if cand in field_names:
            return cand
    return None


def _collect_numbers_from_oznaczenie(layer: QgsVectorLayer, oznaczenie_field: str) -> dict:
    """
    Zbiera informacje o liczbowej części z pola 'oznaczenie'.

    Zwraca:
    {
      fid: {
        "raw": oryginalny_tekst,
        "num": liczba_int_lub_None,
        "prefix": część przed liczbą,
        "suffix": część po liczbie,
      },
      ...
    }
    """
    result = {}

    for f in layer.getFeatures():
        val = f[oznaczenie_field]
        text = "" if val is None else str(val).strip()
        num = None
        prefix = ""
        suffix = ""

        if text:
            m = re.search(r'(\d+)', text)
            if m:
                try:
                    num = int(m.group(1))
                    prefix = text[:m.start(1)]
                    suffix = text[m.end(1):]
                except Exception:
                    num = None

        result[f.id()] = {
            "raw": text,
            "num": num,
            "prefix": prefix,
            "suffix": suffix,
        }

    return result


def _compute_missing_numbers(nums: set[int]) -> list[int]:
    """
    Dla zbioru numerów zwraca listę brakujących wartości
    w zakresie 1..max(nums).

    Numeracja jest traktowana jako poprawna tylko wtedy,
    gdy zaczyna się od 1 i jest ciągła (1,2,3,…,N).
    """
    if not nums:
        return []
    end = max(nums)
    # wymagamy pełnego ciągu od 1 do max
    missing = [n for n in range(1, end + 1) if n not in nums]
    return missing


def _build_reindex_mapping(nums: set[int]) -> dict[int, int]:
    """
    Tworzy mapowanie stary_numer -> nowy_numer, tak aby numeracja była ciągła 1..N.

    Przykład:
      nums = {1, 2, 4, 5} -> mapping = {1: 1, 2: 2, 4: 3, 5: 4}
    """
    sorted_nums = sorted(nums)
    mapping = {old: i + 1 for i, old in enumerate(sorted_nums)}
    return mapping


def _update_oznaczenie_and_lokalnyId(
    layer: QgsVectorLayer,
    oznaczenie_field: str,
    lokalny_field: str,
    oznaczenia_info: dict,
    mapping: dict[int, int],
):
    """
    Aktualizuje pola 'oznaczenie' i 'lokalnyId' według mapowania stary_numer -> nowy_numer.

    - 'oznaczenie': prefix + nowy_numer + suffix
    - 'lokalnyId': np. "1POG-1OUZ" -> "1POG-3OUZ"
       (zamiana tylko liczbowej części drugiego członu po myślniku)
    """
    ozn_idx = layer.fields().indexFromName(oznaczenie_field)
    lok_idx = layer.fields().indexFromName(lokalny_field)

    if ozn_idx == -1 or lok_idx == -1:
        return

    with edit(layer):
        for f in layer.getFeatures():
            info = oznaczenia_info.get(f.id())
            if not info:
                continue

            old_num = info["num"]
            if old_num is None or old_num not in mapping:
                continue

            new_num = mapping[old_num]

            # --- nowe oznaczenie ---
            new_ozn = f"{info['prefix']}{new_num}{info['suffix']}"
            layer.changeAttributeValue(f.id(), ozn_idx, new_ozn)

            # --- nowe lokalnyId ---
            lok_val = f[lokalny_field]
            lok_text = "" if lok_val is None else str(lok_val).strip()

            # oczekiwany format mniej więcej: "1POG-1OUZ"
            # -> prefix: "1POG-" ; digits: "1" ; suffix: "OUZ"
            m = re.match(r"^([^-\n\r]+-)(\d+)(.*)$", lok_text)
            if m:
                new_lok = f"{m.group(1)}{new_num}{m.group(3)}"
                layer.changeAttributeValue(f.id(), lok_idx, new_lok)
            # jeśli format jest inny, nie modyfikujemy 'lokalnyId'


def run(iface):
    """
    Główny punkt wejścia modułu.

    1) Pobiera aktywną warstwę.
    2) Sprawdza obecność pól 'oznaczenie' i 'lokalnyId'/'loklaneId'.
    3) Analizuje ciąg numerów w polu 'oznaczenie' i wykrywa nieciągłości
       (wymagana numeracja od 1).
    4) Jeśli są luki – w jednym oknie pokazuje nazwę warstwy, brakujące numery i ostrzeżenia
       oraz pyta, czy przeliczyć oznaczenia + lokalnyId.
    """

    layer = iface.activeLayer()

    if not isinstance(layer, QgsVectorLayer):
        QMessageBox.warning(
            iface.mainWindow(),
            "Przeliczanie oznaczeń",
            (
                "Aktywna warstwa nie jest warstwą wektorową.<br>"
                "Wybierz odpowiednią warstwę i spróbuj ponownie."
            ),
        )
        return

    layer_name = layer.name()
    layer_name_html = f"<span style='color:#8e44ad;'>{layer_name}</span>"
    field_names = [f.name() for f in layer.fields()]

    # --- krok 1: sprawdzenie pól ---
    oznaczenie_field = "oznaczenie"
    if oznaczenie_field not in field_names:
        QMessageBox.warning(
            iface.mainWindow(),
            "Przeliczanie oznaczeń",
            (
                "Aktywna warstwa "
                f"{layer_name_html} nie zawiera pola „oznaczenie”.<br>"
                "Wybierz poprawną warstwę i spróbuj ponownie."
            ),
        )
        return

    lokalny_field = _find_lokalny_field(layer)
    if lokalny_field is None:
        QMessageBox.warning(
            iface.mainWindow(),
            "Przeliczanie oznaczeń",
            (
                "Aktywna warstwa "
                f"{layer_name_html} nie zawiera wymaganego pola „lokalnyId”.<br>"
                "Upewnij się, że warstwa posiada pole „lokalnyId” "
                "i spróbuj ponownie."
            ),
        )
        return

    # --- krok 2: analiza ciągłości oznaczeń ---
    oznaczenia_info = _collect_numbers_from_oznaczenie(layer, oznaczenie_field)
    nums = {info["num"] for info in oznaczenia_info.values() if info["num"] is not None}

    if not nums:
        QMessageBox.information(
            iface.mainWindow(),
            "Przeliczanie oznaczeń",
            (
                "Nie znaleziono żadnych wartości liczbowych w polu „oznaczenie”.<br>"
                "Kontrola ciągłości numeracji została pominięta."
            ),
        )
        return

    missing = _compute_missing_numbers(nums)

    if not missing:
        QMessageBox.information(
            iface.mainWindow(),
            "Przeliczanie oznaczeń",
            (
                "Nie wykryto nieciągłości w numeracji pola „oznaczenie”.<br>"
                "Działanie nie jest wymagane."
            ),
        )
        return

    # --- krok 3: jedno okno z nazwą warstwy, brakującymi numerami i ostrzeżeniami ---
    missing_str = ", ".join(str(n) for n in missing)
    missing_html = f"<span style='color:#c0392b;'>{missing_str}</span>"

    question_text = (
        "Aktywna warstwa:<br><br>"
        f"&nbsp;&nbsp;&nbsp;&nbsp;{layer_name_html}<br><br>"
        "Wykryto brakujące wartości w liczbowej części pola „oznaczenie”<br>"
        "(numeracja wymagana od 1, bez nieciągłości):<br><br>"
        f"&nbsp;&nbsp;&nbsp;&nbsp;{missing_html}<br><br>"
        "Przeliczenie nastąpi w atrybutach wskazanej warstwy.<br>"
        "Jeśli chcesz wykonać kopię warstwy przed przeliczeniem, przerwij działanie.<br><br>"
        "Czy chcesz przeliczyć oznaczenia tak, aby numeracja była ciągła (1..N)<br>"
        "oraz zaktualizować odpowiednio pole „lokalnyId”?"
    )

    resp_fix = QMessageBox.question(
        iface.mainWindow(),
        "Przeliczanie oznaczeń",
        question_text,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )

    # --- krok 4: jeśli „Nie” – przerwij ---
    if resp_fix != QMessageBox.Yes:
        return

    # --- krok 5: przeliczenie oznaczeń i lokalnyId ---
    mapping = _build_reindex_mapping(nums)
    _update_oznaczenie_and_lokalnyId(
        layer=layer,
        oznaczenie_field=oznaczenie_field,
        lokalny_field=lokalny_field,
        oznaczenia_info=oznaczenia_info,
        mapping=mapping,
    )

    QMessageBox.information(
        iface.mainWindow(),
        "Przeliczanie oznaczeń",
        (
            "Przeliczanie pola „oznaczenie” oraz aktualizacja pola "
            f"„{lokalny_field}” w warstwie {layer_name_html} zostały zakończone."
        ),
    )
