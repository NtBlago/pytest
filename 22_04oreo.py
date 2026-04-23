import sys, os, requests, time, math, random
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox, QTextEdit, QFrame,
    QGridLayout, QGroupBox, QSplitter, QSizePolicy, QDialog, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPointF, QRectF, QSize
from PyQt6.QtGui import (
    QFont, QPainter, QPen, QBrush, QColor, QLinearGradient,
    QRadialGradient, QPainterPath, QConicalGradient, QFontDatabase
)
import matplotlib

matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

API_BASE = "https://mephi.opentoshi.net/api/v1"
TEAM_NAME = "REVERSE_OREO"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reactor_log.txt")

C_BG = "#0a0e1a"
C_PANEL = "#0d1428"
C_BORDER = "#1a2a5e"
C_ACCENT = "#1565C0"
C_ACCENT2 = "#1E88E5"
C_ACCENT3 = "#42A5F5"
C_TEXT = "#cdd8f0"
C_MUTED = "#4a5a8a"
C_OK = "#00C853"
C_WARN = "#FF6F00"
C_CRIT = "#D50000"
C_WHITE = "#ffffff"

WATER_REFILL_COOLDOWN = 15


def write_log(message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass
    return entry.strip()


class ReactorAPI:
    def __init__(self):
        self.team_id = None

    def register_team(self):
        r = requests.get(f"{API_BASE}/team/register", params={"name": TEAM_NAME}, timeout=10)
        if r.status_code != 200: raise Exception(f"Registration failed: {r.status_code}")
        d = r.json();
        data = d.get("data", d)
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
        super().__init__();
        self.fn = fn;
        self.args = args

    def run(self):
        try:
            self.result.emit(self.fn(*self.args), "")
        except Exception as e:
            self.result.emit(None, str(e))


class MonitorThread(QThread):
    data_received = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, api, interval):
        super().__init__();
        self.api = api;
        self.interval = interval;
        self._running = True
        self.last_incident_check = time.time()
        self.active_incidents = {}
        self.incident_probability = 0.04
        self.last_water_refill_time = 0

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                data = self.api.get_data()
                if data:
                    sim_speed = data.get('simulation_speed', 1.0)
                    data = self._apply_local_incidents(data, sim_speed)
                    self.data_received.emit(data)
                    self._auto(data)
                else:
                    self.error.emit("Нет данных от сервера")
            except Exception as e:
                self.error.emit(str(e))
            time.sleep(self.interval)

    def _apply_local_incidents(self, data, sim_speed):
        now = time.time()
        sim_interval = 60.0 / sim_speed if sim_speed > 0 else 60

        if now - self.last_incident_check >= sim_interval:
            self.last_incident_check = now

            expired = []
            for inc_type, end_time in self.active_incidents.items():
                if now >= end_time:
                    expired.append(inc_type)
            for inc_type in expired:
                del self.active_incidents[inc_type]
                self.log_message.emit(write_log(f"ИНЦИДЕНТ ЗАВЕРШЁН: {inc_type}"))

            if random.random() < self.incident_probability and len(self.active_incidents) < 3:
                incident_data = self._generate_incident()
                duration_seconds = incident_data.get('duration', 5) * 60
                self.active_incidents[incident_data['type']] = now + duration_seconds
                self.log_message.emit(write_log(
                    f"ИНЦИДЕНТ: {incident_data['name']} - {incident_data['description']}"
                ))

        if self.active_incidents:
            incidents_list = []
            for inc_type, end_time in self.active_incidents.items():
                remaining = max(0, (end_time - now) / 60)
                incidents_list.append({
                    'type': inc_type,
                    'sim_minutes_remaining': remaining,
                    'started_at': datetime.now().isoformat()
                })
            data['incidents'] = incidents_list
        else:
            data['incidents'] = []

        return data

    def _generate_incident(self):
        incidents_pool = [
            {
                'type': 'water_leak',
                'name': 'Утечка воды',
                'description': 'потребление воды x2.5',
                'duration': 5
            },
            {
                'type': 'cooling_malfunction',
                'name': 'Неисправность охлаждения',
                'description': 'эффект охлаждения /2',
                'duration': 4
            },
            {
                'type': 'temperature_spike',
                'name': 'Скачок температуры',
                'description': 'повышение температуры на 60-90 C',
                'duration': 2
            }
        ]
        return random.choice(incidents_pool)

    def can_refill_water(self):
        now = time.time()
        if now - self.last_water_refill_time >= WATER_REFILL_COOLDOWN:
            return True, 0
        else:
            remaining = WATER_REFILL_COOLDOWN - (now - self.last_water_refill_time)
            return False, remaining

    def execute_refill(self, amount, source):
        can_refill, remaining = self.can_refill_water()
        if can_refill:
            result = self.api.refill_water(amount)
            if result:
                self.last_water_refill_time = time.time()
                self.log_message.emit(write_log(f"{source}: Вода долита {amount}Л"))
            else:
                self.log_message.emit(write_log(f"{source}: ОШИБКА: долив не удался"))
            return result
        else:
            self.log_message.emit(write_log(f"{source}: Долив запрещён. Осталось ждать {remaining:.1f} сек"))
            return False

    def _auto(self, d):
        t, w, r = d.get('temperature', 0), d.get('water_level', 0), d.get('radiation', 0)
        if d.get('emergency_active') or d.get('exploded'): return

        incidents = [i.get('type') for i in d.get('incidents', [])]
        cool_power = 20 if 'cooling_malfunction' in incidents else 10

        if w < 40:
            self.execute_refill(30, "AUTO")
        if t >= 1200:
            self.log_message.emit(write_log(f"AUTO: Температура {t:.1f}C >= 1200C - охлаждение {cool_power} ед"))
            self.api.activate_cooling(cool_power)
        if r >= 150:
            self.log_message.emit(write_log(f"AUTO: Радиация {r:.1f} >= 150 - охлаждение {cool_power} ед"))
            self.api.activate_cooling(cool_power)
        if t >= 1250 or r >= 200:
            self.log_message.emit(write_log("AUTO: КРИТИЧНО - аварийное отключение"))
            self.api.emergency_shutdown()


class GraphDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Графики параметров реактора")
        self.setGeometry(200, 200, 900, 600)
        self.setStyleSheet(f"background: {C_BG}; color: {C_TEXT};")

        self.history = []
        self.start_time = time.time()

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.figure = Figure(figsize=(10, 8), dpi=80, facecolor=C_BG)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        btn_close = QPushButton("Закрыть")
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: {C_ACCENT};
                border-radius: 6px;
                color: white;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {C_ACCENT2}; }}
        """)
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)

        self.ax1 = self.figure.add_subplot(311)
        self.ax2 = self.figure.add_subplot(312)
        self.ax3 = self.figure.add_subplot(313)

        for ax in [self.ax1, self.ax2, self.ax3]:
            ax.set_facecolor(C_PANEL)
            ax.tick_params(colors=C_TEXT)
            ax.title.set_color(C_ACCENT3)
            ax.xaxis.label.set_color(C_MUTED)
            ax.yaxis.label.set_color(C_MUTED)
            ax.spines['bottom'].set_color(C_BORDER)
            ax.spines['top'].set_color(C_BORDER)
            ax.spines['left'].set_color(C_BORDER)
            ax.spines['right'].set_color(C_BORDER)

        self.ax1.set_title("Температура (C)", color=C_CRIT)
        self.ax1.set_ylabel("C", color=C_MUTED)
        self.ax1.axhline(y=1200, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Критично (1200 C)')
        self.ax1.axhline(y=1250, color='darkred', linestyle='--', linewidth=1, alpha=0.7, label='Авария (1250 C)')

        self.ax2.set_title("Уровень воды (%)", color=C_ACCENT)
        self.ax2.set_ylabel("%", color=C_MUTED)
        self.ax2.axhline(y=40, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Минимум (40%)')
        self.ax2.axhline(y=20, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Критично (20%)')

        self.ax3.set_title("Радиация (мкЗв)", color=C_WARN)
        self.ax3.set_ylabel("мкЗв", color=C_MUTED)
        self.ax3.set_xlabel("Время (секунды)", color=C_MUTED)
        self.ax3.axhline(y=150, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Критично (150)')
        self.ax3.axhline(y=200, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Авария (200)')

        for ax in [self.ax1, self.ax2, self.ax3]:
            ax.legend(loc='upper right', facecolor=C_PANEL, labelcolor=C_TEXT)

        self.figure.tight_layout()

    def add_data_point(self, temp, water, rad):
        elapsed = time.time() - self.start_time
        self.history.append((elapsed, temp, water, rad))

        if len(self.history) > 300:
            self.history = self.history[-300:]

        self.update_graphs()

    def update_graphs(self):
        if not self.history:
            return

        times = [h[0] for h in self.history]
        temps = [h[1] for h in self.history]
        waters = [h[2] for h in self.history]
        rads = [h[3] for h in self.history]

        self.ax1.clear()
        self.ax2.clear()
        self.ax3.clear()

        self.ax1.plot(times, temps, color=C_CRIT, linewidth=2, label='Температура')
        self.ax1.set_title("Температура (C)", color=C_CRIT)
        self.ax1.set_ylabel("C", color=C_MUTED)
        self.ax1.axhline(y=1200, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Критично (1200 C)')
        self.ax1.axhline(y=1250, color='darkred', linestyle='--', linewidth=1, alpha=0.7, label='Авария (1250 C)')
        self.ax1.legend(loc='upper right', facecolor=C_PANEL, labelcolor=C_TEXT)
        self.ax1.set_facecolor(C_PANEL)
        self.ax1.tick_params(colors=C_TEXT)

        water_color = C_CRIT if min(waters) <= 40 else C_ACCENT
        self.ax2.plot(times, waters, color=water_color, linewidth=2, label='Уровень воды')
        self.ax2.set_title("Уровень воды (%)", color=C_ACCENT)
        self.ax2.set_ylabel("%", color=C_MUTED)
        self.ax2.axhline(y=40, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Минимум (40%)')
        self.ax2.axhline(y=20, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Критично (20%)')
        self.ax2.legend(loc='upper right', facecolor=C_PANEL, labelcolor=C_TEXT)
        self.ax2.set_facecolor(C_PANEL)
        self.ax2.tick_params(colors=C_TEXT)

        self.ax3.plot(times, rads, color=C_WARN, linewidth=2, label='Радиация')
        self.ax3.set_title("Радиация (мкЗв)", color=C_WARN)
        self.ax3.set_ylabel("мкЗв", color=C_MUTED)
        self.ax3.set_xlabel("Время (секунды)", color=C_MUTED)
        self.ax3.axhline(y=150, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Критично (150)')
        self.ax3.axhline(y=200, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Авария (200)')
        self.ax3.legend(loc='upper right', facecolor=C_PANEL, labelcolor=C_TEXT)
        self.ax3.set_facecolor(C_PANEL)
        self.ax3.tick_params(colors=C_TEXT)

        self.canvas.draw()

    def reset(self):
        self.history.clear()
        self.start_time = time.time()
        self.update_graphs()


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
        p = QPainter(self);
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.width() // 2, self.height() // 2, 10
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0, QColor("#42A5F5"))
        grad.setColorAt(1, QColor("#1565C0"))
        p.setBrush(QBrush(grad));
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        pen = QPen(QColor("#1E88E5"), 1.5)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen);
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            p.save()
            p.translate(cx, cy)
            p.rotate(self._angle + i * 60)
            p.drawEllipse(QRectF(-20, -8, 40, 16))
            ex = 20 * math.cos(math.radians(self._angle * (1 + i * 0.3)))
            ey = 8 * math.sin(math.radians(self._angle * (1 + i * 0.3)))
            p.setBrush(QColor("#42A5F5"));
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ex, ey), 2.5, 2.5)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.restore()


class ArcGauge(QWidget):
    def __init__(self, label, unit, min_v, max_v, warn, crit, invert_warn=False, parent=None):
        super().__init__(parent)
        self.label = label;
        self.unit = unit
        self.min_v = min_v;
        self.max_v = max_v
        self.warn = warn;
        self.crit = crit
        self.invert_warn = invert_warn
        self.value = max_v if invert_warn else min_v
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_value(self, v):
        self.value = v;
        self.update()

    def paintEvent(self, _):
        p = QPainter(self);
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 16
        x0 = (w - size) // 2;
        y0 = (h - size) // 2
        rect = QRectF(x0, y0, size, size)
        cx, cy = w / 2, h / 2

        pen = QPen(QColor(C_BORDER), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen);
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, 225 * 16, -270 * 16)

        ratio = max(0.0, min(1.0, (self.value - self.min_v) / (self.max_v - self.min_v)))
        span = int(-270 * 16 * ratio)

        if self.label == "Уровень воды":
            if self.value <= self.warn:
                color = QColor(C_CRIT)
            else:
                color = QColor(C_ACCENT2)
        else:
            if self.value >= self.crit:
                color = QColor(C_CRIT)
            elif self.value >= self.warn:
                color = QColor(C_WARN)
            else:
                color = QColor(C_ACCENT2)

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
            glow.setColorAt(0, color);
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(glow));
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(dx, dy), 8, 8)

        p.setPen(QColor(C_WHITE))
        p.setFont(QFont("Segoe UI", int(size * 0.12), QFont.Weight.Bold))
        p.drawText(QRectF(x0, y0 + size * 0.3, size, size * 0.3),
                   Qt.AlignmentFlag.AlignCenter, f"{self.value:.1f}")

        p.setPen(QColor(C_MUTED))
        p.setFont(QFont("Segoe UI", int(size * 0.07)))
        p.drawText(QRectF(x0, y0 + size * 0.52, size, size * 0.18),
                   Qt.AlignmentFlag.AlignCenter, self.unit)
        p.setFont(QFont("Segoe UI", int(size * 0.08), QFont.Weight.Bold))
        p.setPen(QColor(C_ACCENT3))
        p.drawText(QRectF(x0, y0 + size * 0.68, size, size * 0.18),
                   Qt.AlignmentFlag.AlignCenter, self.label)


GRADE_COLORS = {
    "A": "#00C853", "B": "#64DD17", "C": "#FFD600",
    "D": "#FF6D00", "E": "#DD2C00", "F": "#B71C1C",
}


class RatingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grade = "-";
        self.score = None
        self.setMinimumSize(90, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_rating(self, score, grade):
        self.score = score;
        self.grade = grade;
        self.update()

    def paintEvent(self, _):
        p = QPainter(self);
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 8
        cx, cy = w / 2, h / 2
        r = size / 2

        color = QColor(GRADE_COLORS.get(self.grade, C_MUTED))
        pen = QPen(color, 4)
        p.setPen(pen);
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 40))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad));
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(color)
        p.setFont(QFont("Segoe UI", int(size * 0.38), QFont.Weight.Bold))
        p.drawText(QRectF(0, cy - size * 0.30, w, size * 0.42),
                   Qt.AlignmentFlag.AlignCenter, self.grade)
        p.setPen(QColor(C_MUTED))
        p.setFont(QFont("Segoe UI", int(size * 0.13)))
        score_txt = f"{int(self.score)}/100" if self.score is not None else ""
        p.drawText(QRectF(0, cy + size * 0.12, w, size * 0.22),
                   Qt.AlignmentFlag.AlignCenter, score_txt)


INCIDENT_META = {
    "water_leak": ( "Утечка воды", "#01579B", "потребление воды x2.5"),
    "cooling_malfunction": ("Неисправность охлаждения", "#006064", "эффект охлаждения /2"),
    "temperature_spike": ("Скачок температуры", "#BF360C", "повышение на 60-90 C"),
}


class IncidentCard(QFrame):
    def __init__(self, incident, parent=None):
        super().__init__(parent)
        itype = incident.get("type", "")
        icon, name, color, desc = INCIDENT_META.get(itype, ("!", itype, C_WARN, ""))
        mins = incident.get("sim_minutes_remaining")

        self.setStyleSheet(f"""
            QFrame {{
                background: {color}22;
                border: 1px solid {color}88;
                border-left: 3px solid {color};
                border-radius: 6px;
            }}
        """)
        layout = QHBoxLayout(self);
        layout.setContentsMargins(8, 6, 8, 6);
        layout.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI", 14))
        icon_lbl.setFixedWidth(24)
        icon_lbl.setStyleSheet("background: transparent; border: none;")

        info = QVBoxLayout();
        info.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {C_TEXT}; background: transparent; border: none;")
        desc_lbl = QLabel(desc)
        desc_lbl.setFont(QFont("Segoe UI", 8))
        desc_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent; border: none;")
        info.addWidget(name_lbl);
        info.addWidget(desc_lbl)

        right = QVBoxLayout();
        right.setSpacing(1);
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        if mins is not None:
            time_lbl = QLabel(f"⏱ {mins:.0f} мин")
            time_lbl.setFont(QFont("Segoe UI", 9))
            time_lbl.setStyleSheet(f"color: {C_WARN}; background: transparent; border: none;")
            right.addWidget(time_lbl, alignment=Qt.AlignmentFlag.AlignRight)

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
        self._update_no_incidents()

    def _update_no_incidents(self):
        lbl = QLabel("Нет активных инцидентов")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color: {C_MUTED}; font-size: 11px; background: transparent;")
        self._layout.addWidget(lbl)

    def update_incidents(self, incidents):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if not incidents:
            self._update_no_incidents()
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
        p = QPainter(self);
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, QColor("#0d1428"))
        grad.setColorAt(0.5, QColor("#0f1e4a"))
        grad.setColorAt(1, QColor("#0d1428"))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(QPen(QColor(C_ACCENT), 1))
        p.drawLine(0, h - 1, w, h - 1)


class ReactorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = ReactorAPI()
        self.monitor_thread = None
        self.worker = None
        self.last_manual_refill_time = 0
        self._known_incidents = set()
        self.graph_dialog = None
        self._setup_ui()
        self._load_log()

    def _setup_ui(self):
        self.setWindowTitle("ТИ НИЯУ МИФИ - Система управления реактором")
        self.setMinimumSize(1100, 720)
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

        central = QWidget();
        self.setCentralWidget(central)
        root = QVBoxLayout(central);
        root.setContentsMargins(0, 0, 0, 0);
        root.setSpacing(0)

        header = HeaderWidget()
        h_layout = QHBoxLayout(header);
        h_layout.setContentsMargins(16, 8, 16, 8)

        self.atom_widget = AtomWidget()
        h_layout.addWidget(self.atom_widget)

        title_col = QVBoxLayout();
        title_col.setSpacing(0)
        lbl_mephi = QLabel("ТИ НИЯУ МИФИ")
        lbl_mephi.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        lbl_mephi.setStyleSheet(f"color: {C_ACCENT2}; letter-spacing: 3px; background: transparent;")
        lbl_sub = QLabel("Система мониторинга и управления ядерным реактором")
        lbl_sub.setFont(QFont("Segoe UI", 9))
        lbl_sub.setStyleSheet(f"color: {C_MUTED}; letter-spacing: 1px; background: transparent;")
        title_col.addWidget(lbl_mephi);
        title_col.addWidget(lbl_sub)
        h_layout.addLayout(title_col);
        h_layout.addStretch()

        self.status_lbl = QLabel("● OFFLINE")
        self.status_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.status_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
        self.team_lbl = QLabel(f"Команда: {TEAM_NAME}")
        self.team_lbl.setFont(QFont("Segoe UI", 9))
        self.team_lbl.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
        right_col = QVBoxLayout();
        right_col.setSpacing(2)
        right_col.addWidget(self.status_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self.team_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        h_layout.addLayout(right_col)
        root.addWidget(header)

        body = QWidget();
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12);
        body_layout.setSpacing(12)

        left = QWidget();
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0);
        left_layout.setSpacing(10)

        gauges_box = make_group("Состояние реактора")
        g_layout = QHBoxLayout(gauges_box);
        g_layout.setSpacing(8)
        self.temp_g = ArcGauge("Температура", "C", 0, 1500, 1200, 1250)
        self.water_g = ArcGauge("Уровень воды", "%", 0, 100, 40, 20, invert_warn=True)
        self.water_g.value = 100
        self.rad_g = ArcGauge("Радиация", "мкЗв", 0, 300, 150, 200)
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
        inc_inner = QVBoxLayout(inc_box);
        inc_inner.setContentsMargins(8, 4, 8, 8)
        self.incidents_w = IncidentsWidget()
        inc_inner.addWidget(self.incidents_w)
        left_layout.addWidget(inc_box)

        params_box = make_group("Параметры")
        p_grid = QGridLayout(params_box);
        p_grid.setSpacing(10)

        def param_label(t):
            l = QLabel(t);
            l.setStyleSheet(f"color:{C_MUTED}; font-size:11px; background: transparent;");
            return l

        p_grid.addWidget(param_label("Скорость симуляции (1-10):"), 0, 0)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(1, 10);
        self.speed_spin.setValue(1);
        self.speed_spin.setSingleStep(0.5)
        p_grid.addWidget(self.speed_spin, 0, 1)

        p_grid.addWidget(param_label("Интервал мониторинга (сек):"), 1, 0)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(1, 10);
        self.interval_spin.setValue(1);
        self.interval_spin.setSingleStep(0.5)
        p_grid.addWidget(self.interval_spin, 1, 1)
        left_layout.addWidget(params_box)

        ctrl_box = make_group("Управление")
        c_grid = QGridLayout(ctrl_box);
        c_grid.setSpacing(8)

        self.btn_connect = make_btn("Подключиться и создать реактор", C_ACCENT)
        self.btn_start = make_btn("Запустить мониторинг", "#00695C")
        self.btn_stop = make_btn("Остановить", "#37474F")
        self.btn_reset = make_btn("Сбросить реактор", "#4527A0")
        self.btn_water = make_btn("Долить воду", "#01579B")
        self.btn_cool = make_btn("Охлаждение", "#006064")
        self.btn_graphs = make_btn("Графики", "#4A148C")
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
                  self.btn_water, self.btn_cool, self.btn_emergency, self.btn_graphs):
            b.setEnabled(False)

        c_grid.addWidget(self.btn_connect, 0, 0, 1, 2)
        c_grid.addWidget(self.btn_start, 1, 0)
        c_grid.addWidget(self.btn_stop, 1, 1)
        c_grid.addWidget(self.btn_reset, 2, 0)
        c_grid.addWidget(self.btn_water, 2, 1)
        c_grid.addWidget(self.btn_cool, 3, 0)
        c_grid.addWidget(self.btn_emergency, 3, 1)
        c_grid.addWidget(self.btn_graphs, 4, 0, 1, 2)
        left_layout.addWidget(ctrl_box)
        left_layout.addStretch()

        log_box = make_group("Журнал событий")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit();
        self.log_view.setReadOnly(True)
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
        self.btn_graphs.clicked.connect(self._on_graphs)

    def _load_log(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    self.log_view.setPlainText(f.read())
            except Exception:
                pass

    def _log(self, msg):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _set_status(self, text, color):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; background: transparent;")

    def _on_connect(self):
        self.btn_connect.setEnabled(False)
        self._set_status("● Подключение...", C_WARN)
        self.atom_widget.start()
        self._log(write_log("СЕССИЯ НАЧАТА"))
        self._log(write_log("Программа запущена"))

        def do():
            self.api.register_team()
            self.api.create_reactor()
            return True

        self.worker = WorkerThread(do)
        self.worker.result.connect(self._on_connected)
        self.worker.start()

    def _on_connected(self, ok, err):
        if ok:
            self._log(write_log(f"Команда зарегистрирована. ID: {self.api.team_id}"))
            self._log(write_log("Реактор создан"))
            self._set_status("● ПОДКЛЮЧЕНО", C_OK)
            for b in (self.btn_start, self.btn_reset, self.btn_water,
                      self.btn_cool, self.btn_emergency, self.btn_graphs):
                b.setEnabled(True)
        else:
            self._log(write_log(f"ОШИБКА: {err}"))
            self._set_status("● ОШИБКА", C_CRIT)
            self.atom_widget.stop()
            self.btn_connect.setEnabled(True)

    def _on_start(self):
        speed = self.speed_spin.value()
        interval = self.interval_spin.value()
        self.worker = WorkerThread(self.api.set_speed, speed)
        self.worker.result.connect(lambda ok, _: self._start_monitor(interval, speed))
        self.worker.start()

    def _start_monitor(self, interval, speed):
        self._log(write_log(f"Скорость {speed}x, интервал {interval}с - мониторинг запущен"))
        self.monitor_thread = MonitorThread(self.api, interval)
        self.monitor_thread.data_received.connect(self._on_data)
        self.monitor_thread.log_message.connect(self._log)
        self.monitor_thread.error.connect(lambda e: self._log(f"[ОШИБКА] {e}"))
        self.monitor_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_status("● МОНИТОРИНГ", C_ACCENT3)

    def _on_stop(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
            self.monitor_thread = None
        self._log(write_log("Мониторинг остановлен пользователем"))
        self._set_status("● ПОДКЛЮЧЕНО", C_OK)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_reset(self):
        self.worker = WorkerThread(self.api.reset_reactor)
        self.worker.result.connect(lambda ok, _:
                                   self._log(write_log("Реактор сброшен" if ok else "ОШИБКА: сброс не удался")))
        self.worker.start()
        if self.graph_dialog:
            self.graph_dialog.reset()

    def _can_refill_manual(self):
        now = time.time()
        if now - self.last_manual_refill_time >= WATER_REFILL_COOLDOWN:
            return True, 0
        else:
            remaining = WATER_REFILL_COOLDOWN - (now - self.last_manual_refill_time)
            return False, remaining

    def _on_refill(self):
        if self.monitor_thread and (self.monitor_thread.active_incidents or
                                    self.monitor_thread.api.get_data().get('emergency_active')):
            self._log(write_log("РУЧНОЙ: Долив невозможен - аварийный режим или активные инциденты"))
            return

        can_refill, remaining = self._can_refill_manual()
        if can_refill:
            self.worker = WorkerThread(self.api.refill_water, 30)
            self.worker.result.connect(lambda ok, _:
                                       self._log(write_log(
                                           "РУЧНОЙ: Вода долита 30Л" if ok else "РУЧНОЙ: ОШИБКА: долив не удался")))
            self.worker.start()
            self.last_manual_refill_time = time.time()
        else:
            self._log(write_log(f"РУЧНОЙ: Долив запрещён. Осталось ждать {remaining:.1f} сек"))

    def _on_cool(self):
        self.worker = WorkerThread(self.api.activate_cooling, 10)
        self.worker.result.connect(lambda ok, _:
                                   self._log(write_log("Охлаждение 10 ед" if ok else "ОШИБКА: охлаждение")))
        self.worker.start()

    def _on_emergency(self):
        self.worker = WorkerThread(self.api.emergency_shutdown)
        self.worker.result.connect(lambda ok, _:
                                   self._log(
                                       write_log("АВАРИЙНОЕ ОТКЛЮЧЕНИЕ активировано" if ok else "ОШИБКА: отключение")))
        self.worker.start()

    def _on_graphs(self):
        if self.graph_dialog is None:
            self.graph_dialog = GraphDialog(self)
        self.graph_dialog.show()
        self.graph_dialog.raise_()

    def _on_data(self, data):
        t = data.get('temperature', 0)
        w = data.get('water_level', 0)
        r = data.get('radiation', 0)

        self.temp_g.set_value(t)
        self.water_g.set_value(w)
        self.rad_g.set_value(r)

        if self.graph_dialog and self.graph_dialog.isVisible():
            self.graph_dialog.add_data_point(t, w, r)

        score = data.get('rating')
        grade = data.get('rating_grade')
        if score is not None and grade:
            self.rating_w.set_rating(score, grade)

        incidents = data.get('incidents', [])
        self.incidents_w.update_incidents(incidents)

        if data.get('exploded'):
            at = data.get('exploded_at', '?')
            self._log(write_log(f"РЕАКТОР ВЗОРВАЛСЯ в {at}"))
            self._set_status("ВЗРЫВ", C_CRIT)
            self._on_stop()
        elif data.get('emergency_active'):
            self._set_status("АВАРИЙНЫЙ РЕЖИМ", C_WARN)

    def closeEvent(self, e):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        if self.graph_dialog:
            self.graph_dialog.close()
        write_log("=== СЕССИЯ ЗАВЕРШЕНА ===")
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ReactorWindow()
    window.show()
    sys.exit(app.exec())