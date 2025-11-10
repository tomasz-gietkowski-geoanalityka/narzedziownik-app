"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
import html
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .http import _norm

# =========================
#  HTML → tabele i linki
# =========================

class TableGrabber(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._buf = []
        self._row = []
        self._curr_table = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._in_table = True
            self._curr_table = []
        elif t == "tr" and self._in_table:
            self._in_tr = True
            self._row = []
        elif t in ("td", "th") and self._in_tr:
            self._in_td = True
            self._buf = []

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data or "")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._in_td:
            self._row.append(_norm("".join(self._buf)))
            self._in_td = False
        elif t == "tr" and self._in_tr:
            if any(self._row):
                self._curr_table.append(self._row)
            self._in_tr = False
        elif t == "table" and self._in_table:
            if self._curr_table:
                self.tables.append(self._curr_table)
            self._in_table = False
            self._curr_table = []


class TableRowLinkGrabber(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._buf = []
        self._row_cells = []
        self._row_links = []
        self._curr_table = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._in_table = True
            self._curr_table = []
        elif t == "tr" and self._in_table:
            self._in_tr = True
            self._row_cells = []
            self._row_links = []
        elif t in ("td", "th") and self._in_tr:
            self._in_td = True
            self._buf = []
        elif t == "a" and self._in_tr and self._in_td:
            href = None
            for k, v in attrs:
                if k and k.lower() == "href" and v:
                    href = v
                    break
            if href:
                self._row_links.append(html.unescape(href).strip())

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data or "")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th") and self._in_td:
            self._row_cells.append(_norm("".join(self._buf)))
            self._in_td = False
        elif t == "tr" and self._in_tr:
            if any(self._row_cells):
                self._curr_table.append({"cells": self._row_cells, "links": self._row_links})
            self._in_tr = False
        elif t == "table" and self._in_table:
            if self._curr_table:
                self.tables.append(self._curr_table)
            self._in_table = False
            self._curr_table = []


def extract_organs(html_text: str):
    p = TableGrabber()
    p.feed(html_text)
    labels = ("organ zgłaszający", "organ prowadz")
    organs, seen = [], set()
    for tbl in p.tables:
        if not tbl:
            continue
        header = [c.casefold() for c in tbl[0]]
        idx = -1
        for i, h in enumerate(header):
            if any(lbl in h for lbl in labels):
                idx = i
                break
        if idx == -1:
            continue
        for row in tbl[1:]:
            if idx < len(row):
                name = _norm(html.unescape(row[idx]))
                if name and name not in seen:
                    seen.add(name)
                    organs.append(name)
    return organs


def classify_service_href(href: str):
    if not href or not href.lower().startswith(("http://", "https://")):
        return None
    href_l = href.lower()
    if re.search(r'wmts|/tile/|/tiles?/|/xyz', href_l):
        return None
    if "service=wms" in href_l or re.search(r'(^|[^\w])wms(/|$)', href_l):
        return "WMS"
    if "service=wfs" in href_l or re.search(r'(^|[^\w])wfs(/|$)', href_l):
        return "WFS"
    if re.search(r'(^|[^\w])ows(/|$)', href_l) or "getcapabilities" in href_l:
        return "AUTO"
    return None


def extract_datasets(html_text: str):
    p = TableRowLinkGrabber()
    p.feed(html_text)
    name_labels = ("nazwa zbioru danych",)
    datasets = {}
    for tbl in p.tables:
        if not tbl:
            continue
        header_cells = tbl[0]["cells"] if isinstance(tbl[0], dict) else tbl[0]
        idx_name = -1
        for i, h in enumerate([c.casefold() for c in header_cells]):
            if any(lbl in h for lbl in name_labels):
                idx_name = i
                break
        if idx_name == -1:
            continue
        for row in tbl[1:]:
            if not isinstance(row, dict):
                continue
            cells, links = row["cells"], row["links"]
            if idx_name >= len(cells):
                continue
            ds_name = _norm(html.unescape(cells[idx_name]))
            if not ds_name:
                continue
            bucket = datasets.setdefault(ds_name, {"WMS": set(), "WFS": set()})
            for href in links:
                kind = classify_service_href(href)
                if not kind:
                    continue
                if kind == "AUTO":
                    bucket["WMS"].add(href)
                    bucket["WFS"].add(href)
                else:
                    bucket[kind].add(href)
    return datasets

# =========================
#  WMS/WFS Capabilities
# =========================

def parse_wms_titles_names_and_crs(xml_bytes: bytes, href: str = None):
    """
    Zwraca:
      items: list[dict] z polami:
        - title, name, is_group, is_child, depth (int), path (list[str])
      crs: set[str] (np. 'EPSG:2180', 'EPSG:3857', …)
    """
    root = ET.fromstring(xml_bytes)
    nsstrip = lambda tag: tag.split("}", 1)[-1]

    def _layer_children(node):
        return [ch for ch in node if nsstrip(ch.tag) == "Layer"]

    def _get_text(node, tag):
        for ch in node:
            if nsstrip(ch.tag) == tag:
                return (ch.text or "").strip()
        return ""

    def _walk(node, out, depth=0, path=None):
        if path is None:
            path = []
        name = _get_text(node, "Name")
        title = _get_text(node, "Title")
        children = _layer_children(node)
        current_path = path + [title or name or "(bez nazwy)"]
        is_group = len(children) > 0
        is_child = depth > 0
        out.append({
            "title": title or name or "",
            "name": name or "",
            "is_group": is_group,
            "is_child": is_child,
            "depth": depth,
            "path": current_path
        })
        for ch in children:
            _walk(ch, out, depth + 1, current_path)

    # Root-y Layer (zwykle Capability/Layer)
    roots = root.findall(".//{*}Capability/{*}Layer") or root.findall(".//{*}Layer")
    # spec-case (np. webewid) – root to dziecko Layer
    if href and "webewid.pl" in (href or "").lower():
        r2 = root.findall(".//{*}Capability/{*}Layer/{*}Layer")
        if r2:
            roots = r2

    items = []
    for layer in roots:
        _walk(layer, items, 0, [])

    crs = set(
        el.text.strip().upper()
        for el in (root.findall(".//{*}SRS") + root.findall(".//{*}CRS"))
        if el is not None and el.text
    )

    seen = set()
    uniq = []
    for it in items:
        key = (it["title"], it["name"], it["depth"])
        if key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq, crs


def parse_wfs_titles_names_and_crs(xml_bytes: bytes):
    """
    Zwraca:
      pairs: list[ (title, name, is_group=False) ]
      crs: set[str]
    """
    ns = {
        'wfs': 'http://www.opengis.net/wfs',
        'wfs2': 'http://www.opengis.net/wfs/2.0',
        'ows': 'http://www.opengis.net/ows',
        'ows1': 'http://www.opengis.net/ows/1.1'
    }
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        root = ET.fromstring(xml_bytes.decode('utf-8', errors='ignore').encode('utf-8'))

    out_pairs = []
    crs = set()

    ft_paths = [
        ".//wfs:FeatureTypeList/wfs:FeatureType",
        ".//wfs2:FeatureTypeList/wfs2:FeatureType",
        ".//FeatureTypeList/FeatureType",
    ]
    feature_types = []
    for xp in ft_paths:
        feature_types.extend(root.findall(xp, ns))

    def _first(parent, paths):
        for xp in paths:
            el = parent.find(xp, ns)
            if el is not None and el.text:
                t = el.text.strip()
                if t:
                    return t
        return ""

    for ft in feature_types:
        name = _first(ft, ["./wfs:Name", "./wfs2:Name", "./Name", "./ows:Identifier", "./ows1:Identifier"])
        if not name:
            continue
        title = _first(ft, ["./wfs:Title", "./wfs2:Title", "./Title", "./ows:Title", "./ows1:Title"]) or name
        out_pairs.append((title, name, False))

        for xp in [
            "./wfs:DefaultSRS", "./wfs:OtherSRS", "./DefaultSRS", "./OtherSRS",
            "./wfs2:DefaultCRS", "./wfs2:OtherCRS", "./DefaultCRS", "./OtherCRS",
            "./ows:SupportedCRS", "./ows1:SupportedCRS"
        ]:
            for el in ft.findall(xp, ns):
                txt = (el.text or "").strip()
                if not txt:
                    continue
                for part in re.split(r"[\s,]+", txt):
                    part = part.strip()
                    if part:
                        crs.add(part.upper())

    if not crs:
        for xp in [
            ".//wfs:DefaultSRS", ".//wfs:OtherSRS", ".//wfs2:DefaultCRS", ".//wfs2:OtherCRS",
            ".//DefaultSRS", ".//OtherSRS", ".//DefaultCRS", ".//OtherCRS",
            ".//ows:SupportedCRS", ".//ows1:SupportedCRS"
        ]:
            for el in root.findall(xp, ns):
                txt = (el.text or "").strip()
                if not txt:
                    continue
                for part in re.split(r"[\s,]+", txt):
                    part = part.strip()
                    if part:
                        crs.add(part.upper())

    seen = set()
    uniq = []
    for t, n, _ in out_pairs:
        key = (t, n)
        if key not in seen:
            seen.add(key)
            uniq.append((t, n, False))
    return uniq, crs

