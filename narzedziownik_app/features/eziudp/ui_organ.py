"""
Narzędziownik APP - Wtyczka QGIS
Informacje o autorach, repozytorium: https://github.com/tomasz-gietkowski-geoanalityka/narzedziownik_app
Dokumentacja: https://akademia.geoanalityka.pl/courses/narzedziownik-app-dokumentacja/
Licencja: GNU GPL v3.0 (https://www.gnu.org/licenses/gpl-3.0.html)

"""

# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox,
                             QSizePolicy, QMessageBox, QProgressBar)
from .workers import OrgSearchWorker

class EziudpOrganDialog(QDialog):
    def __init__(self, parent=None, initial_query: str = None, initial_organs: list = None):
        super().__init__(parent)
        self.setWindowTitle("EZiUDP – wybór organu")
        self.setMinimumWidth(640)

        v = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Wpisz nazwę organu, jednostki lub ich część:"))
        self.ed_query = QLineEdit(); self.ed_query.setPlaceholderText("np. 'nak', 'Bydgoszcz'…")
        row.addWidget(self.ed_query, 1)
        self.btn_search = QPushButton("Szukaj"); row.addWidget(self.btn_search)
        v.addLayout(row)

        self.lbl_status = QLabel("")
        self.prg = QProgressBar(); self.prg.setRange(0,100); self.prg.setValue(0)
        v.addWidget(self.lbl_status); v.addWidget(self.prg)

        self.lst = QListWidget(); self.lst.setSelectionMode(QListWidget.SingleSelection)
        self.lst.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.lst, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Cancel); bb.rejected.connect(self.reject); v.addWidget(bb)

        self.btn_search.clicked.connect(self._on_search)
        self.ed_query.returnPressed.connect(self._on_search)
        self.lst.itemDoubleClicked.connect(self._on_item_double_clicked)

        self.ed_query.setText(initial_query or "")
        if initial_organs:
            for name in initial_organs: self.lst.addItem(QListWidgetItem(name))
            self.lbl_status.setText(f"Znaleziono: {len(initial_organs)}"); self.prg.setValue(100)
        self.ed_query.setFocus()

    def current_query(self) -> str: return self.ed_query.text().strip()
    def current_organs(self) -> list: return [self.lst.item(i).text() for i in range(self.lst.count())]
    def selected_organ(self) -> str:
        it = self.lst.selectedItems(); return it[0].text() if it else ""

    def _on_item_double_clicked(self, item: QListWidgetItem):
        if item is not None: self.lst.setCurrentItem(item); self.accept()

    def _on_search(self):
        q = self.ed_query.text().strip()
        if not q:
            QMessageBox.information(self, "Informacja", "Wpisz frazę wyszukującą organ."); return
        self.lst.clear(); self.lbl_status.setText("Szukam…"); self.prg.setValue(0)
        self.worker = OrgSearchWorker(q, parent=self)
        self.worker.progress.connect(self.prg.setValue)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.result.connect(self._on_result)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_error(self, msg: str):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Błąd", msg)
        self.lbl_status.setText("Błąd."); self.prg.setValue(0)

    def _on_result(self, organs: list):
        self.lst.clear()
        if not organs:
            self.lbl_status.setText("Brak dopasowanych organów."); self.prg.setValue(100); return
        for name in sorted(organs, key=lambda s: s.lower()):
            self.lst.addItem(QListWidgetItem(name))
        self.lbl_status.setText(f"Znaleziono: {len(organs)}"); self.prg.setValue(100)
