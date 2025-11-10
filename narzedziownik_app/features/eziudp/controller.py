"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
from .ui_organ import EziudpOrganDialog
from .ui_services import EziudpServicesDialog

def run(parent=None):
    last_query = None; last_organs = None
    while True:
        dlg1 = EziudpOrganDialog(parent, initial_query=last_query, initial_organs=last_organs)
        if dlg1.exec_() != EziudpOrganDialog.Accepted: break
        last_query = dlg1.current_query(); last_organs = dlg1.current_organs()
        organ = dlg1.selected_organ()
        if not organ: continue
        dlg2 = EziudpServicesDialog(organ, parent)
        went_back = {"flag": False}
        dlg2.go_back.connect(lambda: went_back.__setitem__("flag", True))
        dlg2.exec_()
        if not went_back["flag"]: break
