import sys, os, requests, time, math
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QTextEdit, QFrame,
    QGridLayout, QGroupBox, QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPointF, QRectF, QSize
from PyQt6.QtGui import (
    QFont, QPainter, QPen, QBrush, QColor, QLinearGradient,
    QRadialGradient, QPainterPath, QConicalGradient, QFontDatabase
)

API_BASE   = "https://mephi.opentoshi.net/api/v1"
TEAM_NAME  = "REVERSE_OREO"
LOG_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reactor_log.txt")


C_BG        = "#0a0e1a"
C_PANEL     = "#0d1428"
C_BORDER    = "#1a2a5e"
C_ACCENT    = "#1565C0"
C_ACCENT2   = "#1E88E5"
C_ACCENT3   = "#42A5F5"
C_TEXT      = "#cdd8f0"
C_MUTED     = "#4a5a8a"
C_OK        = "#00C853"
C_WARN      = "#FF6F00"
C_CRIT      = "#D50000"
C_WHITE     = "#ffffff"

def write_log(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception: pass
    return entry.strip()


class ReactorAPI:
    def __init__(self): self.team_id = None

    def register_team(self):
        r = requests.get(f"{API_BASE}/team/register", params={"name": TEAM_NAME}, timeout=10)
        if r.status_code != 200: raise Exception(f"Registration failed: {r.status_code}")
        d = r.json(); data = d.get("data", d)
        self.team_id = data.get("team_id") or data.get("id") or data.get("teamId")
        if not self.team_id: raise Exception("No team_id in response")

    def create_reactor(self):
        return requests.post(f"{API_BASE}/reactor/create_reactor",
                             params={"team_id": self.team_id}, timeout=10).status_code == 200

    def reset_reactor(self):
        return requests.post(f"{API_BASE}/reactor/reset_reactor",
                             params={"team_id": self.team_id}, timeout=10).status_code == 200

    def set_speed(self, s):
        return requests.post(f"{API_BASE}/reactor/set-speed",
                             params={"team_id": self.team_id, "speed": s}, timeout=10).status_code == 200

    def refill_water(self, a):
        return requests.post(f"{API_BASE}/reactor/refill-water",
                             params={"team_id": self.team_id, "amount": a}, timeout=10).status_code == 200

    def activate_cooling(self, s):
        return requests.post(f"{API_BASE}/reactor/activate-cooling",
                             params={"team_id": self.team_id, "amount": s}, timeout=10).status_code == 200

    def emergency_shutdown(self):
        return requests.post(f"{API_BASE}/reactor/emergency-shutdown",
                             params={"team_id": self.team_id}, timeout=10).status_code == 200

    def get_data(self):
        r = requests.get(f"{API_BASE}/reactor/data",
                         params={"team_id": self.team_id}, timeout=5)
        if r.status_code != 200: return None
        d = r.json()
        if "data" in d and "reactor_state" in d["data"]: return d["data"]["reactor_state"]
        return d.get("data", d)


class WorkerThread(QThread):
    result = pyqtSignal(object, str)
    def __init__(self, fn, *args):
        super().__init__(); self.fn = fn; self.args = args
    def run(self):
        try: self.result.emit(self.fn(*self.args), "")
        except Exception as e: self.result.emit(None, str(e))


class MonitorThread(QThread):
    data_received = pyqtSignal(dict)
    log_message   = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, api, interval):
        super().__init__(); self.api = api; self.interval = interval; self._running = True

    def stop(self): self._running = False

    def run(self):
        while self._running:
            try:
                data = self.api.get_data()
                if data: self.data_received.emit(data); self._auto(data)
                else: self.error.emit("No data from server")
            except Exception as e: self.error.emit(str(e))
            time.sleep(self.interval)

    def _auto(self, d):
        t, w, r = d.get('temperature',0), d.get('water_level',0), d.get('radiation',0)
        if d.get('emergency_active') or d.get('exploded'): return

        incidents = [i.get('type') for i in d.get('incidents', [])]
        # если cooling_malfunction — удваиваем мощность чтобы компенсировать
        cool_power = 20 if 'cooling_malfunction' in incidents else 10

        if w < 40:
            self.log_message.emit(write_log(f"AUTO: Вода {w:.1f}% < 40% — долив"))
            self.api.refill_water(30)
        if t >= 1200:
            self.log_message.emit(write_log(f"AUTO: Темп {t:.1f}°C ≥ 1200°C — охлаждение {cool_power} ед"))
            self.api.activate_cooling(cool_power)
        if r >= 150:
            self.log_message.emit(write_log(f"AUTO: Радиация {r:.1f} ≥ 150 — охлаждение {cool_power} ед"))
            self.api.activate_cooling(cool_power)
        if t >= 1250 or r >= 200:
            self.log_message.emit(write_log("AUTO: КРИТИЧНО — аварийное отключение"))
            self.api.emergency_shutdown()


class AtomWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._spinning = False

    def start(self): self._spinning = True;  self._timer.start(30)
    def stop(self):  self._spinning = False; self._timer.stop(); self.update()

    def _tick(self): self._angle = (self._angle + 3) % 360; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.width()//2, self.height()//2, 10
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0, QColor("#42A5F5"))
        grad.setColorAt(1, QColor("#1565C0"))
        p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        pen = QPen(QColor("#1E88E5"), 1.5)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            p.save()
            p.translate(cx, cy)
            p.rotate(self._angle + i * 60)
            p.drawEllipse(QRectF(-20, -8, 40, 16))
            ex = 20 * math.cos(math.radians(self._angle * (1 + i*0.3)))
            ey = 8  * math.sin(math.radians(self._angle * (1 + i*0.3)))
            p.setBrush(QColor("#42A5F5")); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ex, ey), 2.5, 2.5)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.restore()


class ArcGauge(QWidget):
    def __init__(self, label, unit, min_v, max_v, warn, crit, invert_warn=False, parent=None):
        super().__init__(parent)
        self.label = label; self.unit = unit
        self.min_v = min_v; self.max_v = max_v
        self.warn = warn; self.crit = crit
        self.invert_warn = invert_warn
        self.value = max_v if invert_warn else min_v
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_value(self, v):
        self.value = v; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 16
        x0 = (w - size) // 2; y0 = (h - size) // 2
        rect = QRectF(x0, y0, size, size)
        cx, cy = w / 2, h / 2

        pen = QPen(QColor(C_BORDER), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, 225 * 16, -270 * 16)

        ratio = max(0.0, min(1.0, (self.value - self.min_v) / (self.max_v - self.min_v)))
        span  = int(-270 * 16 * ratio)
        if self.value >= self.crit:   color = QColor(C_CRIT)
        elif self.value >= self.warn: color = QColor(C_WARN)
        else:                         color = QColor(C_ACCENT2)

        pen2 = QPen(color, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        p.drawArc(rect, 225 * 16, span)

        if ratio > 0.01:
            angle_deg = 225 - 270 * ratio
            rad = math.radians(angle_deg)
            r2 = size / 2
            dx = cx + r2 * math.cos(rad)
            dy = cy - r2 * math.sin(rad)
            glow = QRadialGradient(dx, dy, 8)
            glow.setColorAt(0, color); glow.setColorAt(1, QColor(0,0,0,0))
            p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(dx, dy), 8, 8)

        p.setPen(QColor(C_WHITE))
        p.setFont(QFont("Segoe UI", int(size * 0.12), QFont.Weight.Bold))
        p.drawText(QRectF(x0, y0 + size*0.3, size, size*0.3),
                   Qt.AlignmentFlag.AlignCenter, f"{self.value:.1f}")

        p.setPen(QColor(C_MUTED))
        p.setFont(QFont("Segoe UI", int(size * 0.07)))
        p.drawText(QRectF(x0, y0 + size*0.52, size, size*0.18),
                   Qt.AlignmentFlag.AlignCenter, self.unit)
        p.setFont(QFont("Segoe UI", int(size * 0.08), QFont.Weight.Bold))
        p.setPen(QColor(C_ACCENT3))
        p.drawText(QRectF(x0, y0 + size*0.68, size, size*0.18),
                   Qt.AlignmentFlag.AlignCenter, self.label)


GRADE_COLORS = {
    "A": "#00C853", "B": "#64DD17", "C": "#FFD600",
    "D": "#FF6D00", "E": "#DD2C00", "F": "#B71C1C",
}

class RatingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grade = "—"; self.score = None
        self.setMinimumSize(90, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_rating(self, score, grade):
        self.score = score; self.grade = grade; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 8
        cx, cy = w / 2, h / 2
        r = size / 2

        color = QColor(GRADE_COLORS.get(self.grade, C_MUTED))
        pen = QPen(color, 4)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 40))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(color)
        p.setFont(QFont("Segoe UI", int(size * 0.38), QFont.Weight.Bold))
        p.drawText(QRectF(0, cy - size*0.30, w, size*0.42),
                   Qt.AlignmentFlag.AlignCenter, self.grade)
        p.setPen(QColor(C_MUTED))
        p.setFont(QFont("Segoe UI", int(size * 0.13)))
        score_txt = f"{int(self.score)}/100" if self.score is not None else ""
        p.drawText(QRectF(0, cy + size*0.12, w, size*0.22),
                   Qt.AlignmentFlag.AlignCenter, score_txt)

INCIDENT_META = {
    "water_leak":           ( "Утечка воды",          "#01579B", "потребление ×2.5"),
    "cooling_malfunction":  ( "Неиспр. охлаждения",   "#006064", "эффект охл. ÷2"),
    "temperature_spike":    ( "Скачок температуры",   "#BF360C", "+60–90°C"),
}

class IncidentCard(QFrame):
    def __init__(self, incident, parent=None):
        super().__init__(parent)
        itype = incident.get("type", "")
        icon, name, color, desc = INCIDENT_META.get(itype, ("⚠", itype, C_WARN, ""))
        mins = incident.get("sim_minutes_remaining")
        started = incident.get("started_at", "")

        self.setStyleSheet(f"""
            QFrame {{
                background: {color}22;
                border: 1px solid {color}88;
                border-left: 3px solid {color};
                border-radius: 6px;
            }}
        """)
        layout = QHBoxLayout(self); layout.setContentsMargins(8, 6, 8, 6); layout.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI", 14))
        icon_lbl.setFixedWidth(24)
        icon_lbl.setStyleSheet("background: transparent; border: none;")

        info = QVBoxLayout(); info.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent; border: none;")
        desc_lbl = QLabel(desc)
        desc_lbl.setFont(QFont("Segoe UI", 8))
        desc_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent; border: none;")
        info.addWidget(name_lbl); info.addWidget(desc_lbl)

        right = QVBoxLayout(); right.setSpacing(1); right.setAlignment(Qt.AlignmentFlag.AlignRight)
        if mins is not None:
            time_lbl = QLabel(f"⏱ {mins:.0f} мин")
            time_lbl.setFont(QFont("Segoe UI", 9))
            time_lbl.setStyleSheet(f"color: {C_WARN}; background: transparent; border: none;")
            right.addWidget(time_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        if started:
            st_lbl = QLabel(str(started)[:16])
            st_lbl.setFont(QFont("Segoe UI", 8))
            st_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent; border: none;")
            right.addWidget(st_lbl, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(icon_lbl)
        layout.addLayout(info)
        layout.addStretch()
        layout.addLayout(right)


class IncidentsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._no_lbl = QLabel("Нет активных инцидентов")
        self._no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; background: transparent;")
        self._layout.addWidget(self._no_lbl)

    def update_incidents(self, incidents):
        # clear
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if not incidents:
            self._no_lbl = QLabel("Нет активных инцидентов")
            self._no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._no_lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; background: transparent;")
            self._layout.addWidget(self._no_lbl)
        else:
            for inc in incidents:
                self._layout.addWidget(IncidentCard(inc))
        self._layout.addStretch()


def make_btn(text, color=C_ACCENT, text_color=C_WHITE):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(36)
    b.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    b.setStyleSheet(f"""
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {color}cc, stop:1 {color}88);
            border: 1px solid {color};
            border-radius: 6px;
            color: {text_color};
            padding: 6px 14px;
            letter-spacing: 0.5px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {color}, stop:1 {color}bb);
            border: 1px solid #42A5F5;
        }}
        QPushButton:pressed {{ background: {color}55; }}
        QPushButton:disabled {{ background: #111828; border-color: #1a2a4a; color: #334; }}
    """)
    return b


def make_group(title):
    g = QGroupBox(title)
    g.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    g.setStyleSheet(f"""
        QGroupBox {{
            color: {C_ACCENT3};
            border: 1px solid {C_BORDER};
            border-radius: 10px;
            margin-top: 14px;
            padding-top: 6px;
            background: transparent;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px; padding: 0 6px;
            background: transparent;
        }}
    """)
    return g


class HeaderWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0,   QColor("#0d1428"))
        grad.setColorAt(0.5, QColor("#0f1e4a"))
        grad.setColorAt(1,   QColor("#0d1428"))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(QPen(QColor(C_ACCENT), 1))
        p.drawLine(0, h-1, w, h-1)
        p.setPen(QPen(QColor("#1a2a5e"), 1))
        for x in range(0, w, 30):
            for y in range(0, h, 30):
                p.drawPoint(x, y)

class ReactorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = ReactorAPI()
        self.monitor_thread = None
        self.worker = None
        self._known_incidents = set()
        self._setup_ui()
        self._load_log()

    def _setup_ui(self):
        self.setWindowTitle("ТИ НИЯУ МИФИ — Система управления реактором")
        self.setMinimumSize(1050, 680)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {C_BG}; color: {C_TEXT}; }}
            QSplitter::handle {{ background: {C_BORDER}; width: 2px; }}
            QDoubleSpinBox, QSpinBox {{
                background: #0d1428; border: 1px solid {C_BORDER};
                border-radius: 5px; padding: 4px 8px; color: {C_TEXT};
                font-size: 12px;
            }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                background: {C_ACCENT}; border-radius: 3px; width: 16px;
            }}
            QTextEdit {{
                background: #060a14; border: 1px solid {C_BORDER};
                border-radius: 8px; color: #5dade2;
                font-family: Consolas, monospace; font-size: 11px;
                selection-background-color: {C_ACCENT};
            }}
            QScrollBar:vertical {{
                background: #0d1428; width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {C_ACCENT}; border-radius: 4px; min-height: 20px;
            }}
            QLabel {{ background: transparent; }}
        """)

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        header = HeaderWidget()
        h_layout = QHBoxLayout(header); h_layout.setContentsMargins(16, 8, 16, 8)

        self.atom_widget = AtomWidget()
        h_layout.addWidget(self.atom_widget)

        title_col = QVBoxLayout(); title_col.setSpacing(0)
        lbl_mephi = QLabel("ТИ НИЯУ МИФИ")
        lbl_mephi.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        lbl_mephi.setStyleSheet(f"color: {C_ACCENT2}; letter-spacing: 3px; background: transparent;")
        lbl_sub = QLabel("Система мониторинга и управления ядерным реактором")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet(f"color: {C_MUTED}; letter-spacing: 1px; background: transparent;")
        title_col.addWidget(lbl_mephi); title_col.addWidget(lbl_sub)
        h_layout.addLayout(title_col); h_layout.addStretch()

        self.status_lbl = QLabel("● OFFLINE")
        self.status_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
        self.team_lbl = QLabel(f"Команда: {TEAM_NAME}")
        self.team_lbl.setFont(QFont("Segoe UI", 9))
        self.team_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
        right_col = QVBoxLayout(); right_col.setSpacing(2)
        right_col.addWidget(self.status_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self.team_lbl,   alignment=Qt.AlignmentFlag.AlignRight)
        h_layout.addLayout(right_col)
        root.addWidget(header)

        body = QWidget(); body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12); body_layout.setSpacing(12)

        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0,0,0,0); left_layout.setSpacing(10)

        gauges_box = make_group("Состояние реактора")
        g_layout = QHBoxLayout(gauges_box); g_layout.setSpacing(8)
        self.temp_g  = ArcGauge("Температура", "°C",  0, 1500, 1200, 1250)
        self.water_g = ArcGauge("Уровень воды", "%",  0,  100,   40,   20, invert_warn=True)
        self.water_g.value = 100
        self.rad_g   = ArcGauge("Радиация",   "мкЗв", 0,  300,  150,  200)
        for g in (self.temp_g, self.water_g, self.rad_g): g_layout.addWidget(g)
        self.rating_w = RatingWidget()
        self.rating_w.setMinimumSize(100, 100)
        rating_container = QWidget()
        rating_container.setMaximumWidth(130)
        rc_layout = QVBoxLayout(rating_container)
        rc_layout.setContentsMargins(0, 0, 0, 0)
        rc_layout.setSpacing(2)
        rc_layout.addWidget(self.rating_w)
        rating_lbl = QLabel("РЕЙТИНГ")
        rating_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rating_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        rating_lbl.setStyleSheet(f"color: {C_ACCENT3}; background: transparent;")
        rc_layout.addWidget(rating_lbl)
        g_layout.addWidget(rating_container)
        left_layout.addWidget(gauges_box)
        inc_box = make_group("Активные инциденты")
        inc_inner = QVBoxLayout(inc_box); inc_inner.setContentsMargins(8, 4, 8, 8)
        self.incidents_w = IncidentsWidget()
        inc_inner.addWidget(self.incidents_w)
        left_layout.addWidget(inc_box)

        params_box = make_group("Параметры")
        p_grid = QGridLayout(params_box); p_grid.setSpacing(10)

        def param_label(t):
            l = QLabel(t); l.setStyleSheet(f"color:{C_MUTED}; font-size:11px; background: transparent;"); return l

        p_grid.addWidget(param_label("Скорость симуляции (1–10):"), 0, 0)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(1, 10); self.speed_spin.setValue(1); self.speed_spin.setSingleStep(0.5)
        p_grid.addWidget(self.speed_spin, 0, 1)

        p_grid.addWidget(param_label("Интервал мониторинга (сек):"), 1, 0)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(1, 10); self.interval_spin.setValue(1); self.interval_spin.setSingleStep(0.5)
        p_grid.addWidget(self.interval_spin, 1, 1)
        left_layout.addWidget(params_box)

        ctrl_box = make_group("Управление")
        c_grid = QGridLayout(ctrl_box); c_grid.setSpacing(8)

        self.btn_connect = make_btn("Подключиться и создать реактор", C_ACCENT)
        self.btn_start   = make_btn("Запустить мониторинг", "#00695C")
        self.btn_stop    = make_btn("Остановить", "#37474F")
        self.btn_reset   = make_btn("Сбросить реактор", "#4527A0")
        self.btn_water   = make_btn("Долить воду ", "#01579B")
        self.btn_cool    = make_btn("Охлаждение", "#006064")
        self.btn_emergency = QPushButton("АВАРИЙНОЕ ОТКЛЮЧЕНИЕ!")
        self.btn_emergency.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emergency.setMinimumHeight(44)
        self.btn_emergency.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.btn_emergency.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #7f0000, stop:1 #4a0000);
                border: 2px solid {C_CRIT};
                border-radius: 8px; color: #ff5252;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: #9a0000; border-color: #ff1744; color: white; }}
            QPushButton:pressed {{ background: #3a0000; }}
            QPushButton:disabled {{ background: #110000; border-color: #330000; color: #442222; }}
        """)

        for b in (self.btn_start, self.btn_stop, self.btn_reset,
                  self.btn_water, self.btn_cool, self.btn_emergency):
            b.setEnabled(False)

        c_grid.addWidget(self.btn_connect,   0, 0, 1, 2)
        c_grid.addWidget(self.btn_start,     1, 0)
        c_grid.addWidget(self.btn_stop,      1, 1)
        c_grid.addWidget(self.btn_reset,     2, 0)

        # water refill row: button + amount spinbox
        water_row = QHBoxLayout(); water_row.setSpacing(4)
        water_row.addWidget(self.btn_water)
        self.water_amount_spin = QDoubleSpinBox()
        self.water_amount_spin.setRange(1, 100); self.water_amount_spin.setValue(30)
        self.water_amount_spin.setSingleStep(5); self.water_amount_spin.setSuffix(" Л")
        self.water_amount_spin.setFixedWidth(110)
        self.water_amount_spin.setToolTip("Объём долива воды")
        water_row.addWidget(self.water_amount_spin)
        water_widget = QWidget(); water_widget.setLayout(water_row)
        c_grid.addWidget(water_widget, 2, 1)

        # cooling row: button + duration spinbox
        cool_row = QHBoxLayout(); cool_row.setSpacing(4)
        cool_row.addWidget(self.btn_cool)
        self.cool_duration_spin = QDoubleSpinBox()
        self.cool_duration_spin.setRange(1, 100); self.cool_duration_spin.setValue(10)
        self.cool_duration_spin.setSingleStep(5); self.cool_duration_spin.setSuffix(" ед")
        self.cool_duration_spin.setFixedWidth(110)
        self.cool_duration_spin.setToolTip("Мощность охлаждения (расход воды = 3 × мощность)")
        cool_row.addWidget(self.cool_duration_spin)
        cool_widget = QWidget(); cool_widget.setLayout(cool_row)
        c_grid.addWidget(cool_widget, 3, 0)

        c_grid.addWidget(self.btn_emergency, 3, 1)
        left_layout.addWidget(ctrl_box)
        left_layout.addStretch()

        log_box = make_group("Журнал событий")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)

        body_layout.addWidget(left, 3)
        body_layout.addWidget(log_box, 2)
        root.addWidget(body)

        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_water.clicked.connect(self._on_refill)
        self.btn_cool.clicked.connect(self._on_cool)
        self.btn_emergency.clicked.connect(self._on_emergency)

    def _load_log(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    self.log_view.setPlainText(f.read())
                self.log_view.verticalScrollBar().setValue(
                    self.log_view.verticalScrollBar().maximum())
            except Exception: pass

    def _log(self, msg):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _set_status(self, text, color):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; background: transparent;")

    def _on_connect(self):
        self.btn_connect.setEnabled(False)
        self._set_status("● Подключение…", C_WARN)
        self.atom_widget.start()
        self._log(write_log("СЕССИЯ НАЧАТА"))
        self._log(write_log("Программа запущена"))

        def do():
            self.api.register_team(); self.api.create_reactor(); return True

        self.worker = WorkerThread(do)
        self.worker.result.connect(self._on_connected)
        self.worker.start()

    def _on_connected(self, ok, err):
        if ok:
            self._log(write_log(f"Команда зарегистрирована. ID: {self.api.team_id}"))
            self._log(write_log("Реактор создан"))
            self._set_status("● ПОДКЛЮЧЕНО", C_OK)
            for b in (self.btn_start, self.btn_reset, self.btn_water,
                      self.btn_cool, self.btn_emergency):
                b.setEnabled(True)
        else:
            self._log(write_log(f"ОШИБКА: {err}"))
            self._set_status("● ОШИБКА", C_CRIT)
            self.atom_widget.stop()
            self.btn_connect.setEnabled(True)

    def _on_start(self):
        speed = self.speed_spin.value(); interval = self.interval_spin.value()
        self.worker = WorkerThread(self.api.set_speed, speed)
        self.worker.result.connect(lambda ok, _: self._start_monitor(interval, speed))
        self.worker.start()

    def _start_monitor(self, interval, speed):
        self._log(write_log(f"Скорость {speed}x, интервал {interval}с — мониторинг запущен"))
        self.monitor_thread = MonitorThread(self.api, interval)
        self.monitor_thread.data_received.connect(self._on_data)
        self.monitor_thread.log_message.connect(self._log)
        self.monitor_thread.error.connect(lambda e: self._log(f"[ОШИБКА] {e}"))
        self.monitor_thread.start()
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        self._set_status("● МОНИТОРИНГ", C_ACCENT3)

    def _on_stop(self):
        if self.monitor_thread:
            self.monitor_thread.stop(); self.monitor_thread.wait()
            self.monitor_thread = None
        self._log(write_log("Мониторинг остановлен пользователем"))
        self._set_status("● ПОДКЛЮЧЕНО", C_OK)
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)

    def _on_reset(self):
        self.worker = WorkerThread(self.api.reset_reactor)
        self.worker.result.connect(lambda ok, _:
            self._log(write_log("Реактор сброшен" if ok else "ОШИБКА: сброс не удался")))
        self.worker.start()

    def _on_refill(self):
        amount = self.water_amount_spin.value()
        self.worker = WorkerThread(self.api.refill_water, amount)
        self.worker.result.connect(lambda ok, _:
            self._log(write_log(f"Вода долита +{amount:.0f}Л" if ok else "ОШИБКА: долив не удался")))
        self.worker.start()

    def _on_cool(self):
        duration = self.cool_duration_spin.value()
        water_cost = duration * 3
        self.worker = WorkerThread(self.api.activate_cooling, duration)
        self.worker.result.connect(lambda ok, _:
            self._log(write_log(f"Охлаждение {duration:.0f} ед (расход {water_cost:.0f}Л)" if ok else "ОШИБКА: охлаждение")))
        self.worker.start()

    def _on_emergency(self):
        self.worker = WorkerThread(self.api.emergency_shutdown)
        self.worker.result.connect(lambda ok, _:
            self._log(write_log("АВАРИЙНОЕ ОТКЛЮЧЕНИЕ активировано" if ok else "ОШИБКА: отключение")))
        self.worker.start()

    def _on_data(self, data):
        t = data.get('temperature', 0)
        w = data.get('water_level', 0)
        r = data.get('radiation', 0)
        self.temp_g.set_value(t)
        self.water_g.set_value(w)
        self.rad_g.set_value(r)

        # rating
        score = data.get('rating')
        grade = data.get('rating_grade')
        if score is not None and grade:
            self.rating_w.set_rating(score, grade)

        incidents = data.get('incidents', [])
        self.incidents_w.update_incidents(incidents)
        for inc in incidents:
            itype = inc.get('type', '')
            if itype not in self._known_incidents:
                self._known_incidents.add(itype)
                _, name, _, desc = INCIDENT_META.get(itype, ("", itype, "", ""))
                self._log(write_log(f"ИНЦИДЕНТ: {name} — {desc}"))
        active_types = {i.get('type') for i in incidents}
        self._known_incidents &= active_types

        if data.get('exploded'):
            at = data.get('exploded_at', '?')
            self._log(write_log(f"РЕАКТОР ВЗОРВАЛСЯ в {at}"))
            self._set_status("ВЗРЫВ", C_CRIT)
            self._on_stop()
        elif data.get('emergency_active'):
            self._set_status("АВАРИЙНЫЙ РЕЖИМ", C_WARN)

    def closeEvent(self, e):
        if self.monitor_thread: self.monitor_thread.stop(); self.monitor_thread.wait()
        write_log("=== СЕССИЯ ЗАВЕРШЕНА ===")
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ReactorWindow()
    window.show()
    sys.exit(app.exec())