"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
"""
Zapisuje warstwy tymczasowe (memory) z wybranej grupy do plików GeoPackage (.gpkg)
i przełącza ich źródło na GPKG. Nazwy tabel w GPKG są wymuszane na małe litery
poprzez opcję GDAL/OGR (LAYER_NAME). Komunikaty dotyczące nieudanego 
przełączenia źródła (setDataSource) są wyciszone, jeśli zapis na dysk się udał.
"""

from qgis.PyQt.QtWidgets import QFileDialog, QInputDialog
from qgis.core import QgsProject, QgsVectorLayer, QgsDataProvider
import os
import processing
import re 

# --- FUNKCJA POMOCNICZA DLA NAZW TABEL ---
def _to_gpkg_name(name: str) -> str:
    """Konwertuje nazwę warstwy na bezpieczną nazwę tabeli w GPKG (lowercase)"""
    s = (name or "").strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]+", "", s)
    if not s:
        s = "warstwa_temp"
    if s[0].isdigit():
        s = f"t_{s}"
    return s
# ------------------------------------------


def run(iface, plugin_dir):
    mw = iface.mainWindow()
    bar = iface.messageBar()
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    
    output_dir = ""
    saved, failed = [], []

    # 1) Grupy
    group_nodes = [ch for ch in root.children() if ch.nodeType() == 0]
    group_names = [g.name() for g in group_nodes]
    if not group_names:
        bar.pushCritical("Zapis warstw", "Projekt nie zawiera żadnych grup.")
        return {"saved": [], "failed": [], "output_dir": output_dir} 

    # 2) Wybór grupy 
    if len(group_names) == 1:
        selected_group_name = group_names[0]
    else:
        selected_group_name, ok = QInputDialog.getItem(
            mw, "Wybierz grupę",
            "Z której grupy chcesz zapisać warstwy tymczasowe?",
            group_names, 0, False
        )
        if not ok:
            bar.pushInfo("Zapis warstw", "Operacja anulowana.")
            return None 

    group = root.findGroup(selected_group_name)
    if not group:
        bar.pushCritical("Zapis warstw", f"Nie znaleziono grupy '{selected_group_name}'.")
        return {"saved": [], "failed": [], "output_dir": output_dir}

    # 3) Warstwy memory
    layers = [
        ch.layer() for ch in group.children()
        if hasattr(ch, "layer")
        and isinstance(ch.layer(), QgsVectorLayer)
        and (
            ch.layer().providerType() == "memory"
            or (ch.layer().source() or "").lower().startswith("memory:")
            or "&uid=" in (ch.layer().source() or "")
        )
    ]
    if not layers:
        bar.pushInfo("Zapis warstw", f"Grupa '{selected_group_name}' nie zawiera warstw tymczasowych.")
        return {"saved": [], "failed": []}

    # 4) Katalog zapisu
    dlg = QFileDialog(mw, "Wybierz katalog do zapisania warstw")
    dlg.setFileMode(QFileDialog.Directory)
    dlg.setOption(QFileDialog.ShowDirsOnly, True)
    dlg.setOption(QFileDialog.DontUseNativeDialog, True)
    if dlg.exec_():
        output_dir = dlg.selectedFiles()[0]
    else:
        bar.pushWarning("Zapis warstw", "Nie wybrano katalogu.")
        return None 

    if not os.access(output_dir, os.W_OK):
        bar.pushCritical("Zapis warstw", f"Katalog '{output_dir}' nie jest zapisywalny.")
        return {"saved": [], "failed": [], "output_dir": output_dir} 

    # 5) Zapis + przełączenie źródła
    for layer in layers:
        layer_name = layer.name()
        
        file_name = layer_name.replace(" ", "_") + ".gpkg"
        output_path = os.path.join(output_dir, file_name)
        
        table_name = _to_gpkg_name(layer_name) 

        style_mgr = layer.styleManager()
        current_style_name = style_mgr.currentStyle()
        style_xml = style_mgr.style(current_style_name)

        if layer.isEditable():
            layer.commitChanges()

        try:
            # Wymuszenie nazwy tabeli za pomocą opcji GDAL
            options_list = [f"LAYER_NAME={table_name}"]

            # Zapis do pliku
            result = processing.run("native:savefeatures", {
                'INPUT': layer, 
                'OUTPUT': output_path,
                'OPTIONS': options_list
            })
            
            ok_out = bool(result and 'OUTPUT' in result and os.path.exists(output_path))
            
            if not ok_out:
                failed.append(layer_name)
                continue

            # URI do tabeli w GPKG
            ds_uri = f"{output_path}|layername={table_name}"

            # Przełączenie źródła
            opts = QgsDataProvider.ProviderOptions()
            opts.transformContext = project.transformContext()
            
            if layer.setDataSource(ds_uri, layer.name(), "ogr", opts):
                # SUKCES PRZEŁĄCZENIA
                if layer.styleManager().style(layer.styleManager().currentStyle()) != style_xml:
                    style_mgr.addStyle("_tmp_", style_xml)
                    style_mgr.setCurrentStyle("_tmp_")
                    style_mgr.renameStyle("_tmp_", current_style_name)

                layer.reload()
                layer.triggerRepaint()
                saved.append(layer_name)
            else:
                # Porażka w setDataSource, ale sukces w zapisie. Uznajemy za sukces.
                saved.append(layer_name) 
                # WAŻNE: Wyciszamy ostrzeżenie.

        except Exception:
            failed.append(layer_name)

    # 6) Podsumowanie (logika w main_plugin.py)

    return {"saved": saved, "failed": failed, "output_dir": output_dir}