# -*- coding: utf-8 -*-
"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)
"""

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

        # Referencje do GUI
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

        # NOWA AKCJA: Utwórz szablony POG
        act_create_pog = QAction(
            self._icon("create_pog_tmp.svg"),
            "Utwórz szablony warstw POG…",
            main
        )
        act_create_pog.setToolTip("Tworzy zestaw szablonów APP POG z katalogu templates/wtyczkaapp2")
        act_create_pog.triggered.connect(lambda: QTimer.singleShot(0, self._run_create_pog))

        act_save_temp = QAction(self._icon("save_temp.svg"), "Zapisz warstwy tymczasowe z wybranej grupy…", main)
        act_save_temp.triggered.connect(lambda: QTimer.singleShot(0, self._run_save_temp))

        act_web = QAction(self._icon("github.svg"), "Przejdź do strony na GitHub…", main)
        act_web.triggered.connect(self._open_geoanalityka)

        # Dokumentacja
        act_docs = QAction(self._icon("doku.svg"), "Dokumentacja…", main)
        act_docs.setToolTip("Otwiera dokumentację wtyczki Narzędziownik APP")
        act_docs.triggered.connect(self._open_docs)

        # KST – przygotuj budynki
        act_kst = QAction(self._icon("kst.svg"), "Przygotuj budynki…", main)
        act_kst.triggered.connect(lambda: QTimer.singleShot(0, self._run_kst))

        # OUZ generator
        act_ouz = QAction(self._icon("create-ouz.svg"), "Stwórz OUZ…", main)
        act_ouz.triggered.connect(lambda: QTimer.singleShot(0, self._run_ouz_generator))

        # OUZ weryfikacja
        icon_verify = self._icon("verify-optimization.svg") or self._icon("create-ouz.svg")
        act_ouz_verify = QAction(icon_verify, "Weryfikuj optymalizację OUZ…", main)
        act_ouz_verify.triggered.connect(lambda: QTimer.singleShot(0, self._run_ouz_verify_optimization))

        # Scalanie
        act_merge_sel = QAction(self._icon("merge-selected.svg"), "Połącz zaznaczone i przenieś na warstwę w edycji", main)
        act_merge_sel.triggered.connect(lambda: QTimer.singleShot(0, self._run_merge_selected))

        # Recount
        act_recount = QAction(self._icon("recount.svg"), "Przelicz oznaczenie obiektu", main)
        act_recount.triggered.connect(lambda: QTimer.singleShot(0, self._run_recount))

        # EZiUDP
        icon_ezi = self._icon("eziudp-mpzp.svg") or self._icon("narzedziownik_app.svg")
        act_mpzp_eziudp = QAction(icon_ezi, "Dodaj warstwy z EZiUDP (WMS/WFS)…", main)
        act_mpzp_eziudp.triggered.connect(lambda: QTimer.singleShot(0, self._run_mpzp_eziudp))

        # --- MENU WTYCZKI ---
        plugins_menu = self.iface.pluginMenu()
        self._plugins_menu_root = QMenu(MENU_TITLE, plugins_menu)
        self._plugins_menu_root.setIcon(self._icon("narzedziownik_app.svg"))

        # Narzędzia edycji
        self._plugins_menu_edit = QMenu("Narzędzia edycji", self._plugins_menu_root)
        self._plugins_menu_edit.setIcon(self._icon("edit-tools.svg"))
        self._plugins_menu_edit.addAction(act_merge_sel)
        self._plugins_menu_edit.addAction(act_recount)

        # OUZ
        self._plugins_menu_ouz = QMenu("Obszar uzupełnienia zabudowy", self._plugins_menu_root)
        self._plugins_menu_ouz.setIcon(self._icon("create-ouz.svg"))
        self._plugins_menu_ouz.addAction(act_kst)
        self._plugins_menu_ouz.addAction(act_ouz)
        self._plugins_menu_ouz.addAction(act_ouz_verify)

        # Kolejność w menu głównym
        self._plugins_menu_root.addMenu(self._plugins_menu_edit)
        self._plugins_menu_root.addMenu(self._plugins_menu_ouz)
        self._plugins_menu_root.addSeparator()
        self._plugins_menu_root.addAction(act_import_gml)

        # NOWA POZYCJA tuż pod "Importuj POG GML…"
        self._plugins_menu_root.addAction(act_create_pog)

        self._plugins_menu_root.addAction(act_mpzp_eziudp)
        self._plugins_menu_root.addAction(act_save_temp)
        self._plugins_menu_root.addSeparator()
        self._plugins_menu_root.addAction(act_web)
        self._plugins_menu_root.addAction(act_docs)

        plugins_menu.addMenu(self._plugins_menu_root)

        # --- PASEK NARZĘDZI ---
        self._toolbar = self.iface.addToolBar("Narzędziownik APP")
        self._toolbar.setObjectName("Narzędziownik APP")

        # Główna ikona
        self._toolbutton = QToolButton(self._toolbar)
        self._toolbutton.setIcon(self._icon("narzedziownik_app.svg"))
        self._toolbutton.setPopupMode(QToolButton.InstantPopup)

        self._toolbutton_menu = QMenu(self._toolbutton)

        # Menu edycji
        menu_edit = self._toolbutton_menu.addMenu(self._icon("edit-tools.svg"), "Narzędzia edycji")
        menu_edit.addAction(act_merge_sel)
        menu_edit.addAction(act_recount)

        # OUZ
        menu_ouz = self._toolbutton_menu.addMenu(self._icon("create-ouz.svg"), "Obszar uzupełnienia zabudowy")
        menu_ouz.addAction(act_kst)
        menu_ouz.addAction(act_ouz)
        menu_ouz.addAction(act_ouz_verify)

        # POD GŁÓWNĄ IKONĄ — kolejność
        self._toolbutton_menu.addSeparator()
        self._toolbutton_menu.addAction(act_import_gml)

        # NOWE — TUŻ POD IMPORT GML
        self._toolbutton_menu.addAction(act_create_pog)

        self._toolbutton_menu.addAction(act_mpzp_eziudp)
        self._toolbutton_menu.addAction(act_save_temp)
        self._toolbutton_menu.addSeparator()
        self._toolbutton_menu.addAction(act_web)
        self._toolbutton_menu.addAction(act_docs)

        self._toolbutton.setMenu(self._toolbutton_menu)

        self._toolbar.addWidget(self._toolbutton)
        self._toolbar.addAction(act_merge_sel)

    def unload(self):
        try:
            if self._plugins_menu_root:
                self._plugins_menu_root.deleteLater()
        except Exception:
            traceback.print_exc()
        try:
            if self._toolbutton:
                self._toolbutton.deleteLater()
            if self._toolbar:
                self.iface.mainWindow().removeToolBar(self._toolbar)
                self._toolbar.deleteLater()
        except Exception:
            traceback.print_exc()

    # ---------- Features ----------
    def _run_import_gml(self):
        try:
            from .features.import_gml import run as run_import_gml
            run_import_gml(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_create_pog(self):
        try:
            from .features.create_template_pog import run as run_create_pog
            run_create_pog(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_save_temp(self):
        try:
            from .features.save_temp_layers import run as run_save_temp
            run_save_temp(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_kst(self):
        try:
            from .features.buildings_kst_processor import run as run_kst
            run_kst(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_ouz_generator(self):
        try:
            from .features.ouz_generator import run as run_ouz
            run_ouz(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_ouz_verify_optimization(self):
        try:
            from .features.ouz_verify_optimization import run as run_verify
            run_verify(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_merge_selected(self):
        try:
            from .features.merge_selected_to_edit_target import run as run_merge
            run_merge(self.iface, self.plugin_dir)
        except Exception:
            traceback.print_exc()

    def _run_recount(self):
        try:
            from .features.recount import run as run_recount
            run_recount(self.iface)
        except Exception:
            traceback.print_exc()

    def _run_mpzp_eziudp(self):
        try:
            from .features.eziudp import run as run_eziudp
            run_eziudp(self.iface.mainWindow())
        except Exception:
            traceback.print_exc()

    # ---------- Linki ----------
    def _open_geoanalityka(self):
        url = "https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik-app"
        webbrowser.open(url)

    def _open_docs(self):
        url = "https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/"
        webbrowser.open(url)
