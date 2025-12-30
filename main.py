import sys
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import threading

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QColorDialog,
    QFrame,
)
from PySide6.QtCore import (
    Qt,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QPoint,
    QRect,
    Signal,
    QSize,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPainterPath,
    QFont,
    QPalette,
    QCursor,
    QFontMetrics,
)

import pystray
from PIL import Image, ImageDraw


# ------------------------------
# 配置文件管理
# ------------------------------
class Config:
    def __init__(self):
        self.config_file = Path("dock_config.json")
        self.default_config = {
            "schedule": {
                "1": ["语文", "通用 物理 英语 生物", "政治 历史 语文 化学", "信息"],
                "2": ["数学", "语文 数学 英语 物理", "化学 生物 历史 政治", "语文"],
                "3": ["英语", "物理 化学 数学 语文", "英语 通用 生物 历史", "数学"],
                "4": ["语文", "英语 生物 数学 政治", "语文 物理 化学 信息", "英语"],
                "5": ["数学", "物理 英语 化学 历史", "语文 数学 生物 政治", "物理"],
                "6": ["", "", "", ""],
                "7": ["", "", "", ""],
            },
            "class_times": {
                "morning_self": "07:00:00",
                "am1": "08:00:00",
                "am2": "08:52:00",
                "am3": "10:00:00",
                "am4": "10:50:00",
                "am5": "11:40:00",
                "pm1": "14:00:00",
                "pm2": "14:52:00",
                "pm3": "16:00:00",
                "pm4": "16:52:00",
                "evening_qa": "18:30:00",
            },
            "target_date": "2026-06-07",
            "target_name": "高考",
            "colors": {
                "weekday": "#5AB9FF",
                "date": "#888888",
                "schedule_label": "#888888",
                "schedule_text": "#E0E0E0",
                "schedule_empty": "#555555",
                "countdown_label": "#888888",
                "countdown_text": "#FF6B6B",
                "exam_text": "#666666",
                "background": "#1E1E1E",
            }
        }
        self.load()

    def load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    self.data = self.validate_and_fix_config(loaded_data)
            except Exception:
                self.data = self.default_config.copy()
                self.save()
        else:
            self.data = self.default_config.copy()
            self.save()

    def validate_and_fix_config(self, data):
        if "schedule" not in data:
            data["schedule"] = self.default_config["schedule"].copy()
        for day in range(1, 8):
            day_key = str(day)
            if day_key not in data["schedule"]:
                data["schedule"][day_key] = ["", "", "", ""]
            else:
                schedule = data["schedule"][day_key]
                if not isinstance(schedule, list):
                    data["schedule"][day_key] = ["", "", "", ""]
                else:
                    while len(schedule) < 4:
                        schedule.append("")
                    data["schedule"][day_key] = schedule[:4]

        if "class_times" not in data:
            data["class_times"] = self.default_config["class_times"].copy()
        else:
            for k, v in self.default_config["class_times"].items():
                if k not in data["class_times"]:
                    data["class_times"][k] = v

        if "target_date" not in data:
            data["target_date"] = self.default_config["target_date"]
        if "target_name" not in data:
            data["target_name"] = self.default_config["target_name"]
        if "colors" not in data:
            data["colors"] = self.default_config["colors"].copy()
        else:
            for k, v in self.default_config["colors"].items():
                if k not in data["colors"]:
                    data["colors"][k] = v

        return data

    def save(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # --- Getters & Setters ---
    def get_schedule(self, weekday):
        return self.data["schedule"].get(str(weekday), ["", "", "", ""])

    def set_schedule(self, weekday, courses):
        self.data["schedule"][str(weekday)] = courses[:4]
        self.save()

    def get_class_times(self):
        return self.data["class_times"]

    def set_class_times(self, times):
        self.data["class_times"] = times
        self.save()

    def get_target_date(self):
        return self.data.get("target_date", "")

    def set_target_date(self, date):
        self.data["target_date"] = date
        self.save()

    def get_target_name(self):
        return self.data.get("target_name", "")

    def set_target_name(self, name):
        self.data["target_name"] = name
        self.save()

    def get_color(self, key):
        return self.data["colors"].get(key, "#FFFFFF")

    def set_color(self, key, hex_val):
        self.data["colors"][key] = hex_val
        self.save()


# ------------------------------
# 主 Dock 窗口
# ------------------------------
class DockBar(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config

        self.current_mode = "normal"
        self.is_hidden = False
        self.animation_running = False

        self.trigger_height = 120
        self.pending_timer = None

        self.init_ui()
        self.setup_timers()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.full_height = 110
        self.full_width = 1300
        self.corner_radius = 20

        # [修改点 2] 胶囊尺寸调整：加大一点
        self.mini_height = 60  # 原 50 -> 60
        self.mini_width = 220  # 原 180 -> 220

        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()

        self.normal_x = (self.screen_width - self.full_width) // 2
        self.normal_y = 0

        self.setGeometry(self.normal_x, self.normal_y, self.full_width, self.full_height)
        self.show()

    def setup_timers(self):
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_tick)
        self.update_timer.start(1000)

        self.mouse_timer = QTimer(self)
        self.mouse_timer.timeout.connect(self.check_mouse_position)
        self.mouse_timer.start(100)

    def update_tick(self):
        _, _, type_ = self.get_class_countdown_data()
        target_mode = "class_mode" if type_ == "class" else "normal"

        if target_mode != self.current_mode:
            self.switch_mode(target_mode)

        self.update()

    def switch_mode(self, target_mode):
        if self.animation_running: return
        self.current_mode = target_mode
        self.update_geometry_by_state()

    def update_geometry_by_state(self):
        if self.animation_running: return

        if self.current_mode == "normal":
            w, h = self.full_width, self.full_height
            x = (self.screen_width - w) // 2
            y = 0 if not self.is_hidden else (-h + 10)
        else:
            w, h = self.mini_width, self.mini_height
            x = self.screen_width - w - 20
            y = 10 if not self.is_hidden else (-h)

        self.animation_running = True
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.setDuration(400)
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(QRect(x, y, w, h))
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.anim.finished.connect(self.on_anim_finished)
        self.anim.start()

    def on_anim_finished(self):
        self.animation_running = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.current_mode == "normal":
            self.draw_full_dock(painter)
        else:
            self.draw_mini_capsule(painter)

    def draw_full_dock(self, painter):
        w = self.width()
        h = self.height()

        path = QPainterPath()
        rect = QRect(5, 5, w - 10, h - 10)
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), self.corner_radius, self.corner_radius)

        bg_color = QColor(self.config.get_color("background"))
        bg_color.setAlpha(240)
        painter.fillPath(path, bg_color)
        painter.setPen(QColor(80, 80, 80))
        painter.drawPath(path)

        now = datetime.now()
        left_w = 140
        right_w = 220
        padding = 20

        # 左侧
        c_weekday = QColor(self.config.get_color("weekday"))
        c_date = QColor(self.config.get_color("date"))
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        painter.setPen(c_weekday)
        painter.setFont(QFont("Microsoft YaHei UI", 22, QFont.Bold))
        painter.drawText(QRect(padding, 15, left_w, 35), Qt.AlignCenter, weekdays[now.weekday()])
        painter.setPen(c_date)
        painter.setFont(QFont("Microsoft YaHei UI", 16))
        painter.drawText(QRect(padding, 50, left_w, 25), Qt.AlignCenter, now.strftime("%m/%d"))

        # 右侧：倒计时
        right_x = w - right_w - padding
        c_cd_label = QColor(self.config.get_color("countdown_label"))
        c_cd_text = QColor(self.config.get_color("countdown_text"))
        c_exam = QColor(self.config.get_color("exam_text"))

        cd_text, cd_label, _ = self.get_class_countdown_data()

        painter.setPen(c_cd_label)
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.drawText(QRect(right_x, 10, right_w, 20), Qt.AlignCenter, cd_label)

        # [修改点 1] 倒计时字体大小设置处 (Full Mode)
        painter.setPen(c_cd_text)
        painter.setFont(QFont("Microsoft YaHei UI", 22, QFont.Bold))
        painter.drawText(QRect(right_x, 32, right_w, 30), Qt.AlignCenter, cd_text)

        t_date_str = self.config.get_target_date()
        t_name = self.config.get_target_name()
        if t_date_str:
            try:
                diff = (datetime.strptime(t_date_str, "%Y-%m-%d") - now).days
                painter.setPen(c_exam)
                painter.setFont(QFont("Microsoft YaHei UI", 12))
                painter.drawText(QRect(right_x, 65, right_w, 20), Qt.AlignCenter, f"{t_name} {diff}天")
            except:
                pass

        # 中间：课程表
        sch_start_x = padding + left_w + 20
        sch_end_x = right_x - 20
        total_sch_w = sch_end_x - sch_start_x

        schedule = self.config.get_schedule(now.weekday() + 1)
        labels = ["早自习", "上午", "下午", "晚答疑"]

        weights = []
        for i in range(4):
            txt = schedule[i] if i < len(schedule) else ""
            if not txt: txt = "无"
            weight = 10 + len(txt) * 3
            weights.append(weight)
        total_weight = sum(weights)

        c_lbl = QColor(self.config.get_color("schedule_label"))
        c_txt = QColor(self.config.get_color("schedule_text"))
        c_emp = QColor(self.config.get_color("schedule_empty"))

        text_padding = 15
        curr_x = sch_start_x

        for i in range(4):
            blk_w = (weights[i] / total_weight) * total_sch_w
            drw_w = blk_w - text_padding - 5
            text_x = int(curr_x + text_padding)

            painter.setPen(c_lbl)
            painter.setFont(QFont("Microsoft YaHei UI", 12))
            painter.drawText(QRect(text_x, 15, int(drw_w), 20), Qt.AlignLeft, labels[i])

            txt = schedule[i] if i < len(schedule) else ""
            if txt:
                painter.setPen(c_txt)
            else:
                painter.setPen(c_emp)
                txt = "无"

            # [修改点 1] 课表字体大小设置处 (Full Mode)
            # 这里设置基准大小为 22，代码会自动缩小以适应长文本
            font_sz = 22
            font = QFont("Microsoft YaHei UI", font_sz, QFont.Bold)
            fm = QFontMetrics(font)
            while fm.horizontalAdvance(txt) > drw_w and font_sz > 12:
                font_sz -= 1
                font.setPointSize(font_sz)
                fm = QFontMetrics(font)

            painter.setFont(font)
            painter.drawText(QRect(text_x, 40, int(drw_w), 30), Qt.AlignLeft | Qt.AlignVCenter, txt)

            if i < 3:
                lx = int(curr_x + blk_w)
                painter.setPen(QColor(60, 60, 60))
                painter.drawLine(lx, 15, lx, 85)

            curr_x += blk_w

    def draw_mini_capsule(self, painter):
        w = self.width()
        h = self.height()

        path = QPainterPath()
        rect = QRect(0, 0, w, h)
        radius = h / 2
        path.addRoundedRect(rect, radius, radius)

        bg_color = QColor(self.config.get_color("background"))
        bg_color.setAlpha(200)
        painter.fillPath(path, bg_color)
        painter.setPen(QColor(100, 100, 100))
        painter.drawPath(path)

        cd_text, _, _ = self.get_class_countdown_data()
        c_cd_text = QColor(self.config.get_color("countdown_text"))

        # [修改点 2] 间隙调整：文字位置微调，留出更多留白

        # [修改点 1] 胶囊倒计时字体大小 (Mini Mode)
        painter.setPen(c_cd_text)
        painter.setFont(QFont("Microsoft YaHei UI", 24, QFont.Bold))
        # y从 8 开始绘制，高度 30
        painter.drawText(QRect(0, 8, w, 30), Qt.AlignCenter, cd_text)

        # 小字 "距离下课"
        painter.setPen(QColor("#AAAAAA"))
        painter.setFont(QFont("Microsoft YaHei UI", 11))
        # y从 38 开始绘制
        painter.drawText(QRect(0, 38, w, 15), Qt.AlignCenter, "距离下课")

    # ... (其余方法 check_mouse_position, hide_dock, force_show 等保持不变) ...
    def _debounce(self, func, delay=50):
        if self.pending_timer: self.pending_timer.stop()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(func)
        t.start(delay)
        self.pending_timer = t

    def check_mouse_position(self):
        try:
            if self.animation_running: return
            mouse_y = QCursor.pos().y();
            mouse_x = QCursor.pos().x()
            should_hide = False
            if mouse_y < self.trigger_height:
                if self.current_mode == "normal":
                    should_hide = True
                elif self.current_mode == "class_mode":
                    if mouse_x > (self.screen_width - 300): should_hide = True

            if should_hide:
                if not self.is_hidden: self.is_hidden = True; self._debounce(self.update_geometry_by_state)
            else:
                if self.is_hidden: self.is_hidden = False; self._debounce(self.update_geometry_by_state)
        except:
            pass

    def force_show(self):
        self.is_hidden = False;
        self.update_geometry_by_state();
        self.raise_()

    def parse_time(self, s):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(s, fmt).time()
            except:
                continue
        return None

    def get_class_countdown_data(self):
        now = datetime.now()
        times_config = self.config.get_class_times()
        get_dt = lambda k: datetime.combine(now.date(),
                                            self.parse_time(times_config.get(k, "00:00"))) if self.parse_time(
            times_config.get(k, "00:00")) else None

        slots_def = [
            ("早自习", "morning_self", 30, False),
            ("上午1", "am1", 40, True),
            ("上午2", "am2", 42, True),
            ("上午3", "am3", 42, True),
            ("上午4", "am4", 42, True),
            ("上午5", "am5", 40, False),
            ("下午1", "pm1", 40, True),
            ("下午2", "pm2", 42, True),
            ("下午3", "pm3", 42, True),
            ("下午4", "pm4", 42, False),
            ("晚答疑", "evening_qa", 60, False),
        ]

        timeline = []
        for name, key, dur, has_break in slots_def:
            start = get_dt(key)
            if not start: continue
            end = start + timedelta(minutes=dur)
            timeline.append({"start": start, "end": end, "label": name, "type": "class"})
            if has_break:
                brk_end = end + timedelta(minutes=8)
                timeline.append({"start": end, "end": brk_end, "label": f"课间", "type": "break"})

        for slot in timeline:
            if slot["start"] <= now < slot["end"]:
                rem = slot["end"] - now
                m, s = divmod(rem.seconds, 60)
                txt = f"{m:02d}:{s:02d}"
                return txt, "距离下课" if slot["type"] == "class" else "距离上课", slot["type"]

            if now < slot["start"]:
                rem = slot["start"] - now
                if rem.total_seconds() < 20 * 60:
                    m, s = divmod(rem.seconds, 60)
                    return f"{m:02d}:{s:02d}", f"距离{slot['label']}", "break"
                else:
                    return slot["start"].strftime("%H:%M"), f"{slot['label']} 开始", "rest"

        return "已结束", "今日课程", "end"

