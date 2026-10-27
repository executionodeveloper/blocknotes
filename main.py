import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import db
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QTextEdit, QPushButton, QLabel, QInputDialog, QMessageBox)
from PyQt6.QtCore import Qt

class BlockWidget(QWidget):
    def __init__(self, block_id, text, transcluded, deleted, main):
        super().__init__()
        self.block_id = block_id
        self.transcluded = transcluded
        self.deleted = deleted
        self.main = main
        lay = QHBoxLayout(self)
        self.text = QTextEdit()
        self.text.setPlainText("[deleted]" if deleted else text)
        self.text.setReadOnly(transcluded or deleted)
        self.text.setMaximumHeight(80)
        lay.addWidget(self.text)
        if transcluded:
            btn = QPushButton("open source")
            btn.clicked.connect(lambda: main.open_source(block_id))
            lay.addWidget(btn)
        # save on focus loss for native blocks
        def _fo(e):
            if not transcluded and not deleted:
                db.edit_block(block_id, self.text.toPlainText())
            QTextEdit.focusOutEvent(self.text, e)
        self.text.focusOutEvent = _fo

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("blocknotes")
        self.resize(900, 600)
        w = QWidget(); self.setCentralWidget(w)
        h = QHBoxLayout(w)
        # sidebar notes
        left = QVBoxLayout()
        self.note_list = QListWidget()
        self.note_list.itemClicked.connect(self.load_note)
        left.addWidget(QLabel("Notes"))
        left.addWidget(self.note_list)
        nb = QPushButton("New Note"); nb.clicked.connect(self.new_note)
        left.addWidget(nb)
        h.addLayout(left, 1)
        # main
        right = QVBoxLayout()
        tr = QHBoxLayout()
        self.title_edit = QTextEdit(); self.title_edit.setMaximumHeight(30)
        tr.addWidget(self.title_edit)
        rb = QPushButton("Rename"); rb.clicked.connect(self.rename_note)
        tr.addWidget(rb)
        right.addLayout(tr)
        self.blocks_area = QVBoxLayout()
        self.blocks_container = QWidget()
        self.blocks_container.setLayout(self.blocks_area)
        right.addWidget(self.blocks_container)
        # buttons
        br = QHBoxLayout()
        for label, fn in [("New Block", self.new_block), ("Split", self.split_sel),
                          ("Merge", self.merge_sel), ("Transclude", self.transclude_sel),
                          ("Delete Block", self.delete_sel)]:
            b = QPushButton(label); b.clicked.connect(fn); br.addWidget(b)
        right.addLayout(br)
        h.addLayout(right, 3)
        self.current_note = None
        self.selected_block = None
        self.refresh_notes()

    def refresh_notes(self):
        self.note_list.clear()
        for nid, title in db.list_notes():
            it = QListWidgetItem(title); it.setData(Qt.ItemDataRole.UserRole, nid)
            self.note_list.addItem(it)

    def new_note(self):
        nid = db.create_note()
        self.refresh_notes()

    def rename_note(self):
        if not self.current_note: return
        db.rename_note(self.current_note, self.title_edit.toPlainText().strip() or 'Untitled')
        self.refresh_notes()

    def load_note(self, item):
        self.current_note = item.data(Qt.ItemDataRole.UserRole)
        # load title
        c = db.init()
        t = c.execute("SELECT title FROM notes WHERE id=?", (self.current_note,)).fetchone()[0]
        c.close()
        self.title_edit.setPlainText(t)
        self.render_blocks()

    def render_blocks(self):
        # clear
        while self.blocks_area.count():
            w = self.blocks_area.takeAt(0).widget()
            if w: w.deleteLater()
        if not self.current_note: return
        for bid, trans, text, deleted in db.note_blocks_list(self.current_note):
            bw = BlockWidget(bid, text, bool(trans), bool(deleted), self)
            def _fi(e, b=bw):
                self.selected_block = b.block_id
                QTextEdit.focusInEvent(bw.text, e)
            bw.text.focusInEvent = _fi
            self.blocks_area.addWidget(bw)

    def new_block(self):
        if not self.current_note: return
        db.create_block("", self.current_note)
        self.render_blocks()

    def split_sel(self):
        if not self.selected_block: return
        w = self.find_block_widget(self.selected_block)
        if not w: return
        cursor = w.text.textCursor()
        pos = cursor.position()
        db.split_block(self.selected_block, pos)
        self.render_blocks()

    def find_block_widget(self, bid):
        for i in range(self.blocks_area.count()):
            w = self.blocks_area.itemAt(i).widget()
            if isinstance(w, BlockWidget) and w.block_id == bid:
                return w
        return None

    def merge_sel(self):
        # merge selected with next block in order
        if not self.selected_block or not self.current_note: return
        blocks = [r[0] for r in db.note_blocks_list(self.current_note)]
        idx = blocks.index(self.selected_block) if self.selected_block in blocks else -1
        if idx < 0 or idx+1 >= len(blocks): return
        db.merge_blocks(blocks[idx], blocks[idx+1])
        self.render_blocks()

    def transclude_sel(self):
        if not self.selected_block: return
        # ask which note
        notes = db.list_notes()
        titles = [t for _, t in notes]
        from PyQt6.QtWidgets import QInputDialog
        title, ok = QInputDialog.getItem(self, "Transclude into", "Note:", titles, 0, False)
        if not ok: return
        nid = [n for n, t in notes if t == title][0]
        pos = len(db.note_blocks_list(nid))
        db.transclude(self.selected_block, nid, pos)
        if nid == self.current_note:
            self.render_blocks()

    def delete_sel(self):
        if not self.selected_block: return
        db.delete_block(self.selected_block)
        self.render_blocks()

    def open_source(self, bid):
        # find native occurrence
        c = db.init()
        row = c.execute("SELECT note_id FROM note_blocks WHERE block_id=? AND transcluded=0", (bid,)).fetchone()
        c.close()
        if not row:
            QMessageBox.information(self, "source", "No native occurrence (deleted?)"); return
        nid = row[0]
        # switch note
        for i in range(self.note_list.count()):
            it = self.note_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == nid:
                self.note_list.setCurrentItem(it)
                self.load_note(it)
                break

if __name__ == "__main__":
    app = QApplication(sys.argv)
    db.init()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
