"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
import urllib.parse
from PyQt5.QtCore import QThread, pyqtSignal
from .http import http_get, BASE_URL, normalize_caps_url
from .parsers import extract_organs, extract_datasets, parse_wms_titles_names_and_crs, parse_wfs_titles_names_and_crs

class OrgSearchWorker(QThread):
    progress = pyqtSignal(int); status = pyqtSignal(str); result = pyqtSignal(list); error = pyqtSignal(str)
    def __init__(self, organ_query: str, parent=None):
        super().__init__(parent); self.organ_query = (organ_query or "").strip()
    def run(self):
        try:
            self.status.emit("Szukam organów w EZiUDP…")
            url = BASE_URL.format(query=urllib.parse.quote(self.organ_query))
            html_text = http_get(url).decode('utf-8', errors='ignore')
            organs = extract_organs(html_text)
            self.progress.emit(100); self.result.emit(organs)
        except Exception as e:
            self.error.emit(str(e))

class ServicesWorker(QThread):
    progress = pyqtSignal(int); status = pyqtSignal(str); result = pyqtSignal(dict); error = pyqtSignal(str)
    def __init__(self, organ_name: str, parent=None):
        super().__init__(parent); self.organ_name = (organ_name or "").strip()
    def run(self):
        try:
            self.status.emit("Wyszukuję usługi dla wybranego organu…")
            import html
            import urllib.parse
            url = BASE_URL.format(query=urllib.parse.quote(self.organ_name))
            html_text = http_get(url).decode('utf-8', errors='ignore')

            ds_urls = extract_datasets(html_text)
            if not ds_urls:
                # fallback: łap wszystkie linki i klasyfikuj AUTO/WMS/WFS (jak w Twoim kodzie)
                from html.parser import HTMLParser
                class _AllLinks(HTMLParser):
                    def __init__(self): super().__init__(); self.links=[]
                    def handle_starttag(self, tag, attrs):
                        if tag.lower()=="a":
                            for k,v in attrs:
                                if k and k.lower()=="href" and v: self.links.append(html.unescape(v).strip())
                al = _AllLinks(); al.feed(html_text)
                ds_urls = {"Nieznany zbiór danych": {"WMS": set(), "WFS": set()}}
                from .parsers import classify_service_href
                for href in al.links:
                    kind = classify_service_href(href)
                    if not kind: continue
                    if kind == "AUTO":
                        ds_urls["Nieznany zbiór danych"]["WMS"].add(href)
                        ds_urls["Nieznany zbiór danych"]["WFS"].add(href)
                    else:
                        ds_urls["Nieznany zbiór danych"][kind].add(href)

            datasets = {}; plan=[]
            for ds_name, buckets in ds_urls.items():
                for kind in ("WMS","WFS"):
                    for href in sorted(buckets.get(kind, [])):
                        plan.append((ds_name, kind, href))

            total = max(1, len(plan))
            for i,(ds_name, kind_try, href) in enumerate(plan, 1):
                self.status.emit(f"Pobieram {kind_try} ({i}/{total})…")
                caps_url = normalize_caps_url(href, kind_try)
                try:
                    caps = http_get(caps_url, timeout=30)
                    d = datasets.setdefault(ds_name, {"WMS": set(),"WFS": set(),
                                                      "WMS_LAYERS": {}, "WFS_LAYERS": {},
                                                      "WMS_CRS": {}, "WFS_CRS": {}})
                    if kind_try == "WMS":
                        items, crs = parse_wms_titles_names_and_crs(caps, href=href)
                        d["WMS"].add(href)
                        d["WMS_LAYERS"].setdefault(href, [])
                        d["WMS_CRS"].setdefault(href, set()).update(crs)
                        seen_local = set((it["title"], it["name"], it["depth"]) for it in d["WMS_LAYERS"][href])
                        for it in items:
                            key = (it["title"], it["name"], it["depth"])
                            if key not in seen_local:
                                d["WMS_LAYERS"][href].append(it)
                                seen_local.add(key)
                    else:
                        pairs, crs = parse_wfs_titles_names_and_crs(caps)
                        d["WFS"].add(href)
                        d["WFS_LAYERS"].setdefault(href, [])
                        d["WFS_CRS"].setdefault(href, set()).update(crs)
                        seen_local = set((t,n) for (t,n,_) in d["WFS_LAYERS"][href])
                        for (t,n,is_group) in pairs:
                            if (t,n) not in seen_local:
                                d["WFS_LAYERS"][href].append((t,n,is_group))
                                seen_local.add((t,n))
                except Exception as e:
                    self.status.emit(f"Błąd {kind_try}: {e}")
                self.progress.emit(min(99, int(100*i/total)))

            for v in datasets.values():
                for href,lst in v["WMS_LAYERS"].items():
                    lst.sort(key=lambda it: (it.get("depth",0), (it.get("title") or "").casefold()))
                for href,lst in v["WFS_LAYERS"].items():
                    lst.sort(key=lambda p: (p[0] or "").casefold())

            out = {}
            for k,v in datasets.items():
                out[k] = {
                    "WMS": sorted(v["WMS"]),
                    "WFS": sorted(v["WFS"]),
                    "WMS_LAYERS": v["WMS_LAYERS"],
                    "WFS_LAYERS": v["WFS_LAYERS"],
                    "WMS_CRS": {u: sorted(list(s)) for u,s in v["WMS_CRS"].items()},
                    "WFS_CRS": {u: sorted(list(s)) for u,s in v["WFS_CRS"].items()},
                }
            self.result.emit(out)
        except Exception as e:
            self.error.emit(str(e))