# ------------------------------
# 系统托盘信号
# ------------------------------
class TraySignals(QWidget):
    show_settings = Signal()
    force_show_dock = Signal()
    exit_app = Signal()


# ------------------------------
# 设置窗口
# ------------------------------
class SettingsWindow(QWidget):
    def __init__(self, config, dock):
        super().__init__()
        self.config = config
        self.dock = dock
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("课表设置")
        self.resize(1000, 700)
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #f0f0f0; font-family: "Microsoft YaHei UI"; font-size: 14px; }
            QLineEdit { background-color: #2d2d2d; border: 1px solid #444; padding: 6px; border-radius: 6px; color:white;}
            QPushButton { background-color: #3b82f6; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { background-color: #2563eb; }
            QTabWidget::pane { border: none; margin-top: 10px; }
            QTabBar::tab { background: #2d2d2d; padding: 10px 20px; margin-right: 5px; border-radius: 8px; }
            QTabBar::tab:selected { background: #3b82f6; }
            QTableWidget { background: #2d2d2d; border: none; gridline-color: #444; }
            QHeaderView::section { background: #1e1e1e; padding: 8px; border:none; border-bottom: 2px solid #3b82f6; }
        """)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_schedule_tab(), "课程表")
        self.tabs.addTab(self.create_time_tab(), "时间")
        self.tabs.addTab(self.create_countdown_tab(), "倒计时")
        self.tabs.addTab(self.create_color_tab(), "外观颜色")

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        self.setLayout(layout)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def create_schedule_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)

        self.table = QTableWidget(7, 5)
        self.table.setHorizontalHeaderLabels(["星期", "早自习", "上午", "下午", "晚答疑"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for r, day in enumerate(weekdays):
            self.table.setItem(r, 0, QTableWidgetItem(day))
            sch = self.config.get_schedule(r + 1)
            for c in range(4):
                self.table.setItem(r, c + 1, QTableWidgetItem(sch[c]))

        l.addWidget(QLabel("课程表编辑"))
        l.addWidget(self.table)
        btn = QPushButton("保存课程表")
        btn.clicked.connect(self.save_schedule)
        l.addWidget(btn)
        return w

    def create_time_tab(self):
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        c = QWidget()
        l = QVBoxLayout(c)

        self.time_edits = {}
        cfgs = [("morning_self", "早自习"), ("am1", "上午1"), ("am2", "上午2"),
                ("am3", "上午3"), ("am4", "上午4"), ("am5", "上午5"),
                ("pm1", "下午1"), ("pm2", "下午2"), ("pm3", "下午3"), ("pm4", "下午4"),
                ("evening_qa", "晚答疑")]
        times = self.config.get_class_times()

        for k, label in cfgs:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(100)
            entry = QLineEdit(times.get(k, ""))
            entry.setPlaceholderText("HH:MM:SS")
            self.time_edits[k] = entry
            row.addWidget(lbl)
            row.addWidget(entry)
            l.addLayout(row)

        l.addStretch()
        btn = QPushButton("保存时间")
        btn.clicked.connect(self.save_times)
        l.addWidget(btn)

        scroll.setWidget(c)
        main_l = QVBoxLayout(w)
        main_l.addWidget(scroll)
        return w

    def create_countdown_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel("事件名称"))
        self.t_name = QLineEdit(self.config.get_target_name())
        l.addWidget(self.t_name)
        l.addWidget(QLabel("日期 (YYYY-MM-DD)"))
        self.t_date = QLineEdit(self.config.get_target_date())
        l.addWidget(self.t_date)
        l.addStretch()
        btn = QPushButton("保存倒计时")
        btn.clicked.connect(self.save_cd)
        l.addWidget(btn)
        return w

    def create_color_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        c = QWidget()
        form = QVBoxLayout(c)

        self.color_buttons = {}
        color_map = [
            ("weekday", "星期几颜色"), ("date", "日期颜色"),
            ("schedule_label", "课程标签"), ("schedule_text", "有课颜色"), ("schedule_empty", "无课颜色"),
            ("countdown_label", "倒计时标签"), ("countdown_text", "倒计时数字"), ("exam_text", "考试倒计时"),
            ("background", "背景颜色"),
        ]

        for key, name in color_map:
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            btn = QPushButton()
            btn.setFixedSize(60, 30)
            curr_col = self.config.get_color(key)
            btn.setStyleSheet(f"background-color: {curr_col}; border: 2px solid #555;")
            btn.clicked.connect(lambda checked=False, k=key, b=btn: self.pick_color(k, b))
            self.color_buttons[key] = btn
            row.addWidget(btn)
            form.addLayout(row)

        form.addStretch()
        scroll.setWidget(c)
        l.addWidget(scroll)
        return w

    def pick_color(self, key, btn):
        curr = self.config.get_color(key)
        c = QColorDialog.getColor(QColor(curr), self, "选择颜色")
        if c.isValid():
            hex_c = c.name()
            self.config.set_color(key, hex_c)
            btn.setStyleSheet(f"background-color: {hex_c}; border: 2px solid #555;")
            self.dock.update()

    def save_schedule(self):
        for r in range(7):
            cols = []
            for c in range(4):
                item = self.table.item(r, c + 1)
                cols.append(item.text() if item else "")
            self.config.set_schedule(r + 1, cols)
        self.dock.update()
        QMessageBox.information(self, "成功", "已保存")

    def save_times(self):
        d = {}
        for k, e in self.time_edits.items():
            d[k] = e.text()
        self.config.set_class_times(d)
        self.dock.update()
        QMessageBox.information(self, "成功", "已保存")

    def save_cd(self):
        self.config.set_target_name(self.t_name.text())
        self.config.set_target_date(self.t_date.text())
        self.dock.update()
        QMessageBox.information(self, "成功", "已保存")


# ------------------------------
# 托盘逻辑
# ------------------------------
def run_tray(signals):
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 54, 54), fill="#3b82f6")

    def show_settings(icon, item):
        signals.show_settings.emit()

    def do_exit(icon, item):
        icon.stop()
        signals.exit_app.emit()

    menu = pystray.Menu(
        pystray.MenuItem("设置", show_settings),
        pystray.MenuItem("退出", do_exit)
    )

    icon = pystray.Icon("DockBar", image, "课表 Dock", menu)
    icon.run()


# ------------------------------
# Main
# ------------------------------
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = Config()
    dock = DockBar(config)
    settings = SettingsWindow(config, dock)

    signals = TraySignals()
    signals.show_settings.connect(lambda: (settings.show(), settings.activateWindow()))
    signals.force_show_dock.connect(dock.force_show)

    def on_exit():
        app.quit()
        os._exit(0)

    signals.exit_app.connect(on_exit)

    t = threading.Thread(target=run_tray, args=(signals,), daemon=True)
    t.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()