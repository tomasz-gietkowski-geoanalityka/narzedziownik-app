# -*- coding: utf-8 -*-
import os, uuid, tempfile, xml.etree.ElementTree as ET
from pathlib import Path

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFields, QgsField, QgsFeature, QgsWkbTypes
)

# ====== KONFIG ======
GROUP_NAME = "Plan Ogólny Gminy"

SIMPLE_LAYERS = [
    "AktPlanowaniaPrzestrzennego",
    "ObszarUzupelnieniaZabudowy",
    "ObszarZabudowySrodmiejskiej",
]

OUT_FIELDS = ("profil_podstawowy", "profil_dodatkowy")

# Wszystkie style z plików w folderze styles/
STYLE_FILES = {
    "AktPlanowaniaPrzestrzennego": "styl-AktPlanowaniaPrzestrzennego.qml",
    "ObszarZabudowySrodmiejskiej": "styl-ObszarZabudowySrodmiejskiej.qml",
    "ObszarUzupelnieniaZabudowy":  "styl-ObszarUzupelnieniaZabudowy.qml",  
    "StrefaPlanistyczna":          "styl-StrefaPlanistyczna.qml",
}

# ====== NARZĘDZIA ======
def localname(tag: str) -> str:
    return tag.split('}', 1)[1] if '}' in tag else tag

def get_attr_local(attrs, wanted_local):
    for k, v in attrs.items():
        if localname(k) == wanted_local:
            return v
    return None

def pick_strefa_id_field(layer):
    preferred = ["gml_id","gmlid","@gml_id","localId","local_id","id","ID"]
    names = layer.fields().names()
    for n in preferred:
        if n in names:
            return n
    for f in layer.fields():
        if f.typeName().lower() in ("string","text","varchar","character varying"):
            return f.name()
    return names[0] if names else None

def open_gpkg_layer(gpkg_path, name):
    vl = QgsVectorLayer(f"{gpkg_path}|layername={name}", name, "ogr")
    return vl if vl.isValid() else None

def open_gpkg_by_simple_name(gpkg_path, wanted):
    vl = open_gpkg_layer(gpkg_path, wanted)
    if vl:
        return vl
    try:
        from osgeo import ogr
    except Exception:
        return None
    ds = ogr.Open(gpkg_path)
    if not ds:
        return None
    for i in range(ds.GetLayerCount()):
        nm = ds.GetLayerByIndex(i).GetName()
        if nm and nm.split(':')[-1] == wanted:
            vl = open_gpkg_layer(gpkg_path, nm)
            if vl and vl.isValid():
                return vl
    return None

def add_features_to_memory(mem_layer, source_layer, mem_fields):
    src_fields = source_layer.fields()
    prov = mem_layer.dataProvider()
    idx_map = [src_fields.indexOf(mem_fields[i].name()) for i in range(mem_fields.count())]
    batch = []
    for f in source_layer.getFeatures():
        nf = QgsFeature(mem_fields)
        nf.setGeometry(f.geometry())
        attrs = f.attributes()
        nf.setAttributes([attrs[i] if i != -1 else None for i in idx_map])
        batch.append(nf)
        if len(batch) >= 10000:
            prov.addFeatures(batch)
            batch.clear()
    if batch:
        prov.addFeatures(batch)

def apply_style_from_file(lyr, qml_path: Path, layer_name: str):
    if not qml_path or not qml_path.exists():
        print(f"[UWAGA] Styl '{layer_name}' – brak pliku: {qml_path}")
        return
    ok, msg = lyr.loadNamedStyle(str(qml_path))
    if not ok:
        print(f"[BŁĄD] Styl '{layer_name}' z '{qml_path}' nie został załadowany: {msg}")
    else:
        lyr.triggerRepaint()
        print(f"[OK] Styl zastosowany: {layer_name} <- {qml_path.name}")

def convert_gml_to_gpkg(gml_path: str) -> str:
    try:
        from osgeo import gdal
    except Exception:
        raise RuntimeError("Brak modułu osgeo.gdal w środowisku QGIS.")
    base = os.path.splitext(os.path.basename(gml_path))[0]
    gpkg_path = os.path.join(tempfile.gettempdir(), f"{base}_import_{uuid.uuid4().hex[:6]}.gpkg")
    while os.path.exists(gpkg_path):
        gpkg_path = os.path.join(tempfile.gettempdir(), f"{base}_import_{uuid.uuid4().hex[:6]}.gpkg")
    vt_opts = gdal.VectorTranslateOptions(
        format="GPKG",
        options=[
            "-skipfailures",
            "-mapFieldType","Date=String,DateTime=String",
            "-lco","SPATIAL_INDEX=YES",
            "-nlt","PROMOTE_TO_MULTI"
        ],
    )
    res = gdal.VectorTranslate(destNameOrDestDS=gpkg_path, srcDS=gml_path, options=vt_opts)
    if res is None:
        raise RuntimeError(f"Nie udało się utworzyć GPKG: {gpkg_path}")
    res = None
    return gpkg_path

def collect_titles_from_gml(gml_path: str):
    # map: strefa_gml_id -> {"podstawowy": set(), "dodatkowy": set()}
    titles = {}
    context = ET.iterparse(gml_path, events=('start','end'))
    _, root = next(context)
    cur_id, collecting = None, False
    for event, elem in context:
        ln = localname(elem.tag)
        if event == 'start':
            if ln == 'StrefaPlanistyczna':
                cur_id = get_attr_local(elem.attrib, 'id')  # gml:id
                collecting = True
                if cur_id:
                    titles.setdefault(cur_id, {"podstawowy": set(), "dodatkowy": set()})
            elif collecting and ln in ('profilPodstawowy','profilDodatkowy'):
                t = get_attr_local(elem.attrib, 'title')  # xlink:title
                if t and cur_id:
                    key = 'podstawowy' if ln == 'profilPodstawowy' else 'dodatkowy'
                    titles[cur_id][key].add(t)
        elif event == 'end':
            if ln == 'StrefaPlanistyczna':
                collecting = False
                cur_id = None
                root.clear()
    return titles

# ====== WEJŚCIE Z MAIN PLUGIN ======
def run(iface, plugin_dir: str):
    """
    Główne wejście funkcjonalności: import GML -> GPKG -> warstwy pamięciowe + style.
    """
    styles_dir = Path(plugin_dir) / "resources" / "qml"

    # 1) wybór GML
    gml_path, _ = QFileDialog.getOpenFileName(
        iface.mainWindow(),
        "Wskaż plik GML",
        "",
        "GML (*.gml *.xml)"
    )
    if not gml_path:
        return

    # 2) zbierz tytuły dzieci
    try:
        titles_by_id = collect_titles_from_gml(gml_path)
    except Exception as e:
        iface.messageBar().pushCritical("Plan Ogólny Gminy", f"Błąd parsowania GML: {e}")
        return

    # 3) GML -> GPKG
    try:
        gpkg_path = convert_gml_to_gpkg(gml_path)
    except Exception as e:
        iface.messageBar().pushCritical("Plan Ogólny Gminy", str(e))
        return

    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME) or root.addGroup(GROUP_NAME)
    group.setName(GROUP_NAME)

    # 4) proste warstwy
    for lname in SIMPLE_LAYERS:
        src = open_gpkg_by_simple_name(gpkg_path, lname)
        if not src:
            print(f"[UWAGA] Brak warstwy {lname} – pomijam.")
            continue

        wkb_str = QgsWkbTypes.displayString(src.wkbType())
        mem = QgsVectorLayer(f"memory:{lname}?geometry={wkb_str}", lname, "memory")
        mem.setCrs(src.crs())

        dp = mem.dataProvider()
        fields = src.fields()
        dp.addAttributes(list(fields))
        mem.updateFields()

        add_features_to_memory(mem, src, fields)

        project.addMapLayer(mem, False)
        group.addLayer(mem)

        # styl z pliku (jeśli jest)
        qml_file = styles_dir / STYLE_FILES.get(lname, "")
        apply_style_from_file(mem, qml_file, lname)

    # 5) StrefaPlanistyczna z dodatkowymi polami i stylem z pliku
    strefa_src = open_gpkg_by_simple_name(gpkg_path, "StrefaPlanistyczna")
    if not strefa_src:
        iface.messageBar().pushCritical("Plan Ogólny Gminy", "Brak warstwy 'StrefaPlanistyczna' w GPKG.")
        return

    wkb_str = QgsWkbTypes.displayString(strefa_src.wkbType())
    strefa_mem = QgsVectorLayer(f"memory:StrefaPlanistyczna?geometry={wkb_str}", "StrefaPlanistyczna", "memory")
    strefa_mem.setCrs(strefa_src.crs())
    dp = strefa_mem.dataProvider()

    all_fields = QgsFields(strefa_src.fields())
    # dodajemy stringowe pola wynikowe (lepiej jawnie: QVariant.String)
    for name in OUT_FIELDS:
        if name not in all_fields.names():
            all_fields.append(QgsField(name, QVariant.String))
    dp.addAttributes(list(all_fields))
    strefa_mem.updateFields()

    id_field = pick_strefa_id_field(strefa_src)
    id_idx = strefa_src.fields().indexOf(id_field) if id_field else -1
    out_idx = {name: all_fields.indexOf(name) for name in OUT_FIELDS}

    batch, matched = [], 0
    for f in strefa_src.getFeatures():
        nf = QgsFeature(all_fields)
        nf.setGeometry(f.geometry())
        attrs = f.attributes()
        new_attrs = attrs[:] + [None] * (all_fields.count() - len(attrs))

        sid = attrs[id_idx] if id_idx >= 0 else None
        if sid and sid in titles_by_id:
            pp = titles_by_id[sid]["podstawowy"]
            pd = titles_by_id[sid]["dodatkowy"]
            if pp:
                new_attrs[out_idx["profil_podstawowy"]] = ", ".join(sorted(pp))
            if pd:
                new_attrs[out_idx["profil_dodatkowy"]] = ", ".join(sorted(pd))
            if pp or pd:
                matched += 1

        nf.setAttributes(new_attrs)
        batch.append(nf)
        if len(batch) >= 5000:
            dp.addFeatures(batch)
            batch.clear()
    if batch:
        dp.addFeatures(batch)

    project.addMapLayer(strefa_mem, False)
    group.addLayer(strefa_mem)

    # styl z pliku dla StrefaPlanistyczna
    strefa_qml = styles_dir / STYLE_FILES["StrefaPlanistyczna"]
    apply_style_from_file(strefa_mem, strefa_qml, "StrefaPlanistyczna")

    iface.messageBar().pushSuccess(
        "Plan Ogólny Gminy",
        f"Gotowe. Dopasowano tytuły w {matched} strefach."
    )
