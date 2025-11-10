"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
import re
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QProgressBar, QMessageBox, QDialogButtonBox,
    QSizePolicy, QHeaderView, QCheckBox
)
from qgis.core import QgsProject, Qgis, QgsMessageLog

from .workers import ServicesWorker
from .add_layers import add_wms_layer, add_wfs_layer


def _build_tree_from_depth_list(parent_item: QTreeWidgetItem, items: list, format_label=None):
    """
    Buduje drzewo na podstawie listy elementów z polami:
    {title,name,is_group,is_child,depth,path}
    Kluczowe: budujemy po PATH, nie po samym 'depth', więc rodzic zawsze
    powstaje z path[:-1], a dziecko z path.
    """
    # mapa: tuple(path) -> QTreeWidgetItem
    nodes = {(): parent_item}

    # sortuj tak, by najpierw powstały rodzice (krótsze path), potem dzieci;
    # w obrębie tego samego poziomu — alfabetycznie po nazwie węzła (ostatni element path)
    def _key(it):
        p = it.get("path") or []
        last = (p[-1] or "") if p else ""
        return (len(p), tuple(p), last.casefold())

    for it in sorted(items, key=_key):
        path = it.get("path") or []
        title = it.get("title") or it.get("name") or ""
        name  = it.get("name") or ""
        is_group = bool(it.get("is_group", False))

        # rodzic = węzeł o ścieżce bez ostatniego elementu; jeśli go nie ma, przyjmij parent_item
        parent_key = tuple(path[:-1]) if path else ()
        parent_node = nodes.get(parent_key, parent_item)

        # label z ewentualnym formatowaniem (np. „(poziom X)”)
        label0 = format_label(it, title) if callable(format_label) else title

        node = QTreeWidgetItem([label0, name])

        # Stylizacja wg poziomu zagnieżdżenia


        # Stylizacja wg poziomu zagnieżdżenia
        depth = int(it.get("depth", 0))
        f0 = node.font(0)
        f1 = node.font(1)

        # domyślnie zwykła czcionka
        color = None

        if depth == 1:
            # poziom 1 – kursywa
            f0.setItalic(True)
            f1.setItalic(True)
        elif depth >= 2:
            # poziom 2+ – kursywa szara
            f0.setItalic(True)
            f1.setItalic(True)
            color = QColor(Qt.gray)

        # zastosuj styl
        node.setFont(0, f0)
        node.setFont(1, f1)

        if color:
            node.setForeground(0, color)
            node.setForeground(1, color)



        parent_node.addChild(node)

        # zapamiętaj węzeł pod pełną ścieżką
        nodes[tuple(path)] = node
        it["_qt_node"] = node



def _merge_wms_items_by_path(lists: list):
    """
    Scala listy WMS dla jednego URL, deduplikując po PATH.
    Nie sortujemy po 'depth', tylko po (len(path), path, label), żeby zawsze
    rodzice trafili przed dziećmi, a dzieci w poprawne miejsca.
    """
    seen = set()
    out = []
    for items in lists:
        for it in items:
            key = tuple(it.get("path") or [])
            if not key:
                # awaryjnie – traktuj pojedynczy węzeł bez path jak unikalny po tytule
                key = ((it.get("title") or it.get("name") or ""),)
            if key in seen:
                continue
            seen.add(key)
            out.append(it.copy())

    def _key(it):
        p = it.get("path") or []
        last = (p[-1] or "") if p else (it.get("title") or it.get("name") or "")
        return (len(p), tuple(p), last.casefold())

    out.sort(key=_key)
    return out



def _merge_wfs_pairs(lists: list):
    """
    Scala listy par WFS [(title, name, is_group), ...] dla jednego URL,
    deduplikując po kluczu (name, title). Zwraca listę jak wejście.
    """
    seen = set()
    out = []
    for pairs in lists:
        for (t, n, is_group) in pairs:
            key = (n or "", t or "")
            if key in seen:
                continue
            seen.add(key)
            out.append((t, n, is_group))
    # sortuj alfabetycznie po title (fallback po name)
    out.sort(key=lambda p: ((p[0] or p[1] or "").casefold(), (p[1] or "").casefold()))
    return out


class EziudpServicesDialog(QDialog):
    go_back = pyqtSignal()

    def __init__(self, organ_name: str, parent=None):
        super().__init__(parent)
        self.organ_name = organ_name
        self.setWindowTitle(f"EZiUDP – usługi dla: {organ_name}")
        self.setMinimumSize(860, 700)   # min: 860×700
        self.resize(860, 720)           # startowa wysokość ~700+
        self.setSizeGripEnabled(True)   # uchwyt do zmiany rozmiaru
        self._data = None
        self._summary = None

        v = QVBoxLayout(self)

        # Pasek statusu i „Wróć”
        top = QHBoxLayout()
        self.lbl_status = QLabel(f"Organ: {organ_name}")
        self.btn_back = QPushButton("Wróć do listy organów")
        self.btn_back.setToolTip("Zamknij to okno i wybierz inny organ")
        self.btn_back.clicked.connect(self._on_back)
        top.addWidget(self.lbl_status)
        top.addStretch(1)
        top.addWidget(self.btn_back)
        v.addLayout(top)

        # Progress
        self.prg = QProgressBar()
        self.prg.setRange(0, 100)
        self.prg.setValue(0)
        v.addWidget(self.prg)

        # Filtr
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Filtr warstw (Title/Name):"))
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("np. 'dzialki' lub 'budynki' …")
        self.btn_clear_filter = QPushButton("Wyczyść")
        frow.addWidget(self.ed_filter, 1)
        frow.addWidget(self.btn_clear_filter)
        v.addLayout(frow)

        # Debug depth
        self.chk_show_depth = QCheckBox("Pokaż poziom (debug)")
        v.addWidget(self.chk_show_depth)
        self.chk_show_depth.toggled.connect(lambda _: self._rerender())

        # Drzewo
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tytuł / Nazwa", "Adres / Name"])
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        v.addWidget(self.tree, 1)

        # Dodawanie wybranych
        self.btn_add_selected = QPushButton("Dodaj wybrane warstwy")
        self.btn_add_selected.setEnabled(False)
        self.btn_add_selected.clicked.connect(self._add_selected_layers)
        v.addWidget(self.btn_add_selected)

        # Zamknięcie
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        # Sygnalizacja
        self.ed_filter.textChanged.connect(self._apply_filter)
        self.btn_clear_filter.clicked.connect(lambda: self.ed_filter.setText(""))
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemSelectionChanged.connect(self._update_add_button_state)

        # Start
        self._fetch()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        total = max(200, self.tree.viewport().width())
        self.tree.setColumnWidth(0, int(total * 0.5))
        self.tree.setColumnWidth(1, int(total * 0.5))

    def _on_back(self):
        self.go_back.emit()
        self.reject()

    def _rerender(self):
        # przerysowanie z aktualnych danych (np. po przełączeniu „Pokaż poziom”)
        if getattr(self, "_data", None) is not None:
            self._on_result(self._data)

    def _fetch(self):
        self.tree.clear()
        self.lbl_status.setText("Pobieram usługi…")
        self.prg.setValue(0)
        self.worker = ServicesWorker(self.organ_name, parent=self)
        self.worker.progress.connect(self.prg.setValue)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.result.connect(self._on_result)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_error(self, msg: str):
        QMessageBox.critical(self, "Błąd", msg)
        self.lbl_status.setText("Błąd.")
        self.prg.setValue(0)

    # ===== agregacja (do trybu „scalonego”) =====
    def _summarize_services(self, data: dict):
        out = {"WMS": {}, "WFS": {}}
        for kind in ("WMS", "WFS"):
            urls = set()
            pairs_by_url = {}
            crs_by_url = {}
            for _ds_name, buckets in data.items():
                for url in buckets.get(kind, []):
                    urls.add(url)
                    if kind == "WMS":
                        items = buckets.get("WMS_LAYERS", {}).get(url, [])
                        pairs_by_url.setdefault(url, [])
                        pairs_by_url[url].extend(items)
                    else:
                        pairs = buckets.get("WFS_LAYERS", {}).get(url, [])
                        pairs_by_url.setdefault(url, [])
                        pairs_by_url[url].extend(pairs)
                    crs_set = set(buckets.get(f"{kind}_CRS", {}).get(url, []))
                    crs_by_url.setdefault(url, set()).update(c for c in crs_set if c)
            out[kind] = {
                "urls": urls,
                "pairs_by_url": pairs_by_url,
                "crs_by_url": crs_by_url,
            }
        return out

    def _normalize_codes(self, codes):
        out = set()
        for c in (codes or []):
            cu = (c or "").upper().strip()
            if not cu:
                continue
            m = re.search(r"EPSG[:/]{1,2}(\d+)$", cu)
            out.add(f"EPSG:{m.group(1)}" if m else cu)
        return out

    def _pick_best_crs(self, kind: str, url: str, ds):
        fallback = "EPSG:2180"
        try:
            project_crs = (QgsProject.instance().crs().authid() or "").upper()
            supported = set()
            if ds:
                if self._data and ds in self._data:
                    if kind == "WMS":
                        supported = set((self._data[ds].get("WMS_CRS", {}).get(url, [])) or [])
                    elif kind == "WFS":
                        supported = set((self._data[ds].get("WFS_CRS", {}).get(url, [])) or [])
            else:
                if self._summary and kind in self._summary:
                    supported = set(self._summary[kind].get("crs_by_url", {}).get(url, []) or [])
            supported_norm = self._normalize_codes(supported)
            if project_crs and project_crs in supported_norm:
                return project_crs
            return fallback
        except Exception:
            return fallback

    # ===== render =====
    def _on_result(self, data: dict):
        self._data = data
        self.tree.clear()

        if not data:
            self.lbl_status.setText("Brak usług WMS/WFS dla tego organu.")
            self.prg.setValue(100)
            return

        bold_font = QFont()
        bold_font.setBold(True)

        # Podsumowanie (używane m.in. do trybu „scalonego WMS/WFS”)
        summary = self._summarize_services(data)
        self._summary = summary

        unique_wms_urls = summary["WMS"]["urls"]
        unique_wfs_urls = summary["WFS"]["urls"]
        use_flat_wms = (len(unique_wms_urls) == 1)
        use_flat_wfs = (len(unique_wfs_urls) == 1)

        # funkcja formatująca etykietę (debug)
        fmt = (lambda it, t: f"{t} (poziom {int(it.get('depth', 0))})") if self.chk_show_depth.isChecked() else (lambda it, t: t)

        # === SCALONY WMS (jeden wspólny adres dla wszystkich zbiorów) ===
        if use_flat_wms and unique_wms_urls:
            wms_url = next(iter(unique_wms_urls))
            node_wms = QTreeWidgetItem(["Usługa przeglądania (WMS)", wms_url])
            node_wms.setData(0, Qt.UserRole, {"kind": "WMS_GROUP", "url": wms_url, "ds": None})
            node_wms.setFont(0, bold_font)
            self.tree.addTopLevelItem(node_wms)

            # zbierz wszystkie listy items dla tego URL i zmerguj po path
            lists = []
            for ds_name, buckets in data.items():
                items = buckets.get("WMS_LAYERS", {}).get(wms_url, [])
                if items:
                    with_ds = []
                    for it in items:
                        j = it.copy()
                        j["_ds"] = ds_name
                        j["_url"] = wms_url
                        with_ds.append(j)
                    lists.append(with_ds)
            merged = _merge_wms_items_by_path(lists)

            # zbuduj drzewo z formatowaniem
            _build_tree_from_depth_list(node_wms, merged, format_label=fmt)

            # meta (kind,url,name,title) dla liści (name != "")
            def set_meta_rec(node: QTreeWidgetItem):
                for i in range(node.childCount()):
                    ch = node.child(i)
                    title = ch.text(0)
                    name = ch.text(1)
                    if name:
                        ch.setData(0, Qt.UserRole, {
                            "kind": "WMS",
                            "url": wms_url,
                            "name": name,
                            "title": title,
                            "ds": None
                        })
                    set_meta_rec(ch)
            set_meta_rec(node_wms)

        # === SCALONY WFS (jeden wspólny adres dla wszystkich zbiorów) ===
        if use_flat_wfs and unique_wfs_urls:
            wfs_url = next(iter(unique_wfs_urls))
            node_wfs = QTreeWidgetItem(["Usługa pobierania (WFS)", wfs_url])
            node_wfs.setData(0, Qt.UserRole, {"kind": "WFS_GROUP", "url": wfs_url, "ds": None})
            node_wfs.setFont(0, bold_font)
            self.tree.addTopLevelItem(node_wfs)

            # zbierz wszystkie pary dla tego URL i zmerguj po (name,title)
            lists = []
            for ds_name, buckets in data.items():
                pairs = buckets.get("WFS_LAYERS", {}).get(wfs_url, [])
                if pairs:
                    lists.append(pairs)
            merged_pairs = _merge_wfs_pairs(lists)

            # wstaw elementy (WFS jest zwykle płaski – depth 0)
            for (title, name, is_group) in merged_pairs:
                label0 = (f"{(title or name)} (poziom 0)") if self.chk_show_depth.isChecked() else (title or name)
                it = QTreeWidgetItem([label0, name])
                it.setData(0, Qt.UserRole, {
                    "kind": "WFS",
                    "url": wfs_url,
                    "name": name,
                    "title": title or name,
                    "ds": None
                })
                if is_group:
                    f0 = it.font(0); f0.setItalic(True); it.setFont(0, f0)
                    f1 = it.font(1); f1.setItalic(True); it.setFont(1, f1)
                node_wfs.addChild(it)

            if not merged_pairs:
                node_wfs.addChild(QTreeWidgetItem(["(brak typów lub błąd parsowania)", ""]))

        # === WĘZŁY ZBIORÓW ===
        for dataset_title in sorted(data.keys(), key=lambda s: s.casefold()):
            ds_has_wms = bool(data[dataset_title].get("WMS"))
            ds_has_wfs = bool(data[dataset_title].get("WFS"))

            # Jeśli oba są scalone, a zbiór nie wnosi nic więcej → pominąć pusty zbiór
            if use_flat_wms and use_flat_wfs:
                # zostaw zbiory, które mają np. różne adresy/sekcje (edge-case), lub gdy chcesz je pokazać jako „etykiety”
                # Minimalny wariant: pokaż tylko, gdy ma choć jeden niescalony typ (tu: brak takich) → pomiń
                continue

            # Jeśli scalony jest tylko WMS, pokaż zbiory mające WFS (jak dotąd)
            if use_flat_wms and not ds_has_wfs:
                continue

            node_dataset = QTreeWidgetItem([dataset_title, ""])
            node_dataset.setFirstColumnSpanned(True)
            node_dataset.setFlags(node_dataset.flags() | Qt.ItemIsTristate | Qt.ItemIsSelectable)
            node_dataset.setFont(0, bold_font)
            self.tree.addTopLevelItem(node_dataset)

            # --- WMS pod zbiorem (tylko gdy NIE ma trybu „scalonego” WMS) ---
            if not use_flat_wms and ds_has_wms:
                for url in data[dataset_title].get("WMS", []):
                    wms_node = QTreeWidgetItem(["Usługa przeglądania (WMS)", url])
                    wms_node.setData(0, Qt.UserRole, {"kind": "WMS_GROUP", "url": url, "ds": dataset_title})
                    node_dataset.addChild(wms_node)

                    items = data[dataset_title].get("WMS_LAYERS", {}).get(url, [])
                    _build_tree_from_depth_list(wms_node, items, format_label=fmt)

                    # meta na liściach
                    def set_meta_rec2(node: QTreeWidgetItem, _url=url, _ds=dataset_title):
                        for i in range(node.childCount()):
                            ch = node.child(i)
                            title = ch.text(0)
                            name = ch.text(1)
                            if name:
                                ch.setData(0, Qt.UserRole, {
                                    "kind": "WMS",
                                    "url": _url,
                                    "name": name,
                                    "title": title,
                                    "ds": _ds
                                })
                            set_meta_rec2(ch, _url, _ds)
                    set_meta_rec2(wms_node)

            # --- WFS pod zbiorem (zwykle płasko); pomiń, gdy scalony WFS ---
            if not use_flat_wfs and ds_has_wfs:
                for url in data[dataset_title].get("WFS", []):
                    wfs_node = QTreeWidgetItem(["Usługa pobierania (WFS)", url])
                    wfs_node.setData(0, Qt.UserRole, {"kind": "WFS_GROUP", "url": url, "ds": dataset_title})
                    node_dataset.addChild(wfs_node)

                    pairs = data[dataset_title].get("WFS_LAYERS", {}).get(url, [])
                    for (title, name, is_group) in pairs:
                        label0 = (f"{(title or name)} (poziom 0)") if self.chk_show_depth.isChecked() else (title or name)
                        it = QTreeWidgetItem([label0, name])
                        it.setData(0, Qt.UserRole, {
                            "kind": "WFS",
                            "url": url,
                            "name": name,
                            "title": title or name,
                            "ds": dataset_title
                        })
                        if is_group:
                            f0 = it.font(0); f0.setItalic(True); it.setFont(0, f0)
                            f1 = it.font(1); f1.setItalic(True); it.setFont(1, f1)
                        wfs_node.addChild(it)
                    if not pairs:
                        wfs_node.addChild(QTreeWidgetItem(["(brak typów lub błąd parsowania)", ""]))

        self.tree.expandAll()
        self.tree.expandAll()
        self._update_add_button_state()
        self.tree.setColumnWidth(0, int(self.tree.viewport().width() * 0.5))
        self.tree.setColumnWidth(1, int(self.tree.viewport().width() * 0.5))
        self.lbl_status.setText("Gotowe.")
        self.prg.setValue(100)
        self._update_add_button_state()

    # ===== Filtrowanie =====
    def _apply_filter(self, text: str):
        q = (text or "").strip().casefold()

        def match_item(it: QTreeWidgetItem) -> bool:
            return (q in (it.text(0) or "").casefold()) or (q in (it.text(1) or "").casefold())

        def filter_node(node: QTreeWidgetItem) -> bool:
            if node.childCount() == 0:
                vis = True if not q else match_item(node)
                node.setHidden(not vis)
                return vis
            any_visible = False
            for i in range(node.childCount()):
                if filter_node(node.child(i)):
                    any_visible = True
            node.setHidden(not any_visible)
            return any_visible

        for i in range(self.tree.topLevelItemCount()):
            filter_node(self.tree.topLevelItem(i))
        self._update_add_button_state()

    # ===== Multi-select: aktywność przycisku =====
    def _update_add_button_state(self):
        selected_layer_items = 0
        for it in self.tree.selectedItems():
            meta = it.data(0, Qt.UserRole)
            if isinstance(meta, dict) and meta.get("kind") in ("WMS", "WFS"):
                selected_layer_items += 1
        self.btn_add_selected.setEnabled(selected_layer_items > 0)

    # ===== Dwuklik → 1 warstwa =====
    def _on_item_double_clicked(self, item: QTreeWidgetItem, col: int):
        meta = item.data(0, Qt.UserRole)
        if not isinstance(meta, dict):
            return
        kind = meta.get("kind")
        url = meta.get("url")
        name = meta.get("name")
        title = meta.get("title") or (item.text(0) or name)
        ds = meta.get("ds")
        if not (kind in ("WMS", "WFS") and url and name):
            return
        try:
            tn = (name or "").strip()
            if not tn:
                QMessageBox.warning(self, "Dodawanie warstwy", "Brak nazwy warstwy/typu – pomijam.")
                return
            chosen_crs = self._pick_best_crs(kind, url, ds)
            if kind == "WMS":
                layer, used_uri, used_crs = add_wms_layer(
                    href=url, layer_name=tn, title=title or tn,
                    preferred_crs=chosen_crs, group_path=["EZiUDP", "WMS"]
                )
                if layer is None:
                    QMessageBox.warning(
                        self, "Dodawanie warstwy – WMS",
                        f"Nie udało się utworzyć warstwy „{title or tn}”. Szczegóły w Dzienniku QGIS."
                    )
                    return
                self.lbl_status.setText(f"✅ Dodano WMS: {title or tn} (CRS: {used_crs or chosen_crs}) → EZiUDP/WMS")
            else:
                layer, used_uri, used_crs = add_wfs_layer(
                    href=url, typename=tn, title=title or tn,
                    preferred_crs=chosen_crs, group_path=["EZiUDP", "WFS"]
                )
                if layer is None:
                    QMessageBox.warning(
                        self, "Dodawanie warstwy – WFS",
                        f"Nie udało się utworzyć warstwy „{title or tn}”. Szczegóły w Dzienniku QGIS."
                    )
                    return
                self.lbl_status.setText(f"✅ Dodano WFS: {title or tn} (CRS: {used_crs or chosen_crs}) → EZiUDP/WFS")
        except Exception as e:
            QgsMessageLog.logMessage(str(e), "EZiUDP", level=Qgis.Critical)
            QMessageBox.critical(self, "Błąd dodawania warstwy", str(e))

    # ===== Klik „Dodaj wybrane warstwy” =====
    def _add_selected_layers(self):
        items = self._collect_selected_layer_items()
        if not items:
            self.lbl_status.setText("ℹ️ Nie wybrano żadnych warstw.")
            return
        errors = []
        added = 0
        for it in items:
            meta = it.data(0, Qt.UserRole) or {}
            kind = meta.get("kind")
            url = meta.get("url")
            name = meta.get("name")
            title = meta.get("title") or (it.text(0) or name)
            ds = meta.get("ds")
            if not (kind in ("WMS", "WFS") and url and name):
                continue
            try:
                tn = (name or "").strip()
                if not tn:
                    errors.append(f"{title or name}: brak nazwy warstwy/typu")
                    continue
                chosen_crs = self._pick_best_crs(kind, url, ds)
                if kind == "WMS":
                    layer, used_uri, used_crs = add_wms_layer(
                        href=url, layer_name=tn, title=title or tn,
                        preferred_crs=chosen_crs, group_path=["EZiUDP", "WMS"]
                    )
                else:
                    layer, used_uri, used_crs = add_wfs_layer(
                        href=url, typename=tn, title=title or tn,
                        preferred_crs=chosen_crs, group_path=["EZiUDP", "WFS"]
                    )
                if layer is None:
                    errors.append(f"{title or tn}: nie udało się dodać (szczegóły w Dzienniku QGIS)")
                else:
                    added += 1
            except Exception as e:
                errors.append(f"{title or name}: {e}")
        if added and not errors:
            self.lbl_status.setText(f"✅ Dodano {added} warstw(y).")
        elif added and errors:
            self.lbl_status.setText(f"⚠️ Dodano {added} warstw(y), {len(errors)} z błędami.")
            QMessageBox.warning(self, "Błędy podczas dodawania", "• " + "\n• ".join(errors))
        else:
            QMessageBox.warning(self, "Nie dodano żadnej warstwy", "• " + "\n• ".join(errors))

    def _collect_selected_layer_items(self):
        def iter_descendant_layers(node):
            out = []
            for i in range(node.childCount()):
                ch = node.child(i)
                meta = ch.data(0, Qt.UserRole)
                if isinstance(meta, dict) and meta.get("kind") in ("WMS", "WFS") and meta.get("name"):
                    out.append(ch)
                out.extend(iter_descendant_layers(ch))
            return out

        selected = self.tree.selectedItems()
        if not selected:
            return []
        result = []
        seen = set()
        for it in selected:
            meta = it.data(0, Qt.UserRole)
            if isinstance(meta, dict) and meta.get("kind") in ("WMS", "WFS") and meta.get("name"):
                key = (meta.get("kind"), meta.get("url"), meta.get("name"))
                if key not in seen:
                    seen.add(key)
                    result.append(it)
            else:
                for ch in iter_descendant_layers(it):
                    m = ch.data(0, Qt.UserRole) or {}
                    key = (m.get("kind"), m.get("url"), m.get("name"))
                    if key not in seen:
                        seen.add(key)
                        result.append(ch)
        return result
