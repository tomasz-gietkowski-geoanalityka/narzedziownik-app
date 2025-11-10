"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""
# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QObject, QTimer
import webbrowser
import os
import traceback

# Tytuł głównego menu w „Wtyczki”
MENU_TITLE = "&Narzędziownik APP"


class NarzedziownikAPP(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        # Referencje do GUI, żeby poprawnie sprzątać przy unload()
        self._toolbar = None
        self._toolbutton = None
        self._toolbutton_menu = None
        self._toolbutton_menu_ouz = None
        self._plugins_menu_root = None
        self._plugins_menu_ouz = None
        self._plugins_menu_edit = None

    # ---------- helpers ----------
    def _icon(self, name: str) -> QIcon:
        p = os.path.join(self.plugin_dir, "resources", "icons", name)
        return QIcon(p) if os.path.exists(p) else QIcon()

    # ---------- QGIS lifecycle ----------
    def initGui(self):
        main = self.iface.mainWindow()

        # --- Akcje wspólne ---
        act_import_gml = QAction(self._icon("import_gml.svg"), "Importuj POG GML…", main)
        act_import_gml.triggered.connect(lambda: QTimer.singleShot(0, self._run_import_gml))

        act_save_temp = QAction(self._icon("save_temp.svg"), "Zapisz warstwy tymczasowe z wybranej grupy…", main)
        act_save_temp.triggered.connect(lambda: QTimer.singleShot(0, self._run_save_temp))

        act_web = QAction(self._icon("github.svg"), "Przejdź do strony na GitHub…", main)
        act_web.triggered.connect(self._open_geoanalityka)

        # 🔹 Nowa akcja: Dokumentacja
        act_docs = QAction(self._icon("doku.svg"), "Dokumentacja…", main)
        act_docs.setToolTip("Otwiera dokumentację wtyczki Narzędziownik APP")
        act_docs.triggered.connect(self._open_docs)

        # KST – przygotuj budynki
        act_kst = QAction(self._icon("kst.svg"), "Przygotuj budynki…", main)
        act_kst.triggered.connect(lambda: QTimer.singleShot(0, self._run_kst))

        # OUZ Generator
        act_ouz = QAction(self._icon("create-ouz.svg"), "Stwórz OUZ…", main)
        act_ouz.triggered.connect(lambda: QTimer.singleShot(0, self._run_ouz_generator))

        # Weryfikacja optymalizacji OUZ
        icon_verify = self._icon("verify-optimization.svg") or self._icon("create-ouz.svg")
        act_ouz_verify = QAction(icon_verify, "Weryfikuj optymalizację OUZ…", main)
        act_ouz_verify.setToolTip("Uruchamia procedurę kontroli/raportu poprawności i optymalizacji OUZ")
        act_ouz_verify.triggered.connect(lambda: QTimer.singleShot(0, self._run_ouz_verify_optimization))

        # Scalanie – narzędzie edycji
        act_merge_sel = QAction(self._icon("merge-selected.svg"), "Połącz zaznaczone i przenieś na warstwę w edycji", main)
        act_merge_sel.setToolTip("Łączy zaznaczone na wielu warstwach obiekty i przenosi na warstwę w edycji")
        act_merge_sel.triggered.connect(lambda: QTimer.singleShot(0, self._run_merge_selected))

        # EZiUDP – przegląd i dodawanie MPZP (pojedyncza akcja, bez podmenu)
        icon_ezi = self._icon("eziudp-mpzp.svg") or self._icon("narzedziownik_app.svg")
        act_mpzp_eziudp = QAction(icon_ezi, "Dodaj warstwy z EZiUDP (WMS/WFS)…", main)
        act_mpzp_eziudp.setToolTip("Wyszukaj w EZiUDP i przeglądaj/dodawaj WMS/WFS (np. MPZP)")
        act_mpzp_eziudp.triggered.connect(lambda: QTimer.singleShot(0, self._run_mpzp_eziudp))

        # --- MENU WTYCZKI ---
        plugins_menu = self.iface.pluginMenu()
        self._plugins_menu_root = QMenu(MENU_TITLE, plugins_menu)
        self._plugins_menu_root.setIcon(self._icon("narzedziownik_app.svg"))

        # Narzędzia edycji
        self._plugins_menu_edit = QMenu("Narzędzia edycji", self._plugins_menu_root)
        self._plugins_menu_edit.setIcon(self._icon("edit-tools.svg"))
        self._plugins_menu_edit.addAction(act_merge_sel)

        # OUZ
        self._plugins_menu_ouz = QMenu("Obszar uzupełnienia zabudowy", self._plugins_menu_root)
        self._plugins_menu_ouz.setIcon(self._icon("create-ouz.svg"))
        self._plugins_menu_ouz.addAction(act_kst)
        self._plugins_menu_ouz.addAction(act_ouz)
        self._plugins_menu_ouz.addAction(act_ouz_verify)

        # Kolejność w menu głównym:
        self._plugins_menu_root.addMenu(self._plugins_menu_edit)
        self._plugins_menu_root.addMenu(self._plugins_menu_ouz)
        self._plugins_menu_root.addSeparator()
        self._plugins_menu_root.addAction(act_import_gml)
        self._plugins_menu_root.addAction(act_mpzp_eziudp)  # ← bez podmenu, zaraz pod Importuj POG GML…
        self._plugins_menu_root.addAction(act_save_temp)
        self._plugins_menu_root.addSeparator()
        self._plugins_menu_root.addAction(act_web)
        self._plugins_menu_root.addAction(act_docs)  # ← NOWE: Dokumentacja na końcu

        plugins_menu.addMenu(self._plugins_menu_root)

        # --- PASEK NARZĘDZI ---
        self._toolbar = self.iface.addToolBar("Narzędziownik APP")
        self._toolbar.setObjectName("Narzędziownik APP")
        self._toolbar.setToolTip("Narzędziownik APP")

        # 1) Główna ikona (po lewej) – rozwijane menu
        self._toolbutton = QToolButton(self._toolbar)
        self._toolbutton.setIcon(self._icon("narzedziownik_app.svg"))
        self._toolbutton.setToolTip("Narzędziownik APP")
        self._toolbutton.setPopupMode(QToolButton.InstantPopup)

        self._toolbutton_menu = QMenu(self._toolbutton)
        self._toolbutton_menu.setTitle("Narzędziownik APP")

        # Najpierw menu edycji
        toolbutton_menu_edit = self._toolbutton_menu.addMenu(self._icon("edit-tools.svg"), "Narzędzia edycji")
        toolbutton_menu_edit.addAction(act_merge_sel)

        # OUZ
        self._toolbutton_menu_ouz = self._toolbutton_menu.addMenu(self._icon("create-ouz.svg"), "Obszar uzupełnienia zabudowy")
        self._toolbutton_menu_ouz.addAction(act_kst)
        self._toolbutton_menu_ouz.addAction(act_ouz)
        self._toolbutton_menu_ouz.addAction(act_ouz_verify)

        # Kolejność pod główną ikoną:
        self._toolbutton_menu.addSeparator()
        self._toolbutton_menu.addAction(act_import_gml)
        self._toolbutton_menu.addAction(act_mpzp_eziudp)   # ← bez podmenu, tuż pod Import GML
        self._toolbutton_menu.addAction(act_save_temp)
        self._toolbutton_menu.addSeparator()
        self._toolbutton_menu.addAction(act_web)
        self._toolbutton_menu.addAction(act_docs)  # ← NOWE: Dokumentacja na końcu

        self._toolbutton.setMenu(self._toolbutton_menu)

        # 🔸 dodaj główny przycisk najpierw
        self._toolbar.addWidget(self._toolbutton)
        # 🔸 teraz po prawej od niego ikona scalania
        self._toolbar.addAction(act_merge_sel)
        # (bez osobnej ikony EZiUDP na pasku)

    def unload(self):
        try:
            if self._plugins_menu_root:
                self._plugins_menu_root.deleteLater()
                self._plugins_menu_root = None
                self._plugins_menu_ouz = None
                self._plugins_menu_edit = None
        except Exception:
            traceback.print_exc()
        try:
            if self._toolbutton:
                self._toolbutton.deleteLater()
                self._toolbutton = None
                self._toolbutton_menu = None
                self._toolbutton_menu_ouz = None
            if self._toolbar:
                self.iface.mainWindow().removeToolBar(self._toolbar)
                self._toolbar.deleteLater()
                self._toolbar = None
        except Exception:
            traceback.print_exc()

    # ---------- Features ----------
    def _run_import_gml(self):
        bar = self.iface.messageBar()
        try:
            from .features.import_gml import run as run_import_gml
            run_import_gml(self.iface, self.plugin_dir)
            bar.pushSuccess("Import GML", "Zakończono import.")
        except Exception as e:
            bar.pushWarning("Import GML – błąd", str(e))
            traceback.print_exc()

    def _run_save_temp(self):
        bar = self.iface.messageBar()
        try:
            from .features.save_temp_layers import run as run_save_temp
            run_save_temp(self.iface, self.plugin_dir)
        except Exception as e:
            bar.pushWarning("Zapis warstw – błąd", str(e))
            traceback.print_exc()

    def _run_kst(self):
        bar = self.iface.messageBar()
        try:
            from .features.buildings_kst_processor import run as run_kst
            run_kst(self.iface, self.plugin_dir)
        except Exception as e:
            bar.pushWarning("KST – błąd", str(e))
            traceback.print_exc()

    def _run_ouz_generator(self):
        bar = self.iface.messageBar()
        try:
            from .features.ouz_generator import run as run_ouz
            run_ouz(self.iface, self.plugin_dir)
        except Exception as e:
            bar.pushWarning("OUZ Generator – błąd", str(e))
            traceback.print_exc()

    def _run_ouz_verify_optimization(self):
        bar = self.iface.messageBar()
        try:
            from .features.ouz_verify_optimization import run as run_verify
            run_verify(self.iface, self.plugin_dir)
        except Exception as e:
            bar.pushWarning("Weryfikacja OUZ – błąd", str(e))
            traceback.print_exc()

    def _run_merge_selected(self):
        bar = self.iface.messageBar()
        try:
            from .features.merge_selected_to_edit_target import run as run_merge
            run_merge(self.iface, self.plugin_dir)
        except Exception as e:
            bar.pushCritical("Scalanie do edycji – błąd", str(e))
            traceback.print_exc()

    # EZiUDP → przegląd usług / dodawanie MPZP
    def _run_mpzp_eziudp(self):
        bar = self.iface.messageBar()
        try:
            # Uwaga: to jest okno dialogowe, które wymaga parenta = mainWindow()
            from .features.eziudp import run as run_eziudp
            run_eziudp(self.iface.mainWindow())
            bar.pushInfo("EZiUDP", "Zakończono przegląd usług EZiUDP.")
        except Exception as e:
            bar.pushWarning("EZiUDP – błąd", str(e))
            traceback.print_exc()

    # ---------- Linki ----------
    def _open_geoanalityka(self):
        url = "https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik-app"
        webbrowser.open(url)
        self.iface.messageBar().pushInfo("Geoanalityka", f"Otworzono {url}")

    def _open_docs(self):
        url = "https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/"
        webbrowser.open(url)
        self.iface.messageBar().pushInfo("Dokumentacja", f"Otworzono {url}")