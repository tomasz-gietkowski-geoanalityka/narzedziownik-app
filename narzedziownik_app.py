# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QObject, QTimer
import webbrowser
import os
import traceback

# Stała dla nagłówka w menu „Wtyczki”
MENU_TITLE = "&Narzędziownik APP"

class NarzedziownikAPP(QObject):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        # Referencje do GUI, żeby poprawnie sprzątać przy unload()
        self._menu_actions = []          # akcje dodane do menu „Wtyczki”
        self._toolbar = None             # QToolBar
        self._toolbutton = None          # QToolButton na pasku
        self._toolbutton_menu = None     # QMenu pod tą ikoną

    # ---------- helpers ----------
    def _icon(self, name: str) -> QIcon:
        p = os.path.join(self.plugin_dir, "resources", "icons", name)
        return QIcon(p) if os.path.exists(p) else QIcon()

    # ---------- QGIS lifecycle ----------
    def initGui(self):
        main = self.iface.mainWindow()

        # --- Akcje wspólne (użyte w menu Wtyczki i w menu pod ikoną) ---
        act_import_gml = QAction(self._icon("import_gml.svg"), "Importuj POG GML…", main)
        act_import_gml.setToolTip("Importuj POG GML do projektu…")
        act_import_gml.setIconVisibleInMenu(True)
        act_import_gml.triggered.connect(lambda: QTimer.singleShot(0, self._run_import_gml))

        act_save_temp = QAction(self._icon("save_temp.svg"), "Zapisz warstwy tymczasowe z wybranej grupy…", main)
        act_save_temp.setToolTip("Zapisz warstwy tymczasowe z wybranej grupy…")
        act_save_temp.setIconVisibleInMenu(True)
        act_save_temp.triggered.connect(lambda: QTimer.singleShot(0, self._run_save_temp))

        act_web = QAction(self._icon("geoanalityka_web.svg"), "Strona wtyczki na geoanalityka.pl", main)
        act_web.setToolTip("Strona wtyczki na geoanalityka.pl")
        act_web.setIconVisibleInMenu(True)
        act_web.triggered.connect(self._open_geoanalityka)

        # --- MENU „Wtyczki” ---
        self.iface.addPluginToMenu(MENU_TITLE, act_import_gml)
        self.iface.addPluginToMenu(MENU_TITLE, act_save_temp)
        self.iface.addPluginToMenu(MENU_TITLE, act_web)
        self._menu_actions = [act_import_gml, act_save_temp, act_web]

        # --- DEDYKOWANY PASEK NARZĘDZI z JEDNĄ IKONĄ i menu rozwijanym ---
        # Upewnij się, że masz ikonę: resources/icons/narzedziownik_app.svg
        self._toolbar = self.iface.addToolBar("Narzędziownik APP")
        self._toolbar.setObjectName("Narzędziownik APP")
        self._toolbar.setToolTip("Narzędziownik APP")

        self._toolbutton = QToolButton(self._toolbar)
        self._toolbutton.setIcon(self._icon("narzedziownik_app.svg"))
        self._toolbutton.setToolTip("Narzędziownik APP")
        # InstantPopup: klik od razu otwiera menu (bez „ostatniej akcji”)
        self._toolbutton.setPopupMode(QToolButton.InstantPopup)

        # Menu pod ikoną
        self._toolbutton_menu = QMenu(self._toolbutton)
        self._toolbutton_menu.setTitle("Narzędziownik APP")
        self._toolbutton_menu.addAction(act_import_gml)
        self._toolbutton_menu.addAction(act_save_temp)
        self._toolbutton_menu.addSeparator()
        self._toolbutton_menu.addAction(act_web)

        self._toolbutton.setMenu(self._toolbutton_menu)

        # Dodaj jeden widget (ikonę) na pasek
        self._toolbar.addWidget(self._toolbutton)

    def unload(self):
        # Sprzątanie: usuń wpisy z menu „Wtyczki”
        for action in self._menu_actions:
            try:
                self.iface.removePluginMenu(MENU_TITLE, action)
            except Exception:
                traceback.print_exc()
        self._menu_actions = []

        # Sprzątanie: usuń pasek i przycisk
        try:
            if self._toolbutton:
                self._toolbutton.deleteLater()
                self._toolbutton = None
                self._toolbutton_menu = None
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
            res = run_save_temp(self.iface, self.plugin_dir)

            if res is None:
                return

            saved = res.get("saved", []) if isinstance(res, dict) else []
            failed = res.get("failed", []) if isinstance(res, dict) else []
            outdir = res.get("output_dir", "") if isinstance(res, dict) else ""

            if not saved and not failed and not outdir:
                return

            if saved and not failed:
                msg = f"Zapisano {len(saved)} warstw do: {outdir}"
                bar.pushSuccess("Zapis warstw", msg)
            elif saved and failed:
                msg = (
                    f"Zapisano {len(saved)} warstw do: {outdir} | "
                    f"Nieudane: {', '.join(failed)}"
                )
                bar.pushWarning("Zapis warstw", msg)
            elif failed and not saved:
                msg = f"Nie udało się zapisać żadnej warstwy: {', '.join(failed)}"
                bar.pushCritical("Zapis warstw", msg)

        except Exception as e:
            bar.pushWarning("Zapis warstw – błąd", str(e))
            traceback.print_exc()

    # ---------- Link ----------
    def _open_geoanalityka(self):
        url = "https://geoanalityka.pl/wtyczka-geoanalityka/"
        webbrowser.open(url)
        self.iface.messageBar().pushInfo("Geoanalityka", f"Otworzono {url}")
