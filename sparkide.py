"""sparkide - a c4d-flavored editor for the spark language.

panels: scripts (left), editor (center viewport), bytecode + functions
(right attributes), console (bottom). the bytecode updates live while
you type, like a material preview.
"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRect, QSize, QEvent
from PySide6.QtGui import (QColor, QFont, QPainter, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QIcon, QPixmap,
                           QPolygon)
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QApplication, QMainWindow, QSplitter,
                               QPlainTextEdit, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QDockWidget, QToolBar,
                               QFileDialog, QMessageBox, QWidget,
                               QVBoxLayout, QLabel)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QStyle

import spark

SRC_DIR = Path(__file__).parent / "scripts"

C4D_BG = "#4a4a4a"
C4D_DARK = "#3a3a3a"
C4D_EDIT = "#2b2b2b"
C4D_ACC = "#e8763e"
C4D_TXT = "#d8d8d8"

DEMO = '''let n = 10
let total = 0

fn fib(a, b, steps) {
    print a
    if steps > 0 {
        fib(b, a + b, steps - 1)
    }
}

print "fib:"
fib(0, 1, n)

let i = 0
while i < 5 {
    total = total + i * i
    i = i + 1
}
print "sum: " + total
'''


class High(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.rules = []
        def f(color, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Bold)
            if italic:
                fmt.setFontItalic(True)
            return fmt
        kw = f("#cc7832", True)
        for w in ("let", "if", "else", "while", "fn", "return",
                  "and", "or", "not", "true", "false"):
            self.rules.append((r"\b%s\b" % w, kw))
        self.rules.append((r"\bprint\b", f("#ffc66d", True)))
        self.rules.append((r'"[^"]*"', f("#6a8759")))
        self.rules.append((r"\b\d+(\.\d+)?\b", f("#6897bb")))
        self.rules.append((r"--[^\n]*", f("#808080", False, True)))
        self.rules.append((r"\b[a-zA-Z_]\w*(?=\s*\()", f("#e8bf6a")))
        import re
        self.rx = [(re.compile(p), fmt) for p, fmt in self.rules]

    def highlightBlock(self, text):
        for rx, fmt in self.rx:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class LineArea(QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.line_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_lines(e)


class Editor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setFont(QFont("Consolas", 11))
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.gut = LineArea(self)
        self.setViewportMargins(self.line_width(), 0, 0, 0)
        self.blockCountChanged.connect(lambda _: self._resize_gut())
        self.updateRequest.connect(self._gut_update)
        self.setStyleSheet(
            "QPlainTextEdit { background:%s; color:#d8d8d8; border:0; "
            "selection-background-color:#5a6b7d; }" % C4D_EDIT)

    def line_width(self):
        return 8 + self.fontMetrics().horizontalAdvance(
            str(max(1, self.blockCount()))) + 8

    def _resize_gut(self):
        r = self.contentsRect()
        self.gut.setGeometry(QRect(r.left(), r.top(),
                                   self.line_width(), r.height()))

    def _gut_update(self, rect, dy):
        if dy:
            self.gut.scroll(0, dy)
        else:
            self.gut.update(0, rect.y(), self.gut.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._resize_gut()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_gut()

    def paint_lines(self, e):
        p = QPainter(self.gut)
        p.fillRect(e.rect(), QColor(C4D_DARK))
        p.setPen(QColor("#787878"))
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(
            self.contentOffset()).top()
        h = self.blockBoundingRect(block).height()
        n = block.blockNumber()
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and top + h >= e.rect().top():
                p.drawText(0, int(top), self.gut.width() - 6, int(h),
                           Qt.AlignRight, str(n + 1))
            block = block.next()
            top += h
            h = self.blockBoundingRect(block).height()
            n += 1


def mk_icon(kind):
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    if kind == "play":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7bc96f"))
        p.drawPolygon(QPolygon([QPoint(4, 3), QPoint(13, 8), QPoint(4, 13)]))
    elif kind == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#d15b5b"))
        p.drawRect(4, 4, 8, 8)
    elif kind == "chip":
        p.setPen(QColor("#ddd"))
        p.setBrush(Qt.NoBrush)
        p.drawRect(3, 3, 10, 10)
        for i in (5, 8, 11):
            p.drawLine(i, 0, i, 3)
            p.drawLine(i, 13, i, 16)
            p.drawLine(0, i, 3, i)
            p.drawLine(13, i, 16, i)
    elif kind == "bolt":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e8b53e"))
        p.drawPolygon(QPolygon([
            QPoint(9, 1), QPoint(3, 9), QPoint(7, 9),
            QPoint(6, 15), QPoint(13, 6), QPoint(8, 6)]))
    p.end()
    return QIcon(px)


class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("spark")
        self.setWindowIcon(mk_icon("bolt"))
        self.resize(1240, 780)
        self.path = None
        self.last_err = False

        self.ed = Editor()
        self.hl = High(self.ed.document())
        self.ed.setPlainText(DEMO)
        self.setCentralWidget(self.ed)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 10))
        self.out.setStyleSheet(
            "QTextEdit { background:%s; color:%s; border-top:1px solid #333; }"
            % (C4D_EDIT, C4D_TXT))
        odock = QDockWidget("Console", self)
        odock.setObjectName("console")
        odock.setWidget(self.out)
        self.addDockWidget(Qt.BottomDockWidgetArea, odock)

        self.bcode = QTextEdit()
        self.bcode.setReadOnly(True)
        self.bcode.setFont(QFont("Consolas", 10))
        self.bcode.setStyleSheet(
            "QTextEdit { background:%s; color:#a8c8e8; border:0; }" % C4D_EDIT)
        bdock = QDockWidget("Bytecode", self)
        bdock.setObjectName("bytecode")
        bdock.setWidget(self.bcode)
        self.addDockWidget(Qt.RightDockWidgetArea, bdock)

        self.flist = QTreeWidget()
        self.flist.setHeaderHidden(True)
        self.flist.itemDoubleClicked.connect(self._fn_jump)
        fdock = QDockWidget("Functions", self)
        fdock.setObjectName("functions")
        fdock.setWidget(self.flist)
        self.addDockWidget(Qt.RightDockWidgetArea, fdock)

        self.files = QTreeWidget()
        self.files.setHeaderHidden(True)
        self.files.itemDoubleClicked.connect(self._file_open)
        sdock = QDockWidget("Scripts", self)
        sdock.setObjectName("scripts")
        sdock.setWidget(self.files)
        self.addDockWidget(Qt.LeftDockWidgetArea, sdock)
        self._fill_files()

        tb = QToolBar("tools")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)
        st = self.style()
        for label, fn, tip, ic in [
            ("New", self.new_file, "new", QStyle.SP_FileIcon),
            ("Open", self.open_file, "open", QStyle.SP_DialogOpenButton),
            ("Save", self.save, "save", QStyle.SP_DialogSaveButton),
            ("|", None, "", None),
            ("Run", self.run, "run (F5)", "play"),
            ("Bytecode", self.rebuild_bc, "rebuild bytecode", "chip"),
            ("Clear", self.out.clear, "clear console", QStyle.SP_TrashIcon),
        ]:
            if label == "|":
                tb.addSeparator()
                continue
            a = QAction(mk_icon(ic) if isinstance(ic, str)
                        else st.standardIcon(ic), label, self)
            a.setToolTip(tip)
            a.triggered.connect(fn)
            tb.addAction(a)
        runsc = QAction(self)
        runsc.setShortcut("F5")
        runsc.triggered.connect(self.run)
        self.addAction(runsc)

        self.statusBar().showMessage("ready")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._maybe_rebuild)
        self.timer.start(600)
        self._dirty = True
        self.ed.textChanged.connect(lambda: setattr(self, "_dirty", True))
        self.rebuild_bc()

    def _fill_files(self):
        SRC_DIR.mkdir(exist_ok=True)
        self.files.clear()
        for p in sorted(SRC_DIR.rglob("*")):
            if p.is_file() and p.suffix in (".sp", ".txt"):
                it = QTreeWidgetItem([p.name])
                it.setData(0, Qt.UserRole, str(p))
                it.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                self.files.addTopLevelItem(it)

    def _file_open(self, item, col):
        p = item.data(0, Qt.UserRole)
        self.ed.setPlainText(Path(p).read_text(encoding="utf-8"))
        self.path = p
        self.setWindowTitle("spark - " + Path(p).name)

    def _fn_jump(self, item, col):
        line = item.data(0, Qt.UserRole)
        if line is not None:
            cur = self.ed.textCursor()
            cur.setPosition(self.ed.document().findBlockByNumber(
                int(line)).position())
            self.ed.setTextCursor(cur)
            self.ed.setFocus()

    def _maybe_rebuild(self):
        if self._dirty:
            self._dirty = False
            self.rebuild_bc()

    def rebuild_bc(self):
        src = self.ed.toPlainText()
        try:
            toks = spark.lex(src)
            c = spark.Compiler()
            code = c.compile(spark.Parser(toks).program())
            self.bcode.setPlainText(spark.dis(code, c.fns))
            self.flist.clear()
            import re
            for m in re.finditer(r"(?m)^\s*fn\s+([a-zA-Z_]\w*)", src):
                it = QTreeWidgetItem(["fn " + m.group(1)])
                it.setData(0, Qt.UserRole,
                           src[:m.start()].count("\n"))
                self.flist.addTopLevelItem(it)
            if self.last_err:
                self.statusBar().showMessage("ok again")
                self.last_err = False
        except Exception as e:
            self.bcode.setPlainText("-- " + str(e))
            self.statusBar().showMessage(str(e)[:80])
            self.last_err = True

    def run(self):
        self.out.clear()
        self._println("#cccccc", "-- run %s --" % time.strftime("%H:%M:%S"))
        try:
            spark.run_src(self.ed.toPlainText(),
                          out=lambda s: self._println("#d8d8d8", s))
            self._println("#7bc96f", "-- done --")
        except Exception as e:
            self._println("#d15b5b", "err: " + str(e))

    def _println(self, color, text):
        cur = self.out.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = cur.charFormat()
        fmt.setForeground(QColor(color))
        cur.setCharFormat(fmt)
        cur.insertText(text + "\n")
        self.out.setTextCursor(cur)
        self.out.ensureCursorVisible()

    def new_file(self):
        self.ed.clear()
        self.path = None
        self.setWindowTitle("spark")

    def open_file(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "open", str(SRC_DIR), "Spark (*.sp);;All (*)")
        if p:
            self.ed.setPlainText(Path(p).read_text(encoding="utf-8"))
            self.path = p

    def save(self):
        if not self.path:
            p, _ = QFileDialog.getSaveFileName(
                self, "save", str(SRC_DIR), "Spark (*.sp)")
            if not p:
                return
            self.path = p
        Path(self.path).write_text(self.ed.toPlainText(), encoding="utf-8")
        self._fill_files()
        self.statusBar().showMessage("saved %s" % self.path, 3000)


def launch():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow, QDockWidget { background: %s; }
        QMenuBar { background: %s; color: %s; }
        QMenuBar::item:selected { background: %s; }
        QMenu { background: %s; color: %s; }
        QMenu::item:selected { background: %s; }
        QToolBar { background: %s; border: 0; spacing: 4px; padding: 3px; }
        QToolButton { color: %s; background: transparent; padding: 4px 8px;
            border-radius: 3px; }
        QToolButton:hover { background: #5a5a5a; }
        QToolButton:pressed { background: %s; }
        QDockWidget { color: %s; font-weight: bold; }
        QDockWidget::title { background: %s; padding: 5px;
            border-bottom: 1px solid #333; }
        QTreeWidget, QTextEdit { background: %s; color: %s; border: 0; }
        QTreeWidget::item:selected { background: %s; }
        QTreeWidget::item:hover { background: #555555; }
        QStatusBar { background: %s; color: %s; }
        QSplitter::handle { background: #333; }
    """ % (C4D_BG, C4D_DARK, C4D_TXT, "#5a5a5a", C4D_DARK, C4D_TXT,
           C4D_ACC, C4D_DARK, C4D_TXT, C4D_ACC, C4D_TXT, C4D_DARK,
           C4D_EDIT, C4D_TXT, C4D_ACC, C4D_DARK, C4D_TXT))
    w = Win()
    w.show()
    if "--shot" in sys.argv:
        def snap():
            w.grab().toImage().save("shot.png")
            app.quit()
        QTimer.singleShot(6000, snap)
    app.exec()


if __name__ == "__main__":
    launch()