# =========================
#  HELPERY DEBUG / UJEDN.
# =========================

def wms_items_debug_ascii(xml_bytes: bytes, href: str = None) -> str:
    """
    Debug: zwraca ASCII-drzewko z (poziom X) na podstawie parse_wms_titles_names_and_crs.
    Tylko do podglądu/logowania – nie używa się w logice UI.
    """
    items, _crs = parse_wms_titles_names_and_crs(xml_bytes, href=href)

    def _label(it):
        t = (it.get("title") or "").strip()
        n = (it.get("name") or "").strip()
        if t and n and t != n:
            return f"{t} ({n})"
        return t or n or "(bez nazwy)"

    lines = []
    # Uproszczone rysowanie wg depth (nie liczymy „ostatniego” – tu chodzi o poziomy)
    stack = []  # [(depth, prefix)]
    for it in items:
        d = int(it.get("depth", 0))
        while stack and stack[-1][0] >= d:
            stack.pop()
        prefix = ""
        if stack:
            prefix = stack[-1][1] + "│  "
        connector = "├─ "
        if d == 0 and not stack:
            lines.append(f"{_label(it)} (poziom {d})")
        else:
            lines.append(f"{prefix}{connector}{_label(it)} (poziom {d})")
        stack.append((d, prefix))
    return "\n".join(lines)


def wms_items_light(xml_bytes: bytes, href: str = None):
    """
    Uproszczony widok: [(title, name, depth), ...] – przydatne do testów.
    """
    items, _ = parse_wms_titles_names_and_crs(xml_bytes, href=href)
    out = []
    for it in items:
        out.append((it.get("title") or "", it.get("name") or "", int(it.get("depth", 0))))
    return out


def wfs_pairs_to_items(pairs):
    """
    Ujednolicenie formatu WFS do „itemów” jak WMS:
      {title, name, is_group, is_child, depth=0, path=[title_or_name]}
    """
    out = []
    for (t, n, is_group) in pairs:
        title = t or n or ""
        name = n or ""
        out.append({
            "title": title,
            "name": name,
            "is_group": bool(is_group),
            "is_child": False,
            "depth": 0,
            "path": [title or name or "(bez nazwy)"]
        })
    return out


__all__ = [
    # HTML
    "TableGrabber", "TableRowLinkGrabber", "extract_organs", "classify_service_href", "extract_datasets",
    # WMS/WFS
    "parse_wms_titles_names_and_crs", "parse_wfs_titles_names_and_crs",
    # Debug/Ujednolicenie
    "wms_items_debug_ascii", "wms_items_light", "wfs_pairs_to_items",
]
