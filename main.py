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
        # 验证逻辑略，保持健壮性
        if "schedule" not in data: data["schedule"] = self.default_config["schedule"].copy()
        if "class_times" not in data: data["class_times"] = self.default_config["class_times"].copy()
        if "colors" not in data: data["colors"] = self.default_config["colors"].copy()
        return data

    def save(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ... Getters ...
    def get_schedule(self, weekday):
        return self.data["schedule"].get(str(weekday), ["", "", "", ""])

    def set_schedule(self, weekday, courses):
        self.data["schedule"][str(weekday)] = courses[:4]; self.save()

    def get_class_times(self):
        return self.data["class_times"]

    def set_class_times(self, times):
        self.data["class_times"] = times; self.save()

    def get_target_date(self):
        return self.data.get("target_date", "")

    def set_target_date(self, date):
        self.data["target_date"] = date; self.save()

    def get_target_name(self):
        return self.data.get("target_name", "")

    def set_target_name(self, name):
        self.data["target_name"] = name; self.save()

    def get_color(self, key):
        return self.data["colors"].get(key, "#FFFFFF")

    def set_color(self, key, hex_val):
        self.data["colors"][key] = hex_val; self.save()


# ------------------------------
# 主 Dock 窗口
# ------------------------------
class DockBar(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config

        # 状态控制
        self.animation_running = False  # 隐藏/显示动画状态
        self.size_animation_running = False  # 大小变形动画状态
        self.current_state = "shown"
        self.view_mode = "full"  # 'full' (完整模式) or 'mini' (上课模式)

        self.trigger_height = 120
        self.pending_timer = None

        # 尺寸定义
        self.dock_height = 110
        self.full_width = 1300
        self.mini_width = 300  # 迷你模式宽度
        self.corner_radius = 20

        self.init_ui()
        self.setup_timers()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()

        # 初始居中
        self.current_width = self.full_width
        self.x_pos = (self.screen_width - self.current_width) // 2
        self.shown_y = 0
        self.hidden_y = -self.dock_height + 10

        self.setGeometry(self.x_pos, self.shown_y, self.current_width, self.dock_height)
        self.show()

    def setup_timers(self):
        # 界面刷新 & 模式检查 (1秒)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_and_check_mode)
        self.update_timer.start(1000)

        # 鼠标避让检测 (100ms)
        self.mouse_timer = QTimer(self)
        self.mouse_timer.timeout.connect(self.check_mouse_position)
        self.mouse_timer.start(100)

    # ---------------- 核心逻辑：模式切换 ----------------
    def update_and_check_mode(self):
        """每秒调用：更新界面并检查是否需要切换 Mini/Full 模式"""

        # 获取当前倒计时状态和是否在上课
        text, label, is_class_time = self.get_class_countdown()
        self.current_countdown_text = text
        self.current_countdown_label = label

        # 自动切换模式逻辑
        target_mode = "mini" if is_class_time else "full"

        if target_mode != self.view_mode:
            self.switch_view_mode(target_mode)

        self.update()  # 触发重绘

    def switch_view_mode(self, mode):
        if self.size_animation_running: return
        self.view_mode = mode
        self.size_animation_running = True

        # 目标宽度
        start_w = self.width()
        end_w = self.mini_width if mode == "mini" else self.full_width

        # 目标 X 坐标 (始终保持居中)
        start_x = self.x()
        end_x = (self.screen_width - end_w) // 2

        # 动画：同时改变 Geometry (位置+大小)
        self.size_anim = QPropertyAnimation(self, b"geometry")
        self.size_anim.setDuration(500)  # 500ms 平滑过渡
        self.size_anim.setStartValue(QRect(start_x, self.y(), start_w, self.dock_height))
        self.size_anim.setEndValue(QRect(end_x, self.y(), end_w, self.dock_height))
        self.size_anim.setEasingCurve(QEasingCurve.InOutQuad)

        # 动画过程中需要更新 x_pos 变量，确保隐藏/显示逻辑使用最新的中心位置
        self.size_anim.valueChanged.connect(lambda v: setattr(self, 'x_pos', v.x()))
        self.size_anim.finished.connect(lambda: setattr(self, 'size_animation_running', False))

        self.size_anim.start()

    # ---------------- 绘制逻辑 ----------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制胶囊背景
        path = QPainterPath()
        # 留边距画阴影或避免切边
        rect = QRect(5, 5, self.width() - 10, self.height() - 10)
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), self.corner_radius, self.corner_radius)

        bg_color = QColor(self.config.get_color("background"))
        bg_color.setAlpha(240)
        painter.fillPath(path, bg_color)
        painter.setPen(QColor(80, 80, 80))
        painter.drawPath(path)

        # 根据当前宽度判断绘制内容
        # 如果宽度接近 mini 模式，只画倒计时
        if self.width() < (self.full_width + self.mini_width) / 2:
            self.draw_mini_content(painter)
        else:
            self.draw_full_content(painter)

    def draw_mini_content(self, painter):
        """Mini 模式：只显示中间的大倒计时"""
        c_label = QColor(self.config.get_color("countdown_label"))
        c_text = QColor(self.config.get_color("countdown_text"))

        # 垂直居中
        center_x = self.width() // 2

        painter.setPen(c_label)
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.drawText(QRect(0, 15, self.width(), 20), Qt.AlignCenter, getattr(self, 'current_countdown_label', ''))

        painter.setPen(c_text)
        painter.setFont(QFont("Microsoft YaHei UI", 26, QFont.Bold))
        painter.drawText(QRect(0, 40, self.width(), 40), Qt.AlignCenter, getattr(self, 'current_countdown_text', ''))

    def draw_full_content(self, painter):
        """Full 模式：显示所有信息"""
        now = datetime.now()
        left_w = 140
        right_w = 220
        padding = 20

        # 1. 左侧：日期
        c_wd = QColor(self.config.get_color("weekday"))
        c_dt = QColor(self.config.get_color("date"))
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        painter.setPen(c_wd)
        painter.setFont(QFont("Microsoft YaHei UI", 22, QFont.Bold))
        painter.drawText(QRect(padding, 15, left_w, 35), Qt.AlignCenter, weekdays[now.weekday()])
        painter.setPen(c_dt)
        painter.setFont(QFont("Microsoft YaHei UI", 16))
        painter.drawText(QRect(padding, 50, left_w, 25), Qt.AlignCenter, now.strftime("%m/%d"))

        # 2. 右侧：倒计时 & 考试
        right_x = self.width() - right_w - padding
        c_cl = QColor(self.config.get_color("countdown_label"))
        c_ct = QColor(self.config.get_color("countdown_text"))
        c_ex = QColor(self.config.get_color("exam_text"))

        painter.setPen(c_cl)
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.drawText(QRect(right_x, 10, right_w, 20), Qt.AlignCenter, getattr(self, 'current_countdown_label', ''))

        painter.setPen(c_ct)
        painter.setFont(QFont("Microsoft YaHei UI", 22, QFont.Bold))
        painter.drawText(QRect(right_x, 32, right_w, 30), Qt.AlignCenter, getattr(self, 'current_countdown_text', ''))

        # 考试倒计时
        t_date = self.config.get_target_date()
        if t_date:
            try:
                diff = (datetime.strptime(t_date, "%Y-%m-%d") - now).days
                painter.setPen(c_ex)
                painter.setFont(QFont("Microsoft YaHei UI", 12))
                painter.drawText(QRect(right_x, 65, right_w, 20), Qt.AlignCenter,
                                 f"{self.config.get_target_name()} {diff}天")
            except:
                pass

        # 3. 中间：课程表
        schedule = self.config.get_schedule(now.weekday() + 1)
        labels = ["早自习", "上午", "下午", "晚答疑"]

        sch_start = padding + left_w + 20
        sch_end = right_x - 20
        total_w = sch_end - sch_start

        # 权重计算
        weights = [10 + len(schedule[i] if i < len(schedule) else "") * 3 for i in range(4)]
        total_weight = sum(weights)

        curr_x = sch_start
        c_lbl = QColor(self.config.get_color("schedule_label"))
        c_txt = QColor(self.config.get_color("schedule_text"))
        c_emp = QColor(self.config.get_color("schedule_empty"))

        for i in range(4):
            bw = (weights[i] / total_weight) * total_w
            dw = bw - 15

            painter.setPen(c_lbl)
            painter.setFont(QFont("Microsoft YaHei UI", 12))
            painter.drawText(QRect(int(curr_x), 15, int(dw), 20), Qt.AlignLeft, labels[i])

            txt = schedule[i] if i < len(schedule) else ""
            painter.setPen(c_txt if txt else c_emp)
            if not txt: txt = "无"

            # 字体自适应
            fs = 22
            font = QFont("Microsoft YaHei UI", fs, QFont.Bold)
            fm = QFontMetrics(font)
            while fm.horizontalAdvance(txt) > dw and fs > 12:
                fs -= 1
                font.setPointSize(fs)
                fm = QFontMetrics(font)

            painter.setFont(font)
            painter.drawText(QRect(int(curr_x), 40, int(dw), 30), Qt.AlignLeft | Qt.AlignVCenter, txt)

            if i < 3:
                lx = int(curr_x + bw)
                painter.setPen(QColor(60, 60, 60))
                painter.drawLine(lx, 15, lx, 85)

            curr_x += bw

    # ---------------- 避让模式 ----------------
    def _debounce(self, func, delay=50):
        if self.pending_timer: self.pending_timer.stop()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(func)
        t.start(delay)
        self.pending_timer = t

    def check_mouse_position(self):
        if self.animation_running: return
        mouse_y = QCursor.pos().y()
        if mouse_y < self.trigger_height:
            if self.current_state == "shown": self._debounce(self.hide_dock)
        else:
            if self.current_state == "hidden": self._debounce(self.show_dock)

    def hide_dock(self):
        self.animation_running = True
        self.current_state = "hidden"
        self.pos_anim = QPropertyAnimation(self, b"pos")
        self.pos_anim.setDuration(300)
        self.pos_anim.setStartValue(QPoint(self.x(), self.shown_y))
        self.pos_anim.setEndValue(QPoint(self.x(), self.hidden_y))
        self.pos_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.pos_anim.finished.connect(lambda: setattr(self, 'animation_running', False))
        self.pos_anim.start()

    def show_dock(self):
        self.animation_running = True
        self.current_state = "shown"
        self.pos_anim = QPropertyAnimation(self, b"pos")
        self.pos_anim.setDuration(300)
        self.pos_anim.setStartValue(QPoint(self.x(), self.y()))
        self.pos_anim.setEndValue(QPoint(self.x(), self.shown_y))
        self.pos_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.pos_anim.finished.connect(lambda: setattr(self, 'animation_running', False))
        self.pos_anim.start()

    def force_show(self):
        self.current_state = "shown"
        self.animation_running = False
        self.move(self.x_pos, self.shown_y)
        self.raise_()

    # --- 倒计时逻辑 (修正版) ---
    def parse_time(self, s):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(s, fmt).time()
            except:
                continue
        return None

    def get_class_countdown(self):
        """
        返回: (倒计时文本, 描述文本, 是否是上课时间)
        """
        now = datetime.now()
        tc = self.config.get_class_times()
        get_dt = lambda k: datetime.combine(now.date(), self.parse_time(tc.get(k, "00:00"))) if self.parse_time(
            tc.get(k, "00:00")) else None

        # 定义时间槽 (名称, key, 时长)
        # 1. 修正课间逻辑：需要在 slot 列表中标记该节课后是否有课间
        # True = 有课间, False = 无课间(紧接着下一节或放学)
        slots = [
            ("早自习", "morning_self", 30, False),  # 修正：无课间 (直接接 am1)
            ("上午第1节", "am1", 40, True),
            ("上午第2节", "am2", 42, True),
            ("上午第3节", "am3", 42, True),
            ("上午第4节", "am4", 42, False),  # 修正：无课间 (放学/午休)
            ("上午第5节", "am5", 40, False),  # 修正：无课间 (放学)
            ("下午第1节", "pm1", 40, True),
            ("下午第2节", "pm2", 42, False),  # 修正：无课间 (眼保健操/大课间通常不算普通课间倒计时)
            ("下午第3节", "pm3", 42, True),
            ("下午第4节", "pm4", 42, False),  # 修正：无课间 (放学)
            ("晚答疑", "evening_qa", 60, False),  # 修正：无课间
        ]

        timeline = []
        for name, key, dur, has_break in slots:
            start = get_dt(key)
            if not start: continue
            end = start + timedelta(minutes=dur)
            # 添加课程段
            timeline.append({"start": start, "end": end, "label": name, "type": "class"})

            # 如果配置为有课间，则生成课间段 (默认8分钟)
            if has_break:
                brk_end = end + timedelta(minutes=8)
                timeline.append({"start": end, "end": brk_end, "label": f"课间", "type": "break"})

        for slot in timeline:
            # 1. 当前处于该时间段内
            if slot["start"] <= now < slot["end"]:
                rem = slot["end"] - now
                m, s = divmod(rem.seconds, 60)
                time_str = f"{m:02d}:{s:02d}"

                if slot["type"] == "class":
                    return time_str, f"距离下课 ({slot['label']})", True  # True = 上课中 -> Mini Mode
                else:
                    return time_str, "距离上课", False  # False = 课间 -> Full Mode

            # 2. 当前处于该时间段之前 (即还没开始，找到最近的下一个)
            if now < slot["start"]:
                rem = slot["start"] - now
                if rem.total_seconds() < 3600:  # 1小时内显示倒计时
                    m, s = divmod(rem.seconds, 60)
                    return f"{m:02d}:{s:02d}", f"距离 {slot['label']}", False
                else:
                    return slot["start"].strftime("%H:%M"), f"{slot['label']} 开始", False

        return "已结束", "今日课程", False


# ------------------------------
# 系统托盘
# ------------------------------
class TraySignals(QWidget):
    show_settings = Signal()
    force_show_dock = Signal()
    exit_app = Signal()


class SettingsWindow(QWidget):
    # ... (设置窗口代码保持不变，为节省篇幅省略，逻辑已在v22完善) ...
    # 为了保证代码完整可运行，这里必须包含 SettingsWindow 的完整定义
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

    def closeEvent(self, e):
        e.ignore(); self.hide()

    def create_schedule_tab(self):
        w = QWidget();
        l = QVBoxLayout(w)
        self.table = QTableWidget(7, 5)
        self.table.setHorizontalHeaderLabels(["星期", "早自习", "上午", "下午", "晚答疑"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for r, day in enumerate(weekdays):
            self.table.setItem(r, 0, QTableWidgetItem(day))
            sch = self.config.get_schedule(r + 1)
            for c in range(4): self.table.setItem(r, c + 1, QTableWidgetItem(sch[c]))
        l.addWidget(self.table)
        btn = QPushButton("保存课程表");
        btn.clicked.connect(self.save_schedule);
        l.addWidget(btn)
        return w

    def create_time_tab(self):
        w = QWidget();
        scroll = QScrollArea();
        scroll.setWidgetResizable(True)
        c = QWidget();
        l = QVBoxLayout(c)
        self.time_edits = {}
        cfgs = [("morning_self", "早自习"), ("am1", "上午1"), ("am2", "上午2"), ("am3", "上午3"), ("am4", "上午4"),
                ("am5", "上午5"),
                ("pm1", "下午1"), ("pm2", "下午2"), ("pm3", "下午3"), ("pm4", "下午4"), ("evening_qa", "晚答疑")]
        times = self.config.get_class_times()
        for k, label in cfgs:
            row = QHBoxLayout();
            row.addWidget(QLabel(label))
            ed = QLineEdit(times.get(k, ""));
            self.time_edits[k] = ed
            row.addWidget(ed);
            l.addLayout(row)
        l.addStretch();
        btn = QPushButton("保存时间");
        btn.clicked.connect(self.save_times);
        l.addWidget(btn)
        scroll.setWidget(c);
        ml = QVBoxLayout(w);
        ml.addWidget(scroll);
        return w

    def create_countdown_tab(self):
        w = QWidget();
        l = QVBoxLayout(w)
        l.addWidget(QLabel("事件名称"));
        self.t_name = QLineEdit(self.config.get_target_name());
        l.addWidget(self.t_name)
        l.addWidget(QLabel("日期"));
        self.t_date = QLineEdit(self.config.get_target_date());
        l.addWidget(self.t_date)
        l.addStretch();
        btn = QPushButton("保存");
        btn.clicked.connect(self.save_cd);
        l.addWidget(btn);
        return w

    def create_color_tab(self):
        w = QWidget();
        l = QVBoxLayout(w);
        scroll = QScrollArea();
        scroll.setWidgetResizable(True)
        c = QWidget();
        form = QVBoxLayout(c);
        self.color_buttons = {}
        color_map = [("weekday", "星期"), ("date", "日期"), ("schedule_label", "标签"), ("schedule_text", "有课"),
                     ("schedule_empty", "无课"),
                     ("countdown_label", "倒计时标签"), ("countdown_text", "倒计时数字"), ("exam_text", "考试"),
                     ("background", "背景")]
        for k, n in color_map:
            r = QHBoxLayout();
            r.addWidget(QLabel(n));
            btn = QPushButton();
            btn.setFixedSize(60, 30)
            col = self.config.get_color(k);
            btn.setStyleSheet(f"background-color:{col}; border:2px solid #555")
            btn.clicked.connect(lambda ch=False, ky=k, b=btn: self.pick_color(ky, b))
            self.color_buttons[k] = btn;
            r.addWidget(btn);
            form.addLayout(r)
        form.addStretch();
        scroll.setWidget(c);
        l.addWidget(scroll);
        return w

    def pick_color(self, k, b):
        curr = self.config.get_color(k);
        c = QColorDialog.getColor(QColor(curr), self, "选择颜色")
        if c.isValid(): hex_c = c.name(); self.config.set_color(k, hex_c); b.setStyleSheet(
            f"background-color:{hex_c}; border:2px solid #555"); self.dock.update()

    def save_schedule(self):
        for r in range(7):
            cols = []
            for c in range(4): it = self.table.item(r, c + 1); cols.append(it.text() if it else "")
            self.config.set_schedule(r + 1, cols)
        self.dock.update();
        QMessageBox.information(self, "成功", "已保存")

    def save_times(self):
        d = {k: e.text() for k, e in self.time_edits.items()};
        self.config.set_class_times(d);
        self.dock.update();
        QMessageBox.information(self, "成功", "已保存")

    def save_cd(self):
        self.config.set_target_name(self.t_name.text());
        self.config.set_target_date(self.t_date.text());
        self.dock.update();
        QMessageBox.information(self, "成功", "已保存")


def run_tray(signals):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0));
    draw = ImageDraw.Draw(img);
    draw.rectangle((10, 10, 54, 54), fill="#3b82f6")
    menu = pystray.Menu(pystray.MenuItem("显示 Dock", lambda: signals.force_show_dock.emit()),
                        pystray.MenuItem("设置", lambda: signals.show_settings.emit()),
                        pystray.MenuItem("退出", lambda i, it: signals.exit_app.emit()))
    pystray.Icon("DockBar", img, "课表 Dock", menu).run()


def main():
    app = QApplication(sys.argv);
    app.setQuitOnLastWindowClosed(False)
    config = Config();
    dock = DockBar(config);
    settings = SettingsWindow(config, dock)
    signals = TraySignals()
    signals.show_settings.connect(lambda: (settings.show(), settings.activateWindow()))
    signals.force_show_dock.connect(dock.force_show)
    signals.exit_app.connect(lambda: (app.quit(), os._exit(0)))
    threading.Thread(target=run_tray, args=(signals,), daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()