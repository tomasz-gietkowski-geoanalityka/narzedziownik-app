"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
from typing import List, Optional, Sequence, Tuple
import re
from urllib.parse import quote

from qgis.PyQt.QtGui import QGuiApplication, QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer,
    Qgis, QgsMessageLog
)

# ------------------------- wspólne helpers -------------------------

def _log(msg: str, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, "Narzędziownik APP / EZiUDP", level)

def _ensure_group_path(path: List[str]):
    root = QgsProject.instance().layerTreeRoot()
    grp = root
    for name in path or []:
        child = grp.findGroup(name) if hasattr(grp, "findGroup") else None
        if not child:
            child = grp.addGroup(name)
        grp = child
    return grp

# ------------------------- WMS -------------------------

def add_wms_layer(href: str, layer_name: str, title: str,
                  preferred_crs: str = "EPSG:2180", group_path=None):
    """
    Zwraca: (layer, used_uri, used_crs)
    Prosta, stabilna składnia providera 'wms' – QGIS sam dobierze parametry GetMap.
    """
    group_path = group_path or ["EZiUDP", "WMS"]
    used_crs = preferred_crs
    uri = (
        f"contextualWMSLegend=0"
        f"&url={href}"
        f"&layers={layer_name}"
        f"&styles="
        f"&format=image/png"
        f"&crs={used_crs}"
    )
    lyr = QgsRasterLayer(uri, title or layer_name, "wms")
    if not lyr.isValid():
        _log(f"[WMS] Nie udało się utworzyć warstwy. URI: {uri}", Qgis.Critical)
        return None, uri, used_crs

    QgsProject.instance().addMapLayer(lyr, False)
    _ensure_group_path(group_path).addLayer(lyr)
    _log(f"[WMS] OK: {title or layer_name} ({used_crs})", Qgis.Info)
    return lyr, uri, used_crs

# ------------------------- WFS (po staremu – provider URI) -------------------------

def _crs_variants(code: str) -> List[str]:
    """Zwraca preferowane warianty SRS do prób (EPSG:XXXX i URN)."""
    c = (code or "").upper().strip()
    if not c:
        return []
    m = re.match(r"EPSG:(\d+)$", c)
    if not m:
        return [c]
    epsg = m.group(1)
    return [f"EPSG:{epsg}", f"urn:ogc:def:crs:EPSG::{epsg}"]

def _strip_query(url: str) -> str:
    """Zwraca scheme://host/path – bez ?query i #fragment (bez percent-encoding)."""
    url = url.split('#', 1)[0]
    url = url.split('?', 1)[0]
    return url.rstrip('?')

def _build_provider_wfs_uri(
    endpoint: str,
    typename: str,
    srsname: str,
    version: str = "2.0.0",
    *,
    restrict_to_bbox: bool = True,
    paging_enabled: bool = False,
    prefer_coords_t11: bool = False,
) -> str:
    """
    Minimalny, kompatybilny z QGIS provider-URI (jak w gissupport_plugin):
      url='<endpoint>' typename='<ns:warstwa>' version='<...>' srsname='<...>'
      pagingEnabled='enabled/disabled' restrictToRequestBBOX='1/0' preferCoordinatesForWfsT11='true/false'
    Uwaga: typename kodujemy tylko częściowo (safe='/:') — dwukropki zostają surowe.
    """
    base = _strip_query(endpoint).rstrip('?')
    tname = quote(typename, safe='/:')  # zachowuje ':' i '/'

    paging_val = 'enabled' if paging_enabled else 'disabled'
    r_bbox = '1' if restrict_to_bbox else '0'
    pref_t11 = 'true' if prefer_coords_t11 else 'false'

    # kolejność i lowercase jak w referencyjnej wtyczce
    return (
        f"pagingEnabled='{paging_val}' "
        f"srsname='{srsname}' "
        f"typename='{tname}' "
        f"url='{base}' "
        f"version='{version}' "
        f"preferCoordinatesForWfsT11='{pref_t11}' "
        f"restrictToRequestBBOX='{r_bbox}'"
    )

def add_wfs_layer(
    href: str,
    typename: str,
    title: Optional[str] = None,
    *,
    preferred_crs: str = "EPSG:2180",
    group_path: Optional[List[str]] = None,
    commit: bool = True,
    # porządek wersji jak w praktyce: 2.0.0 najpierw, potem 1.1.0 i 1.0.0 jako fallbacki
    wfs_versions: Sequence[str] = ("2.0.0", "1.1.0", "1.0.0"),
    restrict_to_bbox: bool = True,
    paging_enabled: bool = False,
    prefer_coordinates_t11: bool = False,
) -> Tuple[Optional[QgsVectorLayer], Optional[str], Optional[str]]:
    """
    Tworzy warstwę WFS używając provider-URI jak w starym utils_add_wfs.py.
    Zwraca (layer, used_uri, used_crs) albo (None, last_uri, None) przy błędzie.
    """
    title = title or typename
    endpoint = _strip_query(href)

    # kandydaci SRS (EPSG i URN)
    crs_list = _crs_variants(preferred_crs)
    # jeśli preferowany URN – dopisz czystą postać EPSG na koniec (gdyby brakło)
    if preferred_crs.upper().startswith("URN:OGC:DEF:CRS:EPSG::"):
        m = re.search(r"EPSG::(\d+)", preferred_crs.upper())
        if m:
            epsg = f"EPSG:{m.group(1)}"
            if epsg not in crs_list:
                crs_list.append(epsg)

    # przygotuj kandydatów (version × srsname)
    candidates: List[Tuple[str, str]] = []
    for ver in wfs_versions:
        for srs in crs_list:
            uri = _build_provider_wfs_uri(
                endpoint=endpoint,
                typename=typename,
                srsname=srs,
                version=ver,
                restrict_to_bbox=restrict_to_bbox,
                paging_enabled=paging_enabled,
                prefer_coords_t11=prefer_coordinates_t11,
            )
            candidates.append((uri, srs))

    last_uri = None
    last_err = None

    for uri, srs in candidates:
        last_uri = uri
        _log(f"[WFS] Próba (provider URI): {uri}", Qgis.Info)

        # Uwaga: provider-id w QGIS to 'wfs' (lowercase)
        lyr = QgsVectorLayer(uri, title, "wfs")
        if lyr.isValid():
            _log(f"[WFS] OK: {typename} ({srs})", Qgis.Info)

            if commit:
                if group_path:
                    grp = _ensure_group_path(group_path)
                    QgsProject.instance().addMapLayer(lyr, False)
                    grp.addLayer(lyr)
                else:
                    QgsProject.instance().addMapLayer(lyr)

            return lyr, uri, srs

        # loguj błąd providera (jeśli dostępny)
        try:
            err = getattr(lyr, "error", None)
            if callable(err):
                e = err()
                msg = e.message() if hasattr(e, "message") else str(e)
                if msg:
                    last_err = msg
                    _log(f"[WFS] error: {msg}", Qgis.Critical)
        except Exception:
            pass

        _log(f"[WFS] candidate failed: {uri}", Qgis.Warning)

    # niepowodzenie – skopiuj URI do schowka i pokaż komunikat
    try:
        QGuiApplication.clipboard().setText(last_uri or "")
    except Exception:
        pass

    message = "Nie udało się utworzyć warstwy WFS żadną kombinacją."
    if last_err:
        message += f"\n\nOstatni błąd providera:\n{last_err}"
    message += f"\n\nOstatni próbowany URI (skopiowano do schowka):\n\n{last_uri or '(brak)'}"

    _log(f"[WFS] NIE DODANO. Ostatni URI: {last_uri}", Qgis.Critical)
    QMessageBox.warning(None, "Dodawanie warstwy – WFS", message)

    return None, last_uri, None
