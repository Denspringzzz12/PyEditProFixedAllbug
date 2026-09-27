# -*- coding: utf-8 -*-
"""
PyEdit IDE + PAI 合并版
Material 3 主题 + AI 聊天 + Windows 控制 + 代码上下文
依赖: pip install PyQt6 psutil openai requests
"""

import sys
import os
import re
import json
import base64
import shutil
import keyword
import builtins
import threading
import subprocess
import platform
import time
import queue
import tempfile
import colorsys
import uuid
import html as html_lib
from pathlib import Path
from datetime import datetime

import psutil
import requests

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# 可选：Windows 控制
try:
    import ctypes
    from ctypes import wintypes
    HAS_WIN32 = platform.system() == "Windows"
except Exception:
    HAS_WIN32 = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except Exception:
    HAS_OPENAI = False


# ============================================================
# Material 3 动态取色
# ============================================================

def _rgb_to_hct(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    h = h * 360
    y = 0.2126 * (r / 255) + 0.7152 * (g / 255) + 0.0722 * (b / 255)
    return h, s * 100, y * 100


def _hct_to_rgb(h, c, t):
    h_norm = (h % 360) / 360
    s = min(1.0, c / 100)
    l = max(0.05, min(0.95, t / 100))
    r, g, b = colorsys.hls_to_rgb(h_norm, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _hex(r, g, b):
    return f"#{r:02X}{g:02X}{b:02X}"


def _lighter(qc: QColor, amt=1.12):
    h, s, v, a = qc.getHsv()
    v = min(255, int(v * amt))
    return QColor.fromHsv(h, s, v, a)


def _darker(qc: QColor, amt=0.88):
    h, s, v, a = qc.getHsv()
    v = max(0, int(v * amt))
    return QColor.fromHsv(h, s, v, a)


class DynamicColor:
    def __init__(self, hue, chroma, tone):
        self.h = hue
        self.c = chroma
        self.t = tone

    @staticmethod
    def from_seed(seed_hex: str):
        seed = QColor(seed_hex)
        h, c, t = _rgb_to_hct(seed.red(), seed.green(), seed.blue())
        return DynamicColor(h, c, t)

    @staticmethod
    def from_hct(h, c, t):
        return DynamicColor(h, c, t)

    @staticmethod
    def from_image(img_path: str):
        img = QImage(img_path)
        if img.isNull():
            return DynamicColor.from_seed("#6750A4")
        img = img.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        buckets = {}
        for y in range(img.height()):
            for x in range(img.width()):
                p = img.pixelColor(x, y)
                if p.alpha() < 128:
                    continue
                r, g, b = p.red(), p.green(), p.blue()
                mx, mn = max(r, g, b), min(r, g, b)
                if mx - mn < 12:
                    continue
                if mx < 30 or mn > 225:
                    continue
                key = (r >> 4, g >> 4, b >> 4)
                buckets[key] = buckets.get(key, 0) + 1
        if not buckets:
            return DynamicColor.from_seed("#6750A4")
        best = max(buckets.items(), key=lambda kv: kv[1])[0]
        r = (best[0] << 4) | 8
        g = (best[1] << 4) | 8
        b = (best[2] << 4) | 8
        h, c, t = _rgb_to_hct(r, g, b)
        c = min(80, max(40, c))
        return DynamicColor(h, c, t)

    def _tone(self, tone, chroma=None):
        c = self.c if chroma is None else chroma
        r, g, b = _hct_to_rgb(self.h, c, tone)
        return _hex(r, g, b)

    def light_scheme(self):
        P = self._tone
        return {
            "primary":              P(40),
            "on_primary":           P(100, 5),
            "primary_container":    P(90),
            "on_primary_container": P(10),
            "secondary":            P(40, self.c * 0.4),
            "on_secondary":         P(100, 5),
            "secondary_container":  P(90, self.c * 0.4),
            "on_secondary_container":P(10, self.c * 0.4),
            "tertiary":             P(40, (self.c + 60) % 360 / 3 + 20),
            "on_tertiary":          P(100, 5),
            "tertiary_container":   P(90, (self.c + 60) % 360 / 3 + 20),
            "on_tertiary_container":P(10, (self.c + 60) % 360 / 3 + 20),
            "error":                "#B3261E",
            "on_error":             "#FFFFFF",
            "error_container":      "#F9DEDC",
            "on_error_container":   "#410E0B",
            "background":           P(98, 4),
            "on_background":        P(10),
            "surface":              P(98, 4),
            "on_surface":           P(10),
            "surface_variant":      P(90, 8),
            "on_surface_variant":   P(30, 8),
            "surface_container_lowest":  P(100, 3),
            "surface_container_low":     P(96, 4),
            "surface_container":         P(94, 4),
            "surface_container_high":    P(92, 5),
            "surface_container_highest": P(90, 5),
            "surface_dim":          P(87, 4),
            "surface_bright":       P(98, 4),
            "outline":              P(50, 8),
            "outline_variant":      P(80, 8),
            "scrim":                "#000000",
            "inverse_surface":      P(20),
            "inverse_on_surface":   P(95, 4),
            "inverse_primary":      P(80),
            "shadow":               "#000000",
        }

    def dark_scheme(self):
        P = self._tone
        return {
            "primary":              P(80),
            "on_primary":           P(20),
            "primary_container":    P(30),
            "on_primary_container": P(90),
            "secondary":            P(80, self.c * 0.4),
            "on_secondary":         P(20, self.c * 0.4),
            "secondary_container":  P(30, self.c * 0.4),
            "on_secondary_container":P(90, self.c * 0.4),
            "tertiary":             P(80, (self.c + 60) % 360 / 3 + 20),
            "on_tertiary":          P(20, (self.c + 60) % 360 / 3 + 20),
            "tertiary_container":   P(30, (self.c + 60) % 360 / 3 + 20),
            "on_tertiary_container":P(90, (self.c + 60) % 360 / 3 + 20),
            "error":                "#F2B8B5",
            "on_error":             "#601410",
            "error_container":      "#8C1D18",
            "on_error_container":   "#F9DEDC",
            "background":           P(6, 4),
            "on_background":        P(90),
            "surface":              P(6, 4),
            "on_surface":           P(90),
            "surface_variant":      P(30, 8),
            "on_surface_variant":   P(80, 8),
            "surface_container_lowest":  P(4, 3),
            "surface_container_low":     P(10, 4),
            "surface_container":         P(12, 4),
            "surface_container_high":    P(17, 5),
            "surface_container_highest": P(22, 5),
            "surface_dim":          P(6, 4),
            "surface_bright":       P(24, 5),
            "outline":              P(60, 8),
            "outline_variant":      P(30, 8),
            "scrim":                "#000000",
            "inverse_surface":      P(90),
            "inverse_on_surface":   P(20),
            "inverse_primary":      P(40),
            "shadow":               "#000000",
        }


class M3:
    _dark = False
    _scheme_light = None
    _scheme_dark = None
    _hct = None

    PRESETS = [
        ("默认紫", "#6750A4"),
        ("海洋蓝", "#0B6BCB"),
        ("森野绿", "#1E7A4B"),
        ("活力橙", "#C4501F"),
        ("樱花粉", "#B3398C"),
        ("薄荷青", "#00838F"),
    ]

    @classmethod
    def init(cls, seed_hex="#6750A4"):
        dc = DynamicColor.from_seed(seed_hex)
        cls._hct = (dc.h, dc.c, dc.t)
        cls._scheme_light = dc.light_scheme()
        cls._scheme_dark = dc.dark_scheme()

    @classmethod
    def init_from_hct(cls, h, c, t):
        dc = DynamicColor.from_hct(h, c, t)
        cls._hct = (h, c, t)
        cls._scheme_light = dc.light_scheme()
        cls._scheme_dark = dc.dark_scheme()

    @classmethod
    def init_from_image(cls, img_path):
        dc = DynamicColor.from_image(img_path)
        cls._hct = (dc.h, dc.c, dc.t)
        cls._scheme_light = dc.light_scheme()
        cls._scheme_dark = dc.dark_scheme()
        return cls._hct

    @classmethod
    def get_hct(cls):
        return cls._hct

    @classmethod
    def set_mode(cls, mode):
        cls._dark = (mode == "dark")

    @classmethod
    def is_dark(cls):
        return cls._dark

    @classmethod
    def c(cls, name):
        if cls._scheme_light is None:
            cls.init()
        return QColor(cls._scheme_dark[name] if cls._dark else cls._scheme_light[name])


def font_family():
    if platform.system() == "Windows":
        return "Segoe UI"
    if platform.system() == "Darwin":
        return "SF Pro Text"
    return "Noto Sans"


def mono_family():
    if platform.system() == "Windows":
        return "Cascadia Mono"
    if platform.system() == "Darwin":
        return "Menlo"
    return "Noto Sans Mono"


# ============================================================
# 样式
# ============================================================

def build_stylesheet() -> str:
    P = M3.c
    return f"""
    * {{
        font-family: "{font_family()}";
        font-size: 13px;
        outline: none;
    }}
    QWidget {{
        background: {P('background').name()};
        color: {P('on_background').name()};
    }}
    QMainWindow, QDialog {{
        background: {P('background').name()};
    }}
    QLabel {{ background: transparent; color: {P('on_surface').name()}; }}
    QLabel[class="title-large"] {{
        font-size: 22px; font-weight: 600; color: {P('on_surface').name()};
    }}
    QLabel[class="title-medium"] {{
        font-size: 14px; font-weight: 600; color: {P('on_surface_variant').name()};
    }}
    QLabel[class="body-small"] {{
        font-size: 11px; color: {P('on_surface_variant').name()};
    }}

    QToolBar {{
        background: {P('surface_container_low').name()};
        border: none;
        border-radius: 18px;
        padding: 6px 10px;
        spacing: 8px;
        margin: 6px 10px 0 10px;
    }}
    QToolBar::separator {{
        background: {P('outline_variant').name()};
        width: 1px;
        margin: 6px 4px;
    }}
    QToolButton {{
        background: transparent;
        color: {P('on_surface').name()};
        border: 1px solid {P('outline_variant').name()};
        border-radius: 16px;
        padding: 6px 16px;
        font-weight: 500;
        font-size: 13px;
    }}
    QToolButton:hover {{
        background: {P('surface_container_highest').name()};
    }}
    QToolButton:pressed {{
        background: {P('secondary_container').name()};
    }}
    QToolButton:checked {{
        background: {P('secondary_container').name()};
        color: {P('on_secondary_container').name()};
        border-color: transparent;
    }}

    QPushButton {{
        background: {P('primary').name()};
        color: {P('on_primary').name()};
        border: none;
        border-radius: 20px;
        padding: 8px 22px;
        font-weight: 500;
        font-size: 13px;
        min-height: 40px;
    }}
    QPushButton:hover {{ background: {_lighter(P('primary')).name()}; }}
    QPushButton:pressed {{ background: {_darker(P('primary')).name()}; }}

    QPushButton[variant="tonal"] {{
        background: {P('secondary_container').name()};
        color: {P('on_secondary_container').name()};
    }}
    QPushButton[variant="tonal"]:hover {{
        background: {_lighter(P('secondary_container')).name()};
    }}
    QPushButton[variant="outlined"] {{
        background: transparent;
        color: {P('primary').name()};
        border: 1px solid {P('outline').name()};
    }}
    QPushButton[variant="outlined"]:hover {{
        background: {P('primary').name()}1A;
    }}
    QPushButton[variant="text"] {{
        background: transparent;
        color: {P('primary').name()};
        padding: 8px 14px;
    }}
    QPushButton[variant="text"]:hover {{
        background: {P('primary').name()}1A;
    }}
    QPushButton[variant="danger"] {{
        background: {P('error').name()};
        color: {P('on_error').name()};
    }}

    QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser {{
        background: {P('surface_container_high').name()};
        color: {P('on_surface').name()};
        border: none;
        border-radius: 14px;
        padding: 10px 14px;
        selection-background-color: {P('primary').name()};
        selection-color: {P('on_primary').name()};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        background: {P('surface_container_highest').name()};
    }}

    QTabWidget::pane {{
        background: {P('surface_container_low').name()};
        border: none; border-radius: 18px; top: -1px;
    }}
    QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {P('on_surface_variant').name()};
        border: none;
        border-bottom: 3px solid transparent;
        padding: 10px 20px;
        margin-right: 2px;
        font-weight: 500; font-size: 13px; min-width: 80px;
    }}
    QTabBar::tab:hover {{
        background: {P('surface_container_high').name()};
        border-top-left-radius: 14px;
        border-top-right-radius: 14px;
    }}
    QTabBar::tab:selected {{
        color: {P('primary').name()};
        border-bottom: 3px solid {P('primary').name()};
        border-top-left-radius: 14px;
        border-top-right-radius: 14px;
    }}

    QTreeWidget {{
        background: {P('surface_container_low').name()};
        color: {P('on_surface').name()};
        border: none; border-radius: 14px; padding: 6px;
    }}
    QTreeWidget::item {{ padding: 6px 4px; border-radius: 10px; }}
    QTreeWidget::item:hover {{ background: {P('surface_container_high').name()}; }}
    QTreeWidget::item:selected {{
        background: {P('secondary_container').name()};
        color: {P('on_secondary_container').name()};
    }}
    QHeaderView::section {{
        background: transparent;
        color: {P('on_surface_variant').name()};
        border: none; padding: 6px; font-weight: 600; font-size: 11px;
    }}

    QListWidget {{
        background: {P('surface_container_high').name()};
        color: {P('on_surface').name()};
        border: 1px solid {P('outline_variant').name()};
        border-radius: 14px; padding: 6px; outline: none;
    }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 10px; }}
    QListWidget::item:hover {{ background: {P('surface_container_highest').name()}; }}
    QListWidget::item:selected {{
        background: {P('secondary_container').name()};
        color: {P('on_secondary_container').name()};
    }}

    QScrollBar:vertical {{
        background: transparent; width: 12px; margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {P('outline_variant').name()};
        border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {P('outline').name()}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{
        background: transparent; height: 12px; margin: 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {P('outline_variant').name()};
        border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

    QComboBox {{
        background: {P('surface_container_high').name()};
        color: {P('on_surface').name()};
        border: 1px solid {P('outline_variant').name()};
        border-radius: 14px; padding: 8px 14px; min-height: 24px;
    }}
    QComboBox:hover {{ background: {P('surface_container_highest').name()}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{
        background: {P('surface_container_high').name()};
        color: {P('on_surface').name()};
        border: 1px solid {P('outline_variant').name()};
        border-radius: 14px; padding: 4px;
        selection-background-color: {P('secondary_container').name()};
        selection-color: {P('on_secondary_container').name()};
    }}

    QSplitter::handle {{ background: transparent; width: 6px; height: 6px; }}
    QSplitter::handle:hover {{ background: {P('primary').name()}55; border-radius: 3px; }}

    QStatusBar {{
        background: {P('surface_container_low').name()};
        color: {P('on_surface_variant').name()};
        border: none; border-radius: 14px; padding: 6px 12px; font-size: 12px;
        margin: 0 10px 6px 10px;
    }}
    QStatusBar::item {{ border: none; }}

    QFrame[class="bottom-sheet"] {{
        background: {P('surface_container_high').name()};
        border-top-left-radius: 28px;
        border-top-right-radius: 28px;
        border: 1px solid {P('outline_variant').name()};
        border-bottom: none;
    }}
    QFrame[class="sheet-handle"] {{
        background: {P('outline_variant').name()};
        border-radius: 2px;
        min-height: 4px; max-height: 4px;
    }}

    QFrame[class="card"] {{
        background: {P('surface_container_low').name()};
        border-radius: 18px;
        border: 1px solid {P('outline_variant').name()};
    }}

    QToolTip {{
        background: {P('inverse_surface').name()};
        color: {P('inverse_on_surface').name()};
        border: none; border-radius: 10px; padding: 6px 10px;
    }}

    QMenu {{
        background: {P('surface_container_high').name()};
        color: {P('on_surface').name()};
        border: 1px solid {P('outline_variant').name()};
        border-radius: 14px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 20px;
        border-radius: 10px;
    }}
    QMenu::item:selected {{
        background: {P('secondary_container').name()};
        color: {P('on_secondary_container').name()};
    }}
    QMenu::separator {{
        height: 1px;
        background: {P('outline_variant').name()};
        margin: 4px 10px;
    }}

    QCheckBox {{ color: {P('on_surface').name()}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 4px;
        border: 2px solid {P('outline').name()};
        background: transparent;
    }}
    QCheckBox::indicator:checked {{
        background: {P('primary').name()};
        border-color: {P('primary').name()};
    }}
    """


# ============================================================
# 语法高亮
# ============================================================

class PythonSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []
        dark = M3.is_dark()

        self.triple_string_format = QTextCharFormat()
        self.triple_string_format.setForeground(QColor("#A5D6A7" if dark else "#2E7D32"))
        self.triple_single_pattern = QRegularExpression(r"'''[^']*(?:'[^']|'[^'])*'''")
        self.triple_double_pattern = QRegularExpression(r'"""[^"]*(?:"[^"]|"[^"]")*"""')

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#A5D6A7" if dark else "#2E7D32"))
        self.highlighting_rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), string_format))
        self.highlighting_rules.append((QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), string_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#9E9E9E" if dark else "#757575"))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append((QRegularExpression(r'#.*'), comment_format))

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#CE93D8" if dark else "#7B1FA2"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        for word in keyword.kwlist:
            self.highlighting_rules.append(
                (QRegularExpression(r'\b' + re.escape(word) + r'\b'), keyword_format))

        builtin_format = QTextCharFormat()
        builtin_format.setForeground(QColor("#90CAF9" if dark else "#1565C0"))
        builtins_list = [name for name in dir(builtins) if not name.startswith('_')]
        for word in builtins_list:
            self.highlighting_rules.append(
                (QRegularExpression(r'\b' + re.escape(word) + r'\b'), builtin_format))

        bool_format = QTextCharFormat()
        bool_format.setForeground(QColor("#EF9A9A" if dark else "#C62828"))
        bool_format.setFontWeight(QFont.Weight.Bold)
        for word in ['True', 'False', 'None']:
            self.highlighting_rules.append(
                (QRegularExpression(r'\b' + re.escape(word) + r'\b'), bool_format))

        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#FFB74D" if dark else "#E65100"))
        self.highlighting_rules.append((QRegularExpression(r'\b\d+\b'), number_format))
        self.highlighting_rules.append((QRegularExpression(r'\b\d+\.\d+\b'), number_format))

        function_format = QTextCharFormat()
        function_format.setForeground(QColor("#80CBC4" if dark else "#00695C"))
        builtins_pattern = '|'.join(re.escape(name) for name in builtins_list)
        self.highlighting_rules.append((
            QRegularExpression(r'\b(?!(?:' + builtins_pattern + r')\b)\w+(?=\()'),
            function_format))

        class_format = QTextCharFormat()
        class_format.setForeground(QColor("#F48FB1" if dark else "#AD1457"))
        class_format.setFontWeight(QFont.Weight.Bold)
        self.highlighting_rules.append((QRegularExpression(r'(?<=\bclass\s+)\w+'), class_format))

        decorator_format = QTextCharFormat()
        decorator_format.setForeground(QColor("#FFCC80" if dark else "#EF6C00"))
        self.highlighting_rules.append((QRegularExpression(r'@\w+'), decorator_format))

        import_format = QTextCharFormat()
        import_format.setForeground(QColor("#B39DDB" if dark else "#4527A0"))
        self.highlighting_rules.append((QRegularExpression(r'(?<=\bimport\s+)\w+'), import_format))
        self.highlighting_rules.append((QRegularExpression(r'(?<=\bfrom\s+)\w+'), import_format))

        operator_format = QTextCharFormat()
        operator_format.setForeground(QColor("#BDBDBD" if dark else "#616161"))
        for pattern in [r'\+\+', r'--', r'\+', r'-', r'\*', r'/', r'%',
                        r'=', r'==', r'!=', r'<', r'>', r'<=', r'>=',
                        r'\+=', r'-=', r'\*=', r'/=', r'%=',
                        r'\.', r',', r':', r';',
                        r'\(', r'\)', r'\[', r'\]', r'\{', r'\}']:
            self.highlighting_rules.append((QRegularExpression(pattern), operator_format))
        for pattern in [r'\band\b', r'\bor\b', r'\bnot\b', r'\bin\b', r'\bis\b']:
            self.highlighting_rules.append((QRegularExpression(pattern), operator_format))

    def highlightBlock(self, text):
        for pattern, fmt in [(self.triple_single_pattern, self.triple_string_format),
                             (self.triple_double_pattern, self.triple_string_format)]:
            m = pattern.match(text)
            while m.hasMatch():
                s = m.capturedStart()
                l = m.capturedLength()
                self.setFormat(s, l, fmt)
                m = pattern.match(text, s + l)

        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s = m.capturedStart()
                l = m.capturedLength()
                skip = False
                for i in range(s, s + l):
                    if self.format(i).foreground().color() == self.triple_string_format.foreground().color():
                        skip = True
                        break
                if not skip:
                    self.setFormat(s, l, fmt)


# ============================================================
# 补全
# ============================================================

class CodeCompleter:
    def __init__(self):
        self.keywords = set(keyword.kwlist)
        self.builtins = set(dir(builtins))
        self.common_modules = {'os', 'sys', 're', 'json', 'time', 'datetime', 'math', 'random', 'requests'}
        self.user_definitions = set()
        self.module_members = {}

    def get_completions(self, text, prefix):
        if not prefix:
            return []
        completions = []
        if '.' in prefix:
            parts = prefix.split('.')
            if len(parts) == 2:
                mp, mpre = parts
                members = self.get_module_members(mp, text)
                completions.extend([f"{mp}.{m}" for m in members if m.startswith(mpre)])
                return completions[:15]
        completions.extend([kw for kw in self.keywords if kw.lower().startswith(prefix.lower())])
        completions.extend([f for f in self.builtins if f.lower().startswith(prefix.lower())])
        completions.extend([m for m in self.common_modules if m.lower().startswith(prefix.lower())])
        completions.extend([d for d in self.user_definitions if d.lower().startswith(prefix.lower())])
        return list(set(completions))[:15]

    def get_module_members(self, module_name, text):
        if module_name in self.module_members:
            return self.module_members[module_name]
        members = []
        try:
            import_pattern = rf'import\s+{module_name}|\s+from\s+{module_name}\s+import'
            if re.search(import_pattern, text):
                try:
                    module = __import__(module_name)
                    members = [a for a in dir(module) if not a.startswith('_')]
                except Exception:
                    pass
        except Exception:
            pass
        if module_name == 'time' and not members:
            members = ['sleep', 'time', 'ctime', 'gmtime', 'localtime', 'mktime', 'strftime', 'strptime']
        elif module_name == 'os' and not members:
            members = ['path', 'listdir', 'mkdir', 'remove', 'rename', 'system']
        elif module_name == 'sys' and not members:
            members = ['argv', 'exit', 'path', 'stdout', 'stderr', 'stdin']
        self.module_members[module_name] = members
        return members

    def update_user_definitions(self, text):
        self.user_definitions.clear()
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            self.user_definitions.update(re.findall(r'def\s+(\w+)\s*\(', line))
            self.user_definitions.update(re.findall(r'class\s+(\w+)', line))
            self.user_definitions.update(re.findall(r'(?:^|\s)(\w+)\s*=\s*', line))
            self.user_definitions.update(re.findall(r'for\s+(\w+)\s+in\s+', line))
            for params in re.findall(r'def\s+\w+\s*\(([^)]*)\)', line):
                for param in params.split(','):
                    param = param.strip()
                    if param:
                        name = param.split('=')[0].strip()
                        if name:
                            self.user_definitions.add(name)


class CompletionPopup(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup |
                            Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(300)
        self.setFixedHeight(220)
        self.setStyleSheet(f"""
            QListWidget {{
                background: {M3.c('surface_container_high').name()};
                border: 1px solid {M3.c('outline_variant').name()};
                border-radius: 14px;
                font-family: "{mono_family()}";
                font-size: 12px;
                color: {M3.c('on_surface').name()};
                padding: 6px; outline: none;
            }}
            QListWidget::item {{ padding: 6px 10px; border-radius: 10px; }}
            QListWidget::item:selected {{
                background: {M3.c('secondary_container').name()};
                color: {M3.c('on_secondary_container').name()};
            }}
            QListWidget::item:hover {{
                background: {M3.c('surface_container_highest').name()};
            }}
        """)


# ============================================================
# 错误检查（PyCharm 风格实时检查，纯标准库实现）
# ============================================================

import ast
from importlib.machinery import PathFinder


class _UndefinedNameVisitor(ast.NodeVisitor):
    """收集定义/使用/导入信息，并做各类静态检查。"""

    def __init__(self, out):
        self.out = out                      # 直接追加 (line, col, severity, message)
        self.defined = set()
        self.used = []                      # [(name, lineno, col_offset)]
        self.imports = []                   # [(绑定名, lineno, col_offset)]
        self.import_calls = []              # ('import', 名称, line, col) / ('from', 模块, [名...], line, col)
        self.star_modules = []
        self.module_bindings = {}           # 绑定名 -> 模块名（用于模块属性检查）
        self.stored = set()                 # 被赋值过的名字

    # ---- 名称与定义 ----
    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Load, ast.Del)):
            self.used.append((node.id, node.lineno, node.col_offset))
        else:
            self.defined.add(node.id)
            self.stored.add(node.id)
        self.generic_visit(node)

    def visit_arg(self, node):
        self.defined.add(node.arg)

    def visit_FunctionDef(self, node):
        self.defined.add(node.name)
        self._check_mutable_defaults(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.defined.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node):
        self.defined.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node):
        if node.name:
            self.defined.add(node.name)
        self.generic_visit(node)

    # ---- 导入 ----
    def visit_Import(self, node):
        for alias in node.names:
            bind = (alias.asname or alias.name).split('.')[0]
            self.defined.add(bind)
            self.imports.append((bind, node.lineno, node.col_offset))
            self.import_calls.append(('import', alias.name, node.lineno, node.col_offset))
            self.module_bindings[bind] = (alias.name if alias.asname
                                          else alias.name.split('.')[0])

    def visit_ImportFrom(self, node):
        if node.module and any(a.name == '*' for a in node.names):
            self.star_modules.append(node.module)
            return
        for alias in node.names:
            bind = alias.asname or alias.name
            self.defined.add(bind)
            self.imports.append((bind, node.lineno, node.col_offset))
        if not node.level and node.module:
            self.import_calls.append(('from', node.module,
                                      [a.name for a in node.names],
                                      node.lineno, node.col_offset))
            for alias in node.names:
                # 只有当该名是子模块时才会在 sys.modules 命中，否则不参与属性检查
                self.module_bindings[alias.asname or alias.name] = \
                    f"{node.module}.{alias.name}"

    # ---- 各类静态检查 ----
    def visit_Compare(self, node):
        operands = [node.left] + node.comparators
        for i, op in enumerate(node.ops):
            left, right = operands[i], operands[i + 1]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                if (isinstance(left, ast.Constant) and left.value is None) or \
                        (isinstance(right, ast.Constant) and right.value is None):
                    self.out.append((node.lineno, node.col_offset, 'warning',
                                     "与 None 比较应使用 'is' / 'is not'"))
            elif isinstance(op, (ast.Is, ast.IsNot)):
                for operand in (left, right):
                    if isinstance(operand, ast.Constant) and operand.value is not None:
                        self.out.append((node.lineno, node.col_offset, 'warning',
                                         "'is' 比较字面量不可靠，应使用 '=='"))
                        break
        self.generic_visit(node)

    def visit_Dict(self, node):
        seen = set()
        for k in node.keys:
            if k is None:   # ** 展开项
                continue
            if isinstance(k, ast.Constant):
                key = (type(k.value).__name__, k.value)
                if key in seen:
                    self.out.append((k.lineno, k.col_offset, 'warning',
                                     f"字典中存在重复的键 {k.value!r}"))
                seen.add(key)
        self.generic_visit(node)

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self.out.append((node.lineno, node.col_offset, 'warning',
                             "assert 后是元组，条件永远为真"))
        self.generic_visit(node)

    def _check_mutable_defaults(self, node):
        defaults = list(node.args.defaults) + \
            [d for d in node.args.kw_defaults if d is not None]
        for d in defaults:
            bad = isinstance(d, (ast.List, ast.Dict, ast.Set))
            if not bad and isinstance(d, ast.Call) and isinstance(d.func, ast.Name) \
                    and d.func.id in ('list', 'dict', 'set'):
                bad = True
            if bad:
                self.out.append((d.lineno, d.col_offset, 'warning',
                                 "可变对象作为默认参数，多次调用间会共享"))

    def visit_MatchAs(self, node):
        if node.name:
            self.defined.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node):
        if node.name:
            self.defined.add(node.name)

    def visit_MatchMapping(self, node):
        if node.rest:
            self.defined.add(node.rest)
        self.generic_visit(node)


class _ModuleResolver:
    """静态解析模块是否存在（按文件路径搜索，不执行被检查代码）。"""

    MAX_SOURCE_SIZE = 512 * 1024

    def __init__(self, extra_paths=None):
        self.search_paths = []
        for p in list(extra_paths or []) + sys.path:
            if p and p not in self.search_paths:
                self.search_paths.append(p)
        self._module_cache = {}
        self._names_cache = {}

    def module_exists(self, dotted):
        if not dotted:
            return True
        if dotted in self._module_cache:
            return self._module_cache[dotted]
        result = self._exists_impl(dotted)
        self._module_cache[dotted] = result
        return result

    def _exists_impl(self, dotted):
        parts = dotted.split('.')
        top = parts[0]
        cur_spec = None
        if top in sys.modules or top in sys.builtin_module_names:
            cur_name = top
        else:
            try:
                cur_spec = PathFinder.find_spec(top, self.search_paths)
            except Exception:
                return True  # 无法判断时不误报
            if cur_spec is None:
                try:
                    import importlib.util
                    cur_spec = importlib.util.find_spec(top)
                except Exception:
                    return True
                if cur_spec is None:
                    return False
            cur_name = top
        # 逐级解析子模块
        for part in parts[1:]:
            nxt_name = f"{cur_name}.{part}"
            if nxt_name in sys.modules:
                cur_name, cur_spec = nxt_name, None
                continue
            parent_mod = sys.modules.get(cur_name)
            if parent_mod is not None:
                if hasattr(parent_mod, part):
                    cur_name, cur_spec = nxt_name, None
                    continue
                paths = list(getattr(parent_mod, '__path__', []) or [])
                if not paths:
                    return False  # 已加载的普通模块不会有该子模块
            elif cur_spec is not None and cur_spec.submodule_search_locations:
                paths = list(cur_spec.submodule_search_locations)
            else:
                return True  # 无法继续静态解析，不误报
            try:
                nxt = PathFinder.find_spec(nxt_name, paths)
            except Exception:
                return True
            if nxt is None:
                return False
            cur_name, cur_spec = nxt_name, nxt
        return True

    def can_import_name(self, module_dotted, name):
        mod = sys.modules.get(module_dotted)
        if mod is not None:
            if hasattr(mod, name):
                return True
            paths = list(getattr(mod, '__path__', []) or [])
            if paths:
                try:
                    if PathFinder.find_spec(f"{module_dotted}.{name}", paths):
                        return True
                except Exception:
                    return True
            return False
        # 未加载：静态解析源文件（不执行模块代码）
        try:
            spec = self._static_spec(module_dotted)
        except Exception:
            return True
        if spec is None:
            return True  # 解析不了，交给 module_exists 处理
        origin = getattr(spec, 'origin', None)
        if not origin or not origin.endswith('.py'):
            return True  # 二进制/内置模块，无法静态判断
        names = self._static_names(origin)
        if names is None:
            return True
        if name in names or '__getattr__' in names:
            return True
        for d in list(spec.submodule_search_locations or []):
            if os.path.exists(os.path.join(d, name + '.py')) or \
                    os.path.exists(os.path.join(d, name, '__init__.py')):
                return True
        return False

    def _static_spec(self, dotted):
        parts = dotted.split('.')
        try:
            spec = PathFinder.find_spec(parts[0], self.search_paths)
        except Exception:
            return None
        cur = parts[0]
        for part in parts[1:]:
            if spec is None or not spec.submodule_search_locations:
                return spec
            try:
                spec = PathFinder.find_spec(f"{cur}.{part}",
                                            list(spec.submodule_search_locations))
            except Exception:
                return None
            cur = f"{cur}.{part}"
        return spec

    def _static_names(self, path):
        """解析一个 .py 源文件的顶层可导入名（静态、带缓存）。"""
        if path in self._names_cache:
            return self._names_cache[path]
        names = None
        try:
            if os.path.getsize(path) <= self.MAX_SOURCE_SIZE:
                src = None
                for enc in ('utf-8', 'gbk', 'latin-1'):
                    try:
                        with open(path, 'r', encoding=enc) as f:
                            src = f.read()
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                if src is not None:
                    tree = ast.parse(src)
                    names = set()
                    stack = list(tree.body)
                    while stack:
                        st = stack.pop()
                        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                                           ast.ClassDef)):
                            names.add(st.name)
                        elif isinstance(st, ast.Assign):
                            for t in st.targets:
                                for n in ast.walk(t):
                                    if isinstance(n, ast.Name):
                                        names.add(n.id)
                            val = st.value
                            if any(isinstance(t, ast.Name) and t.id == '__all__'
                                   for t in st.targets) and \
                                    isinstance(val, (ast.List, ast.Tuple)):
                                for e in val.elts:
                                    if isinstance(e, ast.Constant) and \
                                            isinstance(e.value, str):
                                        names.add(e.value)
                        elif isinstance(st, ast.AnnAssign) and \
                                isinstance(st.target, ast.Name):
                            names.add(st.target.id)
                        elif isinstance(st, ast.Import):
                            for a in st.names:
                                names.add((a.asname or a.name).split('.')[0])
                        elif isinstance(st, ast.ImportFrom):
                            for a in st.names:
                                if a.name != '*':
                                    names.add(a.asname or a.name)
                        elif isinstance(st, ast.If):
                            stack.extend(st.body)
                            stack.extend(st.orelse)
                        elif isinstance(st, ast.Try):
                            stack.extend(st.body)
                            stack.extend(st.orelse)
                            stack.extend(st.finalbody)
                            for h in st.handlers:
                                stack.extend(h.body)
                        elif isinstance(st, (ast.With, ast.AsyncWith)):
                            stack.extend(st.body)
        except Exception:
            names = None
        self._names_cache[path] = names
        return names


class PythonChecker:
    """轻量级 Python 检查器（无需第三方库）:
    - error   语法错误 / 导入了不存在的模块
    - warning 未定义的名称、Tab与空格混用、无法从模块导入指定名、
              模块属性不存在、重复定义、不可达代码、字典重复键、
              assert 元组、用 ==/!= 比较 None、is 比较字面量、可变默认参数
    - info    导入未使用
    返回 [(行号(1基), 列(0基), 级别, 消息), ...]
    """

    MAX_CHECK_SIZE = 300 * 1024  # 超大文件跳过，避免卡顿

    def __init__(self):
        self.builtin_names = set(dir(builtins))
        self.soft_names = {'self', 'cls', '_'}
        self._resolvers = {}

    # ---- 对外入口 ----
    def check(self, code: str, file_path=None, extra_paths=None):
        issues = []
        if not code or len(code) > self.MAX_CHECK_SIZE:
            return issues

        # 1) Tab / 空格缩进混用
        for idx, line in enumerate(code.split('\n'), start=1):
            stripped = line.lstrip()
            if not stripped:
                continue
            lead = line[:len(line) - len(stripped)]
            if '\t' in lead and ' ' in lead:
                issues.append((idx, 0, 'warning', '缩进中混用了 Tab 和空格'))

        # 2) 语法检查
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            line = e.lineno or 1
            col = max(0, (e.offset or 1) - 1)
            issues.append((line, col, 'error', f'语法错误: {e.msg}'))
            issues.sort(key=lambda x: (x[0], x[1]))
            return issues
        except (ValueError, RecursionError, MemoryError) as e:
            issues.append((1, 0, 'error', f'无法解析代码: {e}'))
            return issues

        # 3) 名称 / 导入 / 各类静态检查
        n0 = len(issues)
        v = _UndefinedNameVisitor(issues)
        try:
            v.visit(tree)
        except Exception:
            del issues[n0:]  # 访问器出错时丢弃可能不完整的结论

        # 3.1) 未定义名称 / 未使用导入
        try:
            allowed = self.builtin_names | self.soft_names | v.defined
            for mod in v.star_modules:
                m = sys.modules.get(mod)  # 仅解析已加载模块，避免副作用
                if m is not None:
                    allowed.update(n for n in dir(m) if not n.startswith('_'))
            for name, line, col in v.used:
                if name not in allowed:
                    issues.append((line, col, 'warning', f"未定义的名称 '{name}'"))
            used_names = {n for n, _, _ in v.used}
            for bind, line, col in v.imports:
                if bind not in used_names:
                    issues.append((line, col, 'info', f"导入未使用: '{bind}'"))
        except Exception:
            pass

        # 3.2) 单次遍历：条件导入收集 / 模块属性 / 重复定义 / 不可达代码
        cond_mods, cond_pairs = set(), set()
        catch_names = {'ImportError', 'ModuleNotFoundError', 'Exception',
                       'BaseException', 'FileNotFoundError'}
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    handled = False
                    for h in node.handlers:
                        t = h.type
                        if t is None:
                            handled = True
                            break
                        tnames = []
                        if isinstance(t, ast.Name):
                            tnames = [t.id]
                        elif isinstance(t, ast.Attribute):
                            tnames = [t.attr]
                        elif isinstance(t, ast.Tuple):
                            tnames = [e.id for e in t.elts
                                      if isinstance(e, ast.Name)]
                        if any(n in catch_names for n in tnames):
                            handled = True
                            break
                    if handled:
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Import):
                                for a in sub.names:
                                    cond_mods.add(a.name.split('.')[0])
                                    cond_mods.add(a.name)
                            elif isinstance(sub, ast.ImportFrom) and \
                                    not sub.level and sub.module:
                                cond_mods.add(sub.module)
                                for a in sub.names:
                                    cond_pairs.add((sub.module, a.name))
                if isinstance(node, ast.Attribute) and \
                        isinstance(node.value, ast.Name):
                    nm = node.value.id
                    if nm not in v.stored:  # 该名字被赋值过则可能不是模块本身
                        mapped = v.module_bindings.get(nm)
                        if mapped:
                            mod = sys.modules.get(mapped)
                            if mod is not None and not hasattr(mod, node.attr):
                                issues.append((node.lineno, node.col_offset,
                                               'warning',
                                               f"模块 '{mapped}' 中没有属性 "
                                               f"'{node.attr}'"))
                body = getattr(node, 'body', None)
                if isinstance(body, list) and body:
                    seen_defs = set()
                    dead = False
                    dead_reported = False
                    for st in body:
                        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                                           ast.ClassDef)):
                            if st.name in seen_defs:
                                issues.append((st.lineno, st.col_offset, 'warning',
                                               f"重复定义: '{st.name}'"))
                            seen_defs.add(st.name)
                        if not dead_reported:
                            if dead:
                                issues.append((st.lineno, st.col_offset, 'warning',
                                               '不可达的代码'))
                                dead_reported = True
                            elif isinstance(st, (ast.Return, ast.Break,
                                                 ast.Continue, ast.Raise)):
                                dead = True
        except Exception:
            pass

        # 4) 导入检查：模块是否存在 / 名称是否可导入
        try:
            if extra_paths is None and file_path:
                extra_paths = [os.path.dirname(os.path.abspath(file_path))]
            resolver = self._resolver_for(extra_paths)
            for item in v.import_calls:
                if item[0] == 'import':
                    _, name, line, col = item
                    if name.split('.')[0] in cond_mods:
                        continue
                    if not resolver.module_exists(name):
                        issues.append((line, col, 'error',
                                       f"没有名为 '{name}' 的模块"))
                else:
                    _, module, names, line, col = item
                    if module.split('.')[0] in cond_mods:
                        continue
                    if not resolver.module_exists(module):
                        issues.append((line, col, 'error',
                                       f"没有名为 '{module}' 的模块"))
                        continue
                    for nm in names:
                        if nm == '*' or (module, nm) in cond_pairs:
                            continue
                        if not resolver.can_import_name(module, nm):
                            issues.append((line, col, 'warning',
                                           f"无法从 '{module}' 导入 '{nm}'"))
        except Exception:
            pass

        issues.sort(key=lambda x: (x[0], x[1]))
        return issues

    def _resolver_for(self, extra_paths):
        key = tuple(extra_paths or ())
        r = self._resolvers.get(key)
        if r is None:
            r = _ModuleResolver(list(key))
            self._resolvers[key] = r
        return r


# ============================================================
# 代码编辑器
# ============================================================

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        f = QFont(mono_family(), 11)
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(f)
        self.setTabStopDistance(QFontMetricsF(f).horizontalAdvance(' ') * 4)
        self.highlighter = PythonSyntaxHighlighter(self.document())
        self.completion_popup = CompletionPopup(self)
        self.completion_popup.itemClicked.connect(self.apply_completion)
        self.completion_popup.hide()
        self.code_completer = CodeCompleter()
        self.textChanged.connect(self.on_text_changed)
        self.completion_timer = QTimer()
        self.completion_timer.setSingleShot(True)
        self.completion_timer.timeout.connect(self.check_for_completions)
        self.tab_just_used = False
        self.is_handling_indent = False

        # 错误检查（PyCharm 风格实时检查）
        self.setMouseTracking(True)
        self.error_checker = PythonChecker()
        self.issues = []
        self.check_timer = QTimer(self)
        self.check_timer.setSingleShot(True)
        self.check_timer.timeout.connect(self.run_error_check)

    def on_text_changed(self):
        self.completion_timer.stop()
        self.completion_timer.start(150)
        code = self.toPlainText()
        self.check_timer.stop()
        # 大文件加大防抖间隔，避免检查占用 UI
        self.check_timer.start(600 if len(code) < 60000 else 1200)
        self.code_completer.update_user_definitions(code)

    def check_for_completions(self):
        if not self.hasFocus() or self.tab_just_used:
            self.tab_just_used = False
            return
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        line_start = text.rfind('\n', 0, pos) + 1
        current_line = text[line_start:pos]
        word_start = 0
        for i in range(len(current_line) - 1, -1, -1):
            ch = current_line[i]
            if not (ch.isalnum() or ch == '_' or ch == '.'):
                word_start = i + 1
                break
        current_word = current_line[word_start:] if word_start < len(current_line) else ""
        if len(current_word) > 0:
            completions = self.code_completer.get_completions(text, current_word)
            if completions:
                self.show_completions(completions, cursor, current_word)
            else:
                self.completion_popup.hide()
        else:
            self.completion_popup.hide()

    def show_completions(self, completions, cursor, current_word):
        self.completion_popup.clear()
        filtered = [i for i in completions if i.lower().startswith(current_word.lower())]
        if not filtered:
            self.completion_popup.hide()
            return

        def sort_key(x):
            score = 0
            if x in self.code_completer.user_definitions: score += 1000
            if x in self.code_completer.keywords: score += 500
            if x in self.code_completer.builtins: score += 300
            return (-score, len(x), x.lower())

        filtered.sort(key=sort_key)
        for item in filtered[:10]:
            self.completion_popup.addItem(item)
        if self.completion_popup.count() > 0:
            r = self.cursorRect(cursor)
            gp = self.mapToGlobal(r.bottomLeft())
            sr = QApplication.primaryScreen().availableGeometry()
            if gp.x() + self.completion_popup.width() > sr.right():
                gp.setX(sr.right() - self.completion_popup.width())
            if gp.y() + self.completion_popup.height() > sr.bottom():
                gp.setY(gp.y() - self.completion_popup.height() - r.height())
            self.completion_popup.move(gp)
            self.completion_popup.show()
            self.completion_popup.setCurrentRow(0)
            self.setFocus()
        else:
            self.completion_popup.hide()

    def apply_completion(self, item):
        if not item:
            return
        completion = item.text()
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        ls = text.rfind('\n', 0, pos) + 1
        cl = text[ls:pos]
        ws = 0
        for i in range(len(cl) - 1, -1, -1):
            ch = cl[i]
            if not (ch.isalnum() or ch == '_' or ch == '.'):
                ws = i + 1
                break
        d = len(cl) - ws
        if d > 0:
            cursor.movePosition(QTextCursor.MoveOperation.Left,
                                QTextCursor.MoveMode.MoveAnchor, d)
            cursor.movePosition(QTextCursor.MoveOperation.Right,
                                QTextCursor.MoveMode.KeepAnchor, d)
        cursor.insertText(completion)
        self.setTextCursor(cursor)
        self.completion_popup.hide()
        self.setFocus()
        self.completion_timer.stop()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab:
            cursor = self.textCursor()
            text = self.toPlainText()
            pos = cursor.position()
            ls = text.rfind('\n', 0, pos) + 1
            cl = text[ls:pos]
            if cl.strip() == "":
                cursor.insertText("    ")
                self.tab_just_used = True
                event.accept()
                return

        if self.completion_popup.isVisible():
            if event.key() == Qt.Key.Key_Down:
                r = self.completion_popup.currentRow()
                if r < self.completion_popup.count() - 1:
                    self.completion_popup.setCurrentRow(r + 1)
                event.accept(); return
            elif event.key() == Qt.Key.Key_Up:
                r = self.completion_popup.currentRow()
                if r > 0:
                    self.completion_popup.setCurrentRow(r - 1)
                event.accept(); return
            elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                ci = self.completion_popup.currentItem()
                if ci: self.apply_completion(ci)
                event.accept(); return
            elif event.key() == Qt.Key.Key_Escape:
                self.completion_popup.hide()
                self.setFocus()
                event.accept(); return
            elif event.key() == Qt.Key.Key_Tab:
                ci = self.completion_popup.currentItem()
                if ci:
                    self.apply_completion(ci)
                    self.tab_just_used = True
                event.accept(); return

        if event.text() == ":" and not self.is_handling_indent:
            cursor = self.textCursor()
            text = self.toPlainText()
            pos = cursor.position()
            if not self.is_in_string_or_comment(text[:pos]):
                super().keyPressEvent(event)
                self.is_handling_indent = True
                QTimer.singleShot(10, self.handle_colon_indent)
                QTimer.singleShot(100, lambda: setattr(self, 'is_handling_indent', False))
                return

        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self.is_handling_indent:
                QTimer.singleShot(10, self.auto_indent)
        if event.text() and (event.text().isalnum() or event.text() == '_' or event.text() == '.'):
            self.completion_timer.stop()
            self.completion_timer.start(150)

    def auto_indent(self):
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        ls = text.rfind('\n', 0, pos - 1) + 1
        cl = text[ls:pos - 1] if pos > 0 else ""
        indent = ""
        for ch in cl:
            if ch in [' ', '\t']:
                indent += ch
            else:
                break
        if cl.strip().endswith(':') and not cl.strip().startswith('#'):
            indent += "    "
        if indent:
            cursor.insertText(indent)

    def is_in_string_or_comment(self, tb):
        if '#' in tb:
            lc = tb.rfind('#')
            ln = tb.rfind('\n')
            if lc > ln:
                return True
        sq = tb.count("'"); ts = tb.count("'''")
        dq = tb.count('"'); td = tb.count('"""')
        sq -= ts * 3
        dq -= td * 3
        if ts % 2 == 1 or td % 2 == 1:
            return True
        if sq % 2 == 1: return True
        if dq % 2 == 1: return True
        return False

    def handle_colon_indent(self):
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        if pos > 0 and text[pos - 1] == ":":
            ls = text.rfind('\n', 0, pos - 1) + 1
            cl = text[ls:pos - 1]
            nls = pos
            if nls < len(text):
                nn = text.find('\n', nls)
                if nn == -1: nn = len(text)
                nl = text[nls:nn]
                if nl.strip() != "":
                    self.is_handling_indent = False
                    return
            indent = ""
            for ch in cl:
                if ch in [' ', '\t']:
                    indent += ch
                else:
                    break
            indent += "    "
            cursor.insertText(f"\n{indent}")
        self.is_handling_indent = False

    # ---------------- 错误检查（PyCharm 风格） ----------------

    def _current_file_path(self):
        tab = self.parentWidget()
        return getattr(tab, 'file_path', None) if tab is not None else None

    def _check_is_python(self):
        fp = self._current_file_path()
        if fp:
            return os.path.splitext(fp)[1].lower() in ('.py', '.pyw')
        return True  # 未保存的新文件默认按 Python 检查

    def run_error_check(self):
        code = self.toPlainText()
        if not self._check_is_python() or not code.strip():
            self.issues = []
            self.update_error_highlights()
            return
        fp = self._current_file_path()
        extra = None
        if fp is None:
            sd = getattr(self.window(), 'save_dir', None)  # 未保存文件按保存目录解析模块
            if sd:
                extra = [sd]
        try:
            self.issues = self.error_checker.check(code, fp, extra)
        except Exception:
            self.issues = []
        self.update_error_highlights()

    def update_error_highlights(self):
        selections = []
        doc = self.document()
        for line, col, severity, msg in self.issues:
            block = doc.findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            text = block.text()
            col = max(0, min(col, len(text)))
            length = 0
            i = col
            while i < len(text) and (text[i].isalnum() or text[i] == '_'):
                length += 1
                i += 1
            if length == 0:
                length = max(1, min(len(text) - col, 30))
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            if severity == 'error':
                fmt.setUnderlineColor(QColor('#E53935'))
            elif severity == 'warning':
                fmt.setUnderlineColor(QColor('#FB8C00'))
            else:
                fmt.setUnderlineColor(QColor('#90A4AE'))
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            sel.cursor = QTextCursor(block)
            sel.cursor.setPosition(block.position() + col)
            sel.cursor.movePosition(QTextCursor.MoveOperation.Right,
                                    QTextCursor.MoveMode.KeepAnchor, length)
            selections.append(sel)
        self.setExtraSelections(selections)

    def issue_message_at_line(self, line):
        sev_name = {'error': '错误', 'warning': '警告', 'info': '提示'}
        return [f"{sev_name.get(s, s)}: {m}"
                for (l, c, s, m) in self.issues if l == line]

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.issues:
            return
        cursor = self.cursorForPosition(event.pos())
        msgs = self.issue_message_at_line(cursor.blockNumber() + 1)
        if msgs:
            QToolTip.showText(event.globalPosition().toPoint(),
                              '\n'.join(msgs), self)
        else:
            QToolTip.hideText()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.issues:
            return
        painter = QPainter(self.viewport())
        offset = self.contentOffset()
        color_map = {'error': QColor('#E53935'),
                     'warning': QColor('#FB8C00'),
                     'info': QColor('#90A4AE')}
        ev_top = event.rect().top()
        ev_bottom = event.rect().bottom()
        # 左侧问题标记条
        for line, col, severity, msg in self.issues:
            block = self.document().findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            top = round(self.blockBoundingGeometry(block).translated(offset).top())
            height = round(self.blockBoundingRect(block).height())
            if top + height < ev_top or top > ev_bottom:
                continue
            painter.fillRect(0, top + 1, 3, max(4, height - 2),
                             color_map.get(severity, color_map['info']))
        # 右上角问题统计
        errors = sum(1 for it in self.issues if it[2] == 'error')
        warns = sum(1 for it in self.issues if it[2] == 'warning')
        infos = sum(1 for it in self.issues if it[2] == 'info')
        if errors or warns or infos:
            parts = []
            if errors: parts.append(f"✗ {errors}")
            if warns: parts.append(f"⚠ {warns}")
            if infos: parts.append(f"ℹ {infos}")
            text = '  '.join(parts)
            painter.setPen(color_map['error'] if errors else color_map['warning'])
            fm = painter.fontMetrics()
            painter.drawText(self.viewport().width() - fm.horizontalAdvance(text) - 12,
                             fm.ascent() + 8, text)

    def mousePressEvent(self, event):
        if self.completion_popup.isVisible():
            self.completion_popup.hide()
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.completion_popup.hide()
        super().focusOutEvent(event)


# ============================================================
# 历史管理
# ============================================================

class HistoryManager:
    HISTORY_PATTERN = re.compile(r'^(?P<name>.+?)-第(?P<n>\d+)次记录\.old$')

    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir
        self.history_dir = os.path.join(workspace_dir, "History")
        if not os.path.exists(self.history_dir):
            os.makedirs(self.history_dir)

    def _base_name(self, file_path):
        if not file_path:
            return "untitled.py"
        bn = os.path.basename(file_path)
        name, ext = os.path.splitext(bn)
        if not ext:
            ext = '.py'
        return f"{name}{ext}"

    def _next_index(self, base_name):
        max_n = 0
        if not os.path.exists(self.history_dir):
            return 1
        for fname in os.listdir(self.history_dir):
            m = self.HISTORY_PATTERN.match(fname)
            if m and m.group('name') == base_name:
                try:
                    n = int(m.group('n'))
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
        return max_n + 1

    def save_history(self, file_path, content, encoding='utf-8'):
        base = self._base_name(file_path)
        n = self._next_index(base)
        hn = f"{base}-第{n}次记录.old"
        hp = os.path.join(self.history_dir, hn)
        try:
            with open(hp, 'w', encoding=encoding) as f:
                f.write(content)
            return hp
        except Exception:
            return None

    def list_history(self, file_path=None):
        result = []
        if not os.path.exists(self.history_dir):
            return result
        target_base = self._base_name(file_path) if file_path else None
        for fname in os.listdir(self.history_dir):
            m = self.HISTORY_PATTERN.match(fname)
            if not m:
                continue
            if target_base and m.group('name') != target_base:
                continue
            try:
                n = int(m.group('n'))
            except ValueError:
                n = 0
            result.append((os.path.join(self.history_dir, fname), n))
        result.sort(key=lambda x: (os.path.basename(x[0]), -x[1]))
        return result

    def list_all_bases(self):
        bases = set()
        if not os.path.exists(self.history_dir):
            return []
        for fname in os.listdir(self.history_dir):
            m = self.HISTORY_PATTERN.match(fname)
            if m:
                bases.add(m.group('name'))
        return sorted(bases)

    def load_history(self, hp):
        for enc in ['utf-8', 'gbk', 'utf-16']:
            try:
                with open(hp, 'r', encoding=enc) as f:
                    return f.read(), enc
            except UnicodeDecodeError:
                continue
        with open(hp, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), 'utf-8'

    def latest_history_content(self, file_path):
        entries = self.list_history(file_path)
        if not entries:
            return None
        latest_path, _ = entries[0]
        try:
            content, _ = self.load_history(latest_path)
            return content
        except Exception:
            return None


# ============================================================
# 文件浏览器
# ============================================================

EDITABLE_EXTS = {
    '.py', '.txt', '.md', '.json', '.xml', '.html', '.htm', '.css', '.js',
    '.ts', '.csv', '.log', '.ini', '.cfg', '.yaml', '.yml', '.old',
    '.bat', '.sh', '.ps1', '.c', '.h', '.cpp', '.hpp', '.java', '.go',
    '.rs', '.rb', '.php', '.toml', '.env', '.gitignore',
}

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.ico', '.svg'}


class WorkspaceBrowser(QWidget):
    file_double_clicked = pyqtSignal(str)
    status_message = pyqtSignal(str)

    def __init__(self, root_dir, history_dir, parent=None):
        super().__init__(parent)
        self.root_dir = root_dir
        self.history_dir = history_dir
        self.setMinimumWidth(280)

        self._clipboard = []
        self._trash_stack = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QLabel("工作区")
        header.setProperty("class", "title-medium")
        layout.addWidget(header)

        self.path_label = QLabel(root_dir)
        self.path_label.setProperty("class", "body-small")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)

        def _quick_btn(text, slot, variant=None):
            b = QPushButton(text)
            if variant:
                b.setProperty("variant", variant)
            b.setFixedHeight(36)
            b.setMinimumWidth(64)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        quick_row.addWidget(_quick_btn("剪切", self.cut_selected, "outlined"))
        quick_row.addWidget(_quick_btn("复制", self.copy_selected, "outlined"))
        quick_row.addWidget(_quick_btn("粘贴", self.paste_into_selected, "outlined"))
        quick_row.addWidget(_quick_btn("删除", self.delete_selected, "outlined"))
        quick_row.addWidget(_quick_btn("撤销删除", self.undo_delete, "outlined"))
        quick_row.addStretch()
        layout.addLayout(quick_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "大小"])
        self.tree.setColumnWidth(0, 180)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.itemClicked.connect(self.on_item_clicked)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        self.tree.installEventFilter(self)
        layout.addWidget(self.tree, 1)

        pl = QLabel("预览")
        pl.setProperty("class", "title-medium")
        layout.addWidget(pl)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont(mono_family(), 9))
        self.preview.setMaximumHeight(180)
        layout.addWidget(self.preview)

        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setProperty("variant", "outlined")
        refresh_btn.setFixedHeight(40)
        refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(refresh_btn)

        open_btn = QPushButton("打开")
        open_btn.setFixedHeight(40)
        open_btn.clicked.connect(self.open_selected)
        btn_layout.addWidget(open_btn)
        layout.addLayout(btn_layout)

        self.refresh()

    def refresh(self):
        expanded = self._collect_expanded_paths()
        self.tree.clear()

        root = QTreeWidgetItem([os.path.basename(self.root_dir) or self.root_dir, ""])
        root.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        root.setData(0, Qt.ItemDataRole.UserRole, self.root_dir)
        self.tree.addTopLevelItem(root)

        if os.path.exists(self.root_dir):
            self._populate_tree(root, self.root_dir)
        root.setExpanded(True)
        self._restore_expanded_paths(expanded)

    def _collect_expanded_paths(self):
        result = set()

        def walk(item):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and item.isExpanded():
                result.add(path)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return result

    def _restore_expanded_paths(self, expanded):
        if not expanded:
            return

        def walk(item):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path in expanded:
                item.setExpanded(True)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _populate_tree(self, parent_item, path):
        try:
            entries = sorted(
                os.listdir(path),
                key=lambda e: (not os.path.isdir(os.path.join(path, e)), e.lower())
            )
        except PermissionError:
            return

        for entry in entries:
            full = os.path.join(path, entry)
            try:
                size = os.path.getsize(full) if os.path.isfile(full) else 0
            except OSError:
                size = 0

            if os.path.isdir(full):
                item = QTreeWidgetItem([entry + "/", ""])
                item.setData(0, Qt.ItemDataRole.UserRole, full)
                item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                parent_item.addChild(item)
                self._populate_tree(item, full)
            else:
                item = QTreeWidgetItem([entry, self._format_size(size)])
                item.setData(0, Qt.ItemDataRole.UserRole, full)
                item.setIcon(0, self._icon_for_file(full))
                parent_item.addChild(item)

    def _icon_for_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        style = self.style()
        if ext in IMAGE_EXTS:
            return style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        return style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _format_size(self, size):
        if size < 1024: return f"{size} B"
        elif size < 1024 * 1024: return f"{size / 1024:.1f} KB"
        else: return f"{size / (1024 * 1024):.1f} MB"

    def _selected_items(self):
        return self.tree.selectedItems()

    def _selected_paths(self):
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self._selected_items()
                if it.data(0, Qt.ItemDataRole.UserRole)]

    def _target_dir(self):
        items = self._selected_items()
        if items:
            p = items[0].data(0, Qt.ItemDataRole.UserRole)
            if p and os.path.isdir(p):
                return p
            if p:
                return os.path.dirname(p)
        return self.root_dir

    def _is_inside_root(self, path):
        try:
            rp = os.path.realpath(self.root_dir)
            pp = os.path.realpath(path)
            return os.path.commonpath([rp, pp]) == rp
        except Exception:
            return False

    def on_item_clicked(self, item, column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or os.path.isdir(path):
            self.preview.clear()
            return

        ext = os.path.splitext(path)[1].lower()

        if ext in IMAGE_EXTS:
            try:
                pix = QPixmap(path)
                if not pix.isNull():
                    pix = pix.scaledToHeight(160, Qt.TransformationMode.SmoothTransformation)
                    self.preview.clear()
                    cursor = self.preview.textCursor()
                    cursor.insertImage(pix.toImage())
                    return
            except Exception:
                pass

        if ext in EDITABLE_EXTS or self._is_probably_text(path):
            try:
                content = self._read_text(path)
                if len(content) > 5000:
                    content = content[:5000] + "\n... (文件过大，仅显示前5000字符)"
                self.preview.setPlainText(content)
            except Exception as e:
                self.preview.setPlainText(f"无法预览: {e}")
        else:
            try:
                size = os.path.getsize(path)
                self.preview.setPlainText(
                    f"[二进制文件]\n{os.path.basename(path)}\n大小: {self._format_size(size)}")
            except OSError:
                self.preview.setPlainText("[无法读取文件信息]")

    def on_item_double_clicked(self, item, column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and not os.path.isdir(path):
            self.file_double_clicked.emit(path)

    def open_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        for p in paths:
            if not os.path.isdir(p):
                self.file_double_clicked.emit(p)
                break

    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()

            if key == Qt.Key.Key_Delete:
                self.delete_selected()
                return True
            if key == Qt.Key.Key_F2:
                self.rename_selected()
                return True
            if mods & Qt.KeyboardModifier.ControlModifier:
                if key == Qt.Key.Key_C:
                    self.copy_selected()
                    return True
                if key == Qt.Key.Key_X:
                    self.cut_selected()
                    return True
                if key == Qt.Key.Key_V:
                    self.paste_into_selected()
                    return True
                if key == Qt.Key.Key_A:
                    self.tree.selectAll()
                    return True
                if key == Qt.Key.Key_Z:
                    self.undo_delete()
                    return True
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                self.open_selected()
                return True

        return super().eventFilter(obj, event)

    def on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            is_dir = path and os.path.isdir(path)

            if path and not is_dir:
                act_open = menu.addAction("用编辑器打开" if self._is_editable(path) else "用系统程序打开")
                act_open.triggered.connect(lambda: self.file_double_clicked.emit(path))
            elif is_dir:
                act_open2 = menu.addAction("在文件管理器中打开")
                act_open2.triggered.connect(lambda: self._reveal_in_explorer(path))

            menu.addSeparator()

            act_cut = menu.addAction("剪切")
            act_cut.setShortcut(QKeySequence("Ctrl+X"))
            act_cut.triggered.connect(self.cut_selected)

            act_copy = menu.addAction("复制")
            act_copy.setShortcut(QKeySequence("Ctrl+C"))
            act_copy.triggered.connect(self.copy_selected)

            act_paste = menu.addAction("粘贴到此目录" if is_dir else "粘贴到父目录")
            act_paste.setShortcut(QKeySequence("Ctrl+V"))
            act_paste.setEnabled(bool(self._clipboard))
            act_paste.triggered.connect(self.paste_into_selected)

            menu.addSeparator()

            act_rename = menu.addAction("重命名")
            act_rename.setShortcut(QKeySequence("F2"))
            act_rename.triggered.connect(self.rename_selected)

            act_delete = menu.addAction("删除")
            act_delete.setShortcut(QKeySequence("Delete"))
            act_delete.triggered.connect(self.delete_selected)

            menu.addSeparator()

        act_new_file = menu.addAction("新建文件…")
        act_new_file.triggered.connect(self.new_file_here)

        act_new_dir = menu.addAction("新建文件夹…")
        act_new_dir.triggered.connect(self.new_folder_here)

        menu.addSeparator()

        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            act_reveal = menu.addAction("在文件管理器中显示")
            act_reveal.triggered.connect(lambda: self._reveal_in_explorer(path))

            act_copy_path = menu.addAction("复制路径")
            act_copy_path.triggered.connect(
                lambda: QApplication.clipboard().setText(path))

        act_undo = menu.addAction("撤销上次删除")
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        act_undo.setEnabled(bool(self._trash_stack))
        act_undo.triggered.connect(self.undo_delete)

        menu.addSeparator()

        act_refresh = menu.addAction("刷新")
        act_refresh.triggered.connect(self.refresh)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def copy_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        self._clipboard = [(p, 'copy') for p in paths]
        self.status_message.emit(f"已复制 {len(paths)} 项")

    def cut_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        self._clipboard = [(p, 'cut') for p in paths]
        self.status_message.emit(f"已剪切 {len(paths)} 项")

    def paste_into_selected(self):
        if not self._clipboard:
            self.status_message.emit("剪贴板为空")
            return
        dest_dir = self._target_dir()
        if not os.path.isdir(dest_dir):
            self.status_message.emit("目标不是目录")
            return

        done = 0
        failed = []

        for src, op in self._clipboard:
            if not os.path.exists(src):
                failed.append(f"{os.path.basename(src)}: 源不存在")
                continue

            name = os.path.basename(src)
            target = os.path.join(dest_dir, name)

            if os.path.exists(target):
                if os.path.abspath(src) == os.path.abspath(target):
                    base, ext = os.path.splitext(name)
                    i = 1
                    while os.path.exists(target):
                        target = os.path.join(dest_dir, f"{base}_副本{i}{ext}")
                        i += 1
                else:
                    choice = QMessageBox.question(
                        self, "目标已存在",
                        f"{name} 已存在，是否覆盖？\n\n"
                        f"是 = 覆盖\n否 = 保留两者（自动改名）\n取消 = 跳过此项",
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No |
                        QMessageBox.StandardButton.Cancel)
                    if choice == QMessageBox.StandardButton.Cancel:
                        continue
                    if choice == QMessageBox.StandardButton.No:
                        base, ext = os.path.splitext(name)
                        i = 1
                        while os.path.exists(target):
                            target = os.path.join(dest_dir, f"{base}_副本{i}{ext}")
                            i += 1

            try:
                if os.path.isdir(src):
                    try:
                        if os.path.commonpath([os.path.abspath(src),
                                               os.path.abspath(target)]) == os.path.abspath(src):
                            failed.append(f"{name}: 不能把目录粘贴到自身")
                            continue
                    except ValueError:
                        pass

                if op == 'copy':
                    if os.path.isdir(src):
                        if os.path.exists(target):
                            self._rmtree_safe(target)
                        shutil.copytree(src, target)
                    else:
                        if os.path.exists(target):
                            try: os.remove(target)
                            except Exception: pass
                        shutil.copy2(src, target)
                else:
                    if os.path.exists(target):
                        try:
                            if os.path.isdir(target):
                                self._rmtree_safe(target)
                            else:
                                os.remove(target)
                        except Exception:
                            pass
                    shutil.move(src, target)
                done += 1
            except Exception as e:
                failed.append(f"{name}: {e}")

        if any(op == 'cut' for _, op in self._clipboard):
            self._clipboard = [x for x in self._clipboard if x[1] == 'copy']

        self.refresh()
        msg = f"已粘贴 {done} 项"
        if failed:
            msg += f"，{len(failed)} 项失败"
            QMessageBox.warning(self, "部分失败", "\n".join(failed[:10]))
        self.status_message.emit(msg)

    def delete_selected(self):
        paths = self._selected_paths()
        if not paths:
            return

        outside = [p for p in paths if not self._is_inside_root(p)]
        if outside:
            QMessageBox.warning(
                self, "越界",
                f"以下文件不在工作区根目录内，拒绝删除：\n\n"
                + "\n".join(outside[:5]))
            return

        confirm = QMessageBox.question(
            self, "确认删除",
            f"确定要删除以下 {len(paths)} 项吗？\n\n"
            + "\n".join(os.path.basename(p) for p in paths[:8])
            + ("\n..." if len(paths) > 8 else "")
            + "\n\n删除后可 Ctrl+Z 撤销（本次会话内）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        session_id = str(int(time.time() * 1000))
        trash_root = os.path.join(tempfile.gettempdir(), "PyEdit_trash", session_id)
        os.makedirs(trash_root, exist_ok=True)

        done = 0
        failed = []

        for src in paths:
            if not os.path.exists(src):
                continue
            name = os.path.basename(src)
            dest = os.path.join(trash_root, name)
            i = 1
            while os.path.exists(dest):
                base, ext = os.path.splitext(name)
                dest = os.path.join(trash_root, f"{base}_{i}{ext}")
                i += 1
            try:
                shutil.move(src, dest)
                self._trash_stack.append((dest, src))
                done += 1
            except Exception as e:
                failed.append(f"{name}: {e}")

        self.refresh()
        msg = f"已删除 {done} 项（可 Ctrl+Z 撤销）"
        if failed:
            msg += f"，{len(failed)} 项失败"
            QMessageBox.warning(self, "部分失败", "\n".join(failed[:10]))
        self.status_message.emit(msg)

    def undo_delete(self):
        if not self._trash_stack:
            self.status_message.emit("没有可撤销的删除")
            return
        done = 0
        failed = []
        while self._trash_stack:
            src, original = self._trash_stack.pop()
            if not os.path.exists(src):
                continue
            try:
                target = original
                if os.path.exists(target):
                    base, ext = os.path.splitext(original)
                    i = 1
                    while os.path.exists(target):
                        target = f"{base}_恢复{i}{ext}"
                        i += 1
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(src, target)
                done += 1
            except Exception as e:
                failed.append(f"{os.path.basename(original)}: {e}")

        self.refresh()
        msg = f"已恢复 {done} 项"
        if failed:
            msg += f"，{len(failed)} 项失败"
        self.status_message.emit(msg)

    def rename_selected(self):
        items = self._selected_items()
        if len(items) != 1:
            self.status_message.emit("请选中单个文件/文件夹后重命名")
            return
        path = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        old_name = os.path.basename(path)

        new_name, ok = QInputDialog.getText(
            self, "重命名", "新名称:", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return

        if any(c in new_name for c in r'\/:*?"<>|'):
            QMessageBox.warning(self, "非法名称", "名称中包含非法字符")
            return

        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "已存在", f"{new_name} 已存在")
            return

        try:
            os.rename(path, new_path)
            self.status_message.emit(f"已重命名: {old_name} → {new_name}")
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"重命名失败: {e}")

    def new_file_here(self):
        dest_dir = self._target_dir()
        name, ok = QInputDialog.getText(
            self, "新建文件", "文件名:", text="new_file.py")
        if not ok or not name:
            return
        if any(c in name for c in r'\/:*?"<>|'):
            QMessageBox.warning(self, "非法名称", "名称中包含非法字符")
            return
        target = os.path.join(dest_dir, name)
        if os.path.exists(target):
            QMessageBox.warning(self, "已存在", f"{name} 已存在")
            return
        try:
            with open(target, 'w', encoding='utf-8') as f:
                if name.endswith('.py'):
                    f.write("# 新建文件\n")
            self.refresh()
            self.status_message.emit(f"已创建: {name}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建失败: {e}")

    def new_folder_here(self):
        dest_dir = self._target_dir()
        name, ok = QInputDialog.getText(
            self, "新建文件夹", "文件夹名:", text="新建文件夹")
        if not ok or not name:
            return
        if any(c in name for c in r'\/:*?"<>|'):
            QMessageBox.warning(self, "非法名称", "名称中包含非法字符")
            return
        target = os.path.join(dest_dir, name)
        if os.path.exists(target):
            QMessageBox.warning(self, "已存在", f"{name} 已存在")
            return
        try:
            os.makedirs(target)
            self.refresh()
            self.status_message.emit(f"已创建: {name}/")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建失败: {e}")

    def _rmtree_safe(self, path):
        def onerror(func, p, exc_info):
            try:
                os.chmod(p, 0o777)
                func(p)
            except Exception:
                pass
        shutil.rmtree(path, onerror=onerror)

    def _reveal_in_explorer(self, path):
        try:
            if platform.system() == "Windows":
                if os.path.isfile(path):
                    subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
                else:
                    os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(['open', '-R', path])
            else:
                subprocess.Popen(['xdg-open',
                                  path if os.path.isdir(path) else os.path.dirname(path)])
        except Exception:
            pass

    def _is_editable(self, path):
        return os.path.splitext(path)[1].lower() in EDITABLE_EXTS

    def _is_probably_text(self, path):
        try:
            with open(path, 'rb') as f:
                chunk = f.read(1024)
            if b'\x00' in chunk:
                return False
            chunk.decode('utf-8')
            return True
        except Exception:
            return False

    def _read_text(self, path):
        for enc in ['utf-8', 'gbk', 'utf-16']:
            try:
                with open(path, 'r', encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()


# ============================================================
# 编辑器 Tab
# ============================================================

class EditorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.encoding = "utf-8"
        self.modified = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = CodeEditor(parent)
        self.editor.textChanged.connect(self._on_modified)
        layout.addWidget(self.editor)

    def _on_modified(self):
        self.modified = True

    def set_content(self, content, file_path=None, encoding='utf-8'):
        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)
        self.file_path = file_path
        self.encoding = encoding
        self.modified = False
        self.editor.run_error_check()

    def get_content(self):
        return self.editor.toPlainText()

    def get_display_name(self):
        if self.file_path:
            return os.path.basename(self.file_path)
        return "未命名"


# ============================================================
# 终端
# ============================================================

class TerminalManager:
    def __init__(self):
        self.current_directory = os.path.expanduser("~")
        self.process = None
        self.read_thread = None
        self.stop_reading = False
        self.is_running = False
        self.stdin_queue = queue.Queue()
        self.output_buffer = ""
        self.buffer_lock = threading.Lock()

    def execute_command(self, command, output_callback):
        try:
            if command.strip() == "clear":
                if output_callback: output_callback("")
                return

            if command.startswith("cd "):
                nd = command[3:].strip()
                if nd == "..":
                    self.current_directory = os.path.dirname(self.current_directory)
                elif os.path.isdir(nd):
                    self.current_directory = nd
                elif os.path.isdir(os.path.join(self.current_directory, nd)):
                    self.current_directory = os.path.join(self.current_directory, nd)
                else:
                    if output_callback: output_callback(f"cd: {nd}: 目录不存在\n")
                if output_callback:
                    output_callback(f"切换到目录: {self.current_directory}\n")
                return

            if command.startswith("pip ") and ' install ' in command:
                parts = command.split(' install ')
                if len(parts) == 2:
                    command = parts[0] + ' install --progress-bar off ' + parts[1]

            self.stop_reading = False
            self.is_running = True
            self.output_buffer = ""

            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

            self.process = subprocess.Popen(
                command, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=False,
                cwd=self.current_directory, bufsize=0,
                creationflags=creationflags, env=env
            )

            def read_output():
                buffer = bytearray()
                while not self.stop_reading:
                    if self.process is None or self.process.poll() is not None:
                        break
                    try:
                        data = self.process.stdout.read(1)
                        if data:
                            buffer.extend(data)
                            try:
                                text = buffer.decode('utf-8')
                                if text:
                                    with self.buffer_lock:
                                        self.output_buffer += text
                                    buffer.clear()
                                    if '\n' in text or text.endswith('?') or text.endswith(':') or text.endswith('>'):
                                        with self.buffer_lock:
                                            to_send = self.output_buffer
                                            self.output_buffer = ""
                                        if to_send and output_callback:
                                            output_callback(to_send)
                            except UnicodeDecodeError:
                                if len(buffer) > 100:
                                    try:
                                        text = buffer.decode('utf-8', errors='ignore')
                                        if text:
                                            with self.buffer_lock:
                                                self.output_buffer += text
                                            buffer.clear()
                                    except Exception:
                                        pass
                        else:
                            time.sleep(0.01)
                    except Exception:
                        time.sleep(0.01)
                with self.buffer_lock:
                    if self.output_buffer and output_callback:
                        output_callback(self.output_buffer)
                    self.output_buffer = ""
                if self.process:
                    self.process.wait()
                self.is_running = False

            self.read_thread = threading.Thread(target=read_output, daemon=True)
            self.read_thread.start()

            def handle_stdin():
                while not self.stop_reading and self.process and self.process.poll() is None:
                    try:
                        text = self.stdin_queue.get(timeout=0.1)
                        if text is None: break
                        if self.process and self.process.stdin:
                            self.process.stdin.write((text + '\n').encode('utf-8'))
                            self.process.stdin.flush()
                    except queue.Empty:
                        continue
                    except Exception:
                        pass

            threading.Thread(target=handle_stdin, daemon=True).start()

        except Exception as e:
            if output_callback:
                output_callback(f"命令执行错误: {str(e)}\n")
            self.is_running = False

    def send_input(self, text):
        if self.is_running and self.process and self.process.poll() is None:
            try:
                self.stdin_queue.put(text)
                return True
            except Exception:
                return False
        return False

    def stop_command(self):
        self.stop_reading = True
        while not self.stdin_queue.empty():
            try:
                self.stdin_queue.get_nowait()
            except Exception:
                break
        if self.process:
            try:
                pid = self.process.pid
                if platform.system() == "Windows":
                    try:
                        subprocess.run(f'taskkill /F /T /PID {pid}', shell=True,
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception:
                        pass
                try:
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        try: child.kill()
                        except Exception: pass
                    parent.kill()
                except Exception:
                    pass
                try: self.process.wait(timeout=1)
                except Exception: pass
            except Exception:
                pass
            self.process = None
        self.is_running = False

    def get_prompt(self):
        return f"{self.current_directory}> "


# ============================================================
# Modal Bottom Sheet
# ============================================================

class ModalBottomSheet(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent, title="", content_widget=None, max_height=520):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self._parent = parent
        self._max_h = max_height
        self._visible = False

        self.scrim = QWidget(parent)
        self.scrim.setStyleSheet("background: rgba(0,0,0,140);")
        self.scrim.setGeometry(parent.rect())
        self.scrim.hide()
        self.scrim.mousePressEvent = lambda e: self.dismiss()

        self.sheet = QFrame(parent)
        self.sheet.setProperty("class", "bottom-sheet")
        self.sheet.setFixedHeight(max_height)

        sheet_layout = QVBoxLayout(self.sheet)
        sheet_layout.setContentsMargins(0, 8, 0, 20)
        sheet_layout.setSpacing(8)

        handle = QFrame()
        handle.setProperty("class", "sheet-handle")
        handle.setFixedWidth(48)
        handle_wrap = QHBoxLayout()
        handle_wrap.addStretch()
        handle_wrap.addWidget(handle)
        handle_wrap.addStretch()
        sheet_layout.addLayout(handle_wrap)

        if title:
            tl = QLabel(title)
            tl.setProperty("class", "title-large")
            tl.setContentsMargins(24, 8, 24, 8)
            sheet_layout.addWidget(tl)

        if content_widget is not None:
            content_widget.setParent(self.sheet)
            sheet_layout.addWidget(content_widget, 1)

        self.sheet.hide()

        self._anim = QPropertyAnimation(self.sheet, b"pos")
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._scrim_anim = QPropertyAnimation(self.scrim, b"windowOpacity")
        self._scrim_anim.setDuration(220)

        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._parent and event.type() == QEvent.Type.Resize:
            self.scrim.setGeometry(self._parent.rect())
            if self._visible:
                self._reposition(final=True)
        return super().eventFilter(obj, event)

    def _reposition(self, final=False):
        pw = self._parent.width()
        ph = self._parent.height()
        w = min(700, pw - 48)
        x = (pw - w) // 2
        y_end = ph - self._max_h - 12
        y_start = ph + 20
        self.sheet.setFixedWidth(w)
        self.sheet.setGeometry(x, y_start, w, self._max_h)
        return x, y_end, y_start

    def show_sheet(self):
        if self._visible:
            return
        self._visible = True
        self.scrim.setGeometry(self._parent.rect())
        self.scrim.show()
        self.scrim.raise_()
        self.sheet.show()
        self.sheet.raise_()
        self.sheet.update()

        x, y_end, y_start = self._reposition()
        self.sheet.move(x, y_start)
        self._anim.stop()
        self._anim.setStartValue(QPoint(x, y_start))
        self._anim.setEndValue(QPoint(x, y_end))
        self._anim.start()

        self.scrim.setWindowOpacity(0.0)
        self._scrim_anim.stop()
        self._scrim_anim.setStartValue(0.0)
        self._scrim_anim.setEndValue(1.0)
        self._scrim_anim.start()

    def dismiss(self):
        if not self._visible:
            return
        self._visible = False
        x, y_end, y_start = self._reposition()

        self._anim.stop()
        self._anim.setStartValue(self.sheet.pos())
        self._anim.setEndValue(QPoint(x, y_start))

        def on_done():
            self.sheet.hide()
            self.scrim.hide()
            self.closed.emit()
            try:
                self._anim.finished.disconnect(on_done)
            except Exception:
                pass

        self._anim.finished.connect(on_done)
        self._anim.start()


# ============================================================
# AI 配置与会话
# ============================================================

AI_CONFIG_FILE = Path.home() / ".pyedit_ai_config.json"
AI_HISTORY_DIR = Path.home() / ".pyedit_ai_history"
AI_HISTORY_DIR.mkdir(exist_ok=True)


def load_ai_config():
    if AI_CONFIG_FILE.exists():
        try:
            return json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_ai_config(cfg):
    AI_CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _esc(s: str) -> str:
    return html_lib.escape(s, quote=False)


def _render_md_bold(text: str) -> str:
    text = _esc(text)
    text = re.sub(
        r"\*\*(.+?)\*\*",
        r'<b><span style="font-size:1.25em;color:#e6f4ff">\1</span></b>',
        text,
    )
    text = text.replace("\n", "<br>")
    return text


class AISessionStore:
    @staticmethod
    def _path(sid: str) -> Path:
        return AI_HISTORY_DIR / f"{sid}.json"

    @staticmethod
    def list_sessions():
        sessions = []
        for f in AI_HISTORY_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "id": f.stem,
                    "title": data.get("title", "未命名"),
                    "updated": data.get("updated", ""),
                    "count": len([m for m in data.get("history", []) if m.get("role") != "system"]),
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x.get("updated", ""), reverse=True)
        return sessions

    @staticmethod
    def new_session(title="新对话"):
        sid = uuid.uuid4().hex[:12]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {"id": sid, "title": title, "created": now,
                "updated": now, "history": []}
        AISessionStore._path(sid).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return sid

    @staticmethod
    def load(sid: str):
        p = AISessionStore._path(sid)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def save(sid: str, history: list, title: str = None):
        p = AISessionStore._path(sid)
        data = AISessionStore.load(sid) or {
            "id": sid, "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        data["history"] = history
        data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if title is not None:
            data["title"] = title
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def delete(sid: str):
        p = AISessionStore._path(sid)
        if p.exists():
            p.unlink()

    @staticmethod
    def rename(sid: str, new_title: str):
        data = AISessionStore.load(sid)
        if data:
            data["title"] = new_title
            AISessionStore._path(sid).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 系统提示词（含 Windows 控制协议）
# ============================================================

USER_SYSTEM_PROMPT = (
    "你说的话需要简短一点点，但是不要过于简短。"
    "你可以创建文件，格式是{code}[文件名,文件内容]{/code}，文件名和内容都是str。"
    "如果要求创建上网下载文件请搜索软件官网查看html，html格式：{html}内容{/html}，"
    "会返回给你，你可以查看找链接。"
    "{run}终端命令{/run}可以执行终端。"
    "{out}输出{/out}是输出，里面包含终端的报错。"
    "如果是None说明用户不同意，如果是Null说明没有。"
    "你还可以控制 Windows 桌面（真实点击、键盘、窗口操作），协议："
    "{win:move,x,y} 移动鼠标；"
    "{win:click,x,y,left|right|double} 点击；"
    "{win:type,文本} 输入文本；"
    "{win:key,键名} 按键（enter/tab/esc/win/f5 等）；"
    "{win:hotkey,ctrl,c} 组合键；"
    "{win:scroll,数值} 滚轮；"
    "{win:activate,窗口标题关键字} 激活窗口；"
    "{win:minimize,关键字} / {win:maximize,关键字} / {win:close,关键字}；"
    "{win:list} 列出所有可见窗口；"
    "{win:screenshot} 截屏并保存。"
    "所有 win 操作前会弹窗请求用户确认。"
)


PROTOCOL_RULES = (
    "你必须严格遵循以下协议。任何需要执行动作时,只输出对应标签,不要额外解释:\n"
    "1) 创建或写入文件:{code}[文件名,文件内容]{/code}。文件名与文件内容均为字符串,"
    "文件名相对于工作目录,内容里不要包含{/code}。一次可写多个 code 块。\n"
    "2) 需要联网抓取网页时:{html}网址{/html}。只写 URL,不要写别的。\n"
    "3) 需要执行终端命令时:{run}命令{/run}。一次一条命令,命令不要包含{/run}。\n"
    "4) 收到用户消息 {out}...{/out} 表示上一步执行结果:{out}None{/out} 表示用户拒绝执行,"
    "{out}Null{/out} 表示命令没有输出。请据此继续。\n"
    "5) 回答保持简短但不要过于简短,先执行动作,再简要总结结果。\n"
    "6) 环境是 Windows,终端是 cmd。删除多个文件请用 "
    'del /q "a" & del /q "b" 的形式,不要把多个文件名写在一个 del 后面。\n'
    "7) 如果某个命令返回 {out}None{/out}(用户拒绝),不要反复重试同一命令。\n"
    "8) 读取中文文本文件优先用: powershell -Command \"Get-Content -Encoding UTF8 文件名\"。\n"
    "9) 支持 Markdown 的 **加粗** 语法,用于强调关键词。\n"
    "10) Windows 控制指令格式: {win:动作,参数1,参数2,...}。"
    "动作包括 move/click/double_click/right_click/type/key/hotkey/scroll/"
    "activate/minimize/maximize/close/list/screenshot。"
    "每个 win 指令执行前都会弹窗询问用户是否允许。\n"
    "11) 当用户要求你操作屏幕、点击按钮、打开程序时,使用 {win:...} 指令,"
    "不要试图用 {run} 代替真实鼠标操作。\n"
    "12) 你可以用 {run} 执行 python 脚本,但真正控制鼠标键盘请用 {win:...}。"
)

BASE_SYSTEM_PROMPT = PROTOCOL_RULES + "\n\n补充要求:\n" + USER_SYSTEM_PROMPT


# ============================================================
# Windows 控制器
# ============================================================

class WindowsController:
    """通过 ctypes 直接调用 Windows API 实现真实鼠标键盘控制，无第三方依赖。"""

    @staticmethod
    def available():
        return HAS_WIN32

    @staticmethod
    def get_status():
        if HAS_WIN32:
            return "✓ Windows API 可用 (ctypes)"
        return "✗ 仅支持 Windows 系统"

    # ---------- 鼠标（SendInput） ----------
    @staticmethod
    def _send_input(*inputs):
        if not HAS_WIN32:
            return False
        n = len(inputs)
        arr = (ctypes.c_void_p * n)()
        for i, inp in enumerate(inputs):
            arr[i] = ctypes.cast(ctypes.pointer(inp), ctypes.c_void_p)
        ctypes.windll.user32.SendInput(n, ctypes.cast(arr, ctypes.c_void_p),
                                       ctypes.sizeof(inputs[0]))
        return True

    @staticmethod
    def _mouse_input(flags, dx=0, dy=0, data=0):
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
        return mi

    @staticmethod
    def move_to(x, y, duration=0.0):
        if not HAS_WIN32:
            return "仅支持 Windows"
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        return f"鼠标移动到 ({x}, {y})"

    @staticmethod
    def click(x=None, y=None, button="left", clicks=1):
        if not HAS_WIN32:
            return "仅支持 Windows"
        if x is not None and y is not None:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)
        # 用 mouse_event 更简单
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040
        if button == "right":
            down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            down, up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        else:
            down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        for _ in range(int(clicks)):
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            time.sleep(0.03)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.05)
        pos = WindowsController.get_mouse_pos()
        return f"在 {pos} {button}键点击 {clicks} 次"

    @staticmethod
    def double_click(x=None, y=None):
        return WindowsController.click(x, y, "left", 2)

    @staticmethod
    def right_click(x=None, y=None):
        return WindowsController.click(x, y, "right", 1)

    @staticmethod
    def scroll(amount, x=None, y=None):
        if not HAS_WIN32:
            return "仅支持 Windows"
        if x is not None and y is not None:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)
        MOUSEEVENTF_WHEEL = 0x0800
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0,
                                         int(amount * 120), 0)
        return f"滚轮 {amount}"

    @staticmethod
    def get_mouse_pos():
        if not HAS_WIN32:
            return None
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)

    @staticmethod
    def drag(x1, y1, x2, y2, duration=0.3, button="left"):
        if not HAS_WIN32:
            return "仅支持 Windows"
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        ctypes.windll.user32.SetCursorPos(int(x1), int(y1))
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        steps = 20
        for i in range(1, steps + 1):
            x = int(x1 + (x2 - x1) * i / steps)
            y = int(y1 + (y2 - y1) * i / steps)
            ctypes.windll.user32.SetCursorPos(x, y)
            time.sleep(duration / steps)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return f"拖拽 ({x1},{y1}) → ({x2},{y2})"

    # ---------- 键盘 ----------
    @staticmethod
    def type_text(text, interval=0.02):
        if not HAS_WIN32:
            return "仅支持 Windows"
        # 用 SendInput 输入 unicode
        for ch in text:
            if ch == '\n':
                WindowsController.press_key('enter')
                continue
            if ch == '\t':
                WindowsController.press_key('tab')
                continue
            vk = ctypes.windll.user32.VkKeyScanW(ord(ch))
            if vk == -1:
                # 用 unicode 方式
                KEYEVENTF_UNICODE = 0x0004
                KEYEVENTF_KEYUP = 0x0002
                ctypes.windll.user32.keybd_event(0, ord(ch) & 0xFF, KEYEVENTF_UNICODE, 0)
                ctypes.windll.user32.keybd_event(0, ord(ch) & 0xFF, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            else:
                shift = (vk >> 8) & 0xFF
                vk_code = vk & 0xFF
                if shift & 1:
                    ctypes.windll.user32.keybd_event(0x10, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
                if shift & 1:
                    ctypes.windll.user32.keybd_event(0x10, 0, 2, 0)
            time.sleep(interval)
        return f"已输入文本: {text[:50]}..."

    _VK_MAP = {
        'enter': 0x0D, 'return': 0x0D, 'tab': 0x09, 'esc': 0x1B, 'escape': 0x1B,
        'space': 0x20, 'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E,
        'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
        'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
        'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
        'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
        'f11': 0x7A, 'f12': 0x7B,
        'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10,
        'win': 0x5B, 'windows': 0x5B, 'cmd': 0x5B,
        'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
        'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
        'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
        'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
        'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
        '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
        '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    }

    @staticmethod
    def _vk(key):
        return WindowsController._VK_MAP.get(key.lower(), None)

    @staticmethod
    def press_key(key):
        if not HAS_WIN32:
            return "仅支持 Windows"
        vk = WindowsController._vk(key)
        if vk is None:
            return f"未知按键: {key}"
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return f"按键: {key}"

    @staticmethod
    def hotkey(*keys):
        if not HAS_WIN32:
            return "仅支持 Windows"
        vks = []
        for k in keys:
            vk = WindowsController._vk(k)
            if vk is None:
                return f"未知按键: {k}"
            vks.append(vk)
        for vk in vks:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)
        for vk in reversed(vks):
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            time.sleep(0.02)
        return f"组合键: {'+'.join(keys)}"

    # ---------- 截图 ----------
    @staticmethod
    def screenshot(save_path=None):
        if not HAS_WIN32:
            return None, "仅支持 Windows"
        if save_path is None:
            save_path = os.path.join(tempfile.gettempdir(), "pyedit_screenshot.png")
        try:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            pix = screen.grabWindow(0)
            pix.save(save_path, "PNG")
            return save_path, f"截图已保存: {save_path}"
        except Exception as e:
            return None, f"截图失败: {e}"

    # ---------- 窗口 ----------
    @staticmethod
    def list_windows():
        if not HAS_WIN32:
            return [], "仅支持 Windows"
        result = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                             wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    if buf.value:
                        result.append((hwnd, buf.value))
            return True

        ctypes.windll.user32.EnumWindows(EnumWindowsProc(cb), 0)
        return result, f"共 {len(result)} 个可见窗口"

    @staticmethod
    def find_window(keyword):
        windows, _ = WindowsController.list_windows()
        for hwnd, title in windows:
            if keyword.lower() in title.lower():
                return hwnd, title
        return None, None

    @staticmethod
    def activate_window(keyword):
        if not HAS_WIN32:
            return "仅支持 Windows"
        hwnd, title = WindowsController.find_window(keyword)
        if not hwnd:
            return f"未找到窗口: {keyword}"
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return f"已激活窗口: {title}"
        except Exception as e:
            return f"激活失败: {e}"

    @staticmethod
    def minimize_window(keyword):
        if not HAS_WIN32:
            return "仅支持 Windows"
        hwnd, title = WindowsController.find_window(keyword)
        if not hwnd:
            return f"未找到窗口: {keyword}"
        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return f"已最小化: {title}"

    @staticmethod
    def maximize_window(keyword):
        if not HAS_WIN32:
            return "仅支持 Windows"
        hwnd, title = WindowsController.find_window(keyword)
        if not hwnd:
            return f"未找到窗口: {keyword}"
        ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        return f"已最大化: {title}"

    @staticmethod
    def close_window(keyword):
        if not HAS_WIN32:
            return "仅支持 Windows"
        hwnd, title = WindowsController.find_window(keyword)
        if not hwnd:
            return f"未找到窗口: {keyword}"
        WM_CLOSE = 0x0010
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return f"已请求关闭: {title}"

    @staticmethod
    def get_screen_size():
        if not HAS_WIN32:
            return (0, 0)
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        return (w, h)


# ============================================================
# AI 动作执行器（含 Windows 控制）
# ============================================================

class AIActionExecutor:
    CODE_RE = re.compile(r"\{code\}\[(.*?)\]\{/code\}", re.DOTALL)
    HTML_RE = re.compile(r"\{html\}(.*?)\{/html\}", re.DOTALL)
    RUN_RE = re.compile(r"\{run\}(.*?)\{/run\}", re.DOTALL)
    WIN_RE = re.compile(r"\{win:(.*?)\}", re.DOTALL)

    def __init__(self, workspace: Path, confirm_callback=None):
        self.workspace = workspace
        self.confirm_callback = confirm_callback or self._default_confirm

    def has_actions(self, text: str) -> bool:
        return bool(
            self.CODE_RE.search(text) or self.HTML_RE.search(text)
            or self.RUN_RE.search(text) or self.WIN_RE.search(text)
        )

    def execute_all(self, text: str) -> str:
        results = []
        # 按出现顺序执行
        events = []
        for m in self.CODE_RE.finditer(text):
            events.append((m.start(), "code", m.group(1)))
        for m in self.HTML_RE.finditer(text):
            events.append((m.start(), "html", m.group(1)))
        for m in self.RUN_RE.finditer(text):
            events.append((m.start(), "run", m.group(1)))
        for m in self.WIN_RE.finditer(text):
            events.append((m.start(), "win", m.group(1)))
        events.sort(key=lambda x: x[0])
        for _, kind, payload in events:
            if kind == "code":
                results.append(self._do_code(payload))
            elif kind == "html":
                results.append(self._do_html(payload.strip()))
            elif kind == "run":
                results.append(self._do_run(payload.strip()))
            elif kind == "win":
                results.append(self._do_win(payload.strip()))
        return "\n".join([r for r in results if r])

    def _default_confirm(self, kind: str, detail: str) -> bool:
        names = {"code": "写入文件", "html": "抓取网页",
                 "run": "执行终端命令", "win": "控制 Windows"}
        title = "确认操作 - " + names.get(kind, kind)
        settings = QSettings("PyEdit", "PyEditIDE")
        if settings.value("actions/always_allow", False, type=bool):
            return True

        dlg = QDialog()
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.setMinimumWidth(560)
        dlg.setMaximumHeight(620)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"是否允许{names.get(kind, kind)}?"))

        detail_edit = QPlainTextEdit()
        detail_edit.setReadOnly(True)
        detail_edit.setPlainText(detail)
        detail_edit.setMinimumHeight(140)
        detail_edit.setMaximumHeight(420)
        layout.addWidget(detail_edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes |
            QDialogButtonBox.StandardButton.No
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        layout.addWidget(buttons)

        allowed = dlg.exec() == QDialog.DialogCode.Accepted
        return allowed

    def _do_code(self, payload: str) -> str:
        if not self.confirm_callback("code", payload):
            return "{out}None{/out}"
        try:
            idx = payload.find(",")
            if idx == -1:
                return "{out}格式错误: 缺少逗号{/out}"
            name = payload[:idx].strip()
            content = payload[idx + 1:]
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return "{out}已写入文件: " + name + "{/out}"
        except Exception as e:
            return "{out}写入失败: " + str(e) + "{/out}"

    def _do_html(self, url: str) -> str:
        if not self.confirm_callback("html", url):
            return "{out}None{/out}"
        try:
            if not url.startswith("http"):
                url = "https://" + url
            resp = requests.get(
                url, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return "{out}" + resp.text + "{/out}"
        except Exception as e:
            return "{out}抓取失败: " + str(e) + "{/out}"

    def _do_run(self, cmd: str) -> str:
        if not self.confirm_callback("run", cmd):
            return "{out}None{/out}"
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            if platform.system() == "Windows":
                full_cmd = "chcp 65001 >nul & " + cmd
                p = subprocess.run(
                    full_cmd, shell=True, cwd=str(self.workspace),
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=600, env=env,
                )
            else:
                p = subprocess.run(
                    cmd, shell=True, cwd=str(self.workspace),
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=600, env=env,
                )
            out = (p.stdout or "")
            err = (p.stderr or "")
            out = "\n".join(
                line for line in out.splitlines()
                if "Active code page" not in line and "活动代码页" not in line
            )
            combined = out
            if err.strip():
                combined += ("\n[stderr]\n" + err)
            if not combined.strip():
                return "{out}Null{/out}"
            return "{out}" + combined + "{/out}"
        except subprocess.TimeoutExpired:
            return "{out}命令超时{/out}"
        except Exception as e:
            return "{out}执行失败: " + str(e) + "{/out}"

    def _do_win(self, payload: str) -> str:
        """处理 {win:action,arg1,arg2,...} 指令"""
        if not HAS_WIN32:
            return "{out}Windows 控制不可用（仅 Windows 系统支持）{/out}"
        parts = [p.strip() for p in payload.split(",")]
        if not parts:
            return "{out}win 指令为空{/out}"
        action = parts[0].lower()
        args = parts[1:]

        if not self.confirm_callback("win", f"动作: {action}\n参数: {args}"):
            return "{out}None{/out}"

        try:
            W = WindowsController
            if action == "move":
                x, y = int(args[0]), int(args[1])
                return "{out}" + W.move_to(x, y) + "{/out}"
            elif action == "click":
                x, y = int(args[0]), int(args[1])
                button = args[2] if len(args) > 2 else "left"
                return "{out}" + W.click(x, y, button) + "{/out}"
            elif action == "double_click":
                x, y = int(args[0]), int(args[1])
                return "{out}" + W.double_click(x, y) + "{/out}"
            elif action == "right_click":
                x, y = int(args[0]), int(args[1])
                return "{out}" + W.right_click(x, y) + "{/out}"
            elif action == "type":
                text = ",".join(args)
                return "{out}" + W.type_text(text) + "{/out}"
            elif action == "key":
                return "{out}" + W.press_key(args[0]) + "{/out}"
            elif action == "hotkey":
                return "{out}" + W.hotkey(*args) + "{/out}"
            elif action == "scroll":
                amt = int(args[0])
                if len(args) >= 3:
                    return "{out}" + W.scroll(amt, int(args[1]), int(args[2])) + "{/out}"
                return "{out}" + W.scroll(amt) + "{/out}"
            elif action == "activate":
                return "{out}" + W.activate_window(",".join(args)) + "{/out}"
            elif action == "minimize":
                return "{out}" + W.minimize_window(",".join(args)) + "{/out}"
            elif action == "maximize":
                return "{out}" + W.maximize_window(",".join(args)) + "{/out}"
            elif action == "close":
                return "{out}" + W.close_window(",".join(args)) + "{/out}"
            elif action == "list":
                windows, msg = W.list_windows()
                lines = [msg] + [f"  [{hwnd}] {title}" for hwnd, title in windows]
                return "{out}" + "\n".join(lines) + "{/out}"
            elif action == "screenshot":
                path, msg = W.screenshot()
                return "{out}" + msg + "{/out}"
            elif action == "drag":
                x1, y1, x2, y2 = int(args[0]), int(args[1]), int(args[2]), int(args[3])
                return "{out}" + W.drag(x1, y1, x2, y2) + "{/out}"
            elif action == "pos":
                pos = W.get_mouse_pos()
                return "{out}鼠标位置: {pos}{/out}"
            elif action == "screen":
                w, h = W.get_screen_size()
                return f"{{out}}屏幕尺寸: {w}x{h}{{/out}}"
            else:
                return f"{{out}}未知 win 动作: {action}{{/out}}"
        except Exception as e:
            return f"{{out}}win 执行失败: {e}{{/out}}"


# ============================================================
# AI 聊天渲染器
# ============================================================

class AIChatRenderer:
    CODE_OPEN = re.compile(r"\{code\}\[", re.DOTALL)
    CODE_CLOSE = re.compile(r"\]\{/code\}", re.DOTALL)
    RUN_OPEN = re.compile(r"\{run\}", re.DOTALL)
    RUN_CLOSE = re.compile(r"\{/run\}", re.DOTALL)
    HTML_OPEN = re.compile(r"\{html\}", re.DOTALL)
    HTML_CLOSE = re.compile(r"\{/html\}", re.DOTALL)
    OUT_OPEN = re.compile(r"\{out\}", re.DOTALL)
    OUT_CLOSE = re.compile(r"\{/out\}", re.DOTALL)
    WIN_OPEN = re.compile(r"\{win:", re.DOTALL)
    WIN_CLOSE = re.compile(r"\}", re.DOTALL)

    def __init__(self, browser: QTextBrowser, store: dict):
        self.browser = browser
        self.store = store
        self.block_counter = 0
        self.buffer = ""
        self.in_block = None
        self.block_buf = ""

    def feed(self, text: str):
        self.buffer += text
        self._consume()

    def flush(self):
        if self.buffer:
            self._append_plain(self.buffer)
            self.buffer = ""

    def _consume(self):
        while True:
            if self.in_block is None:
                matches = []
                for name, rx in (
                    ("code", self.CODE_OPEN),
                    ("run", self.RUN_OPEN),
                    ("html", self.HTML_OPEN),
                    ("out", self.OUT_OPEN),
                    ("win", self.WIN_OPEN),
                ):
                    m = rx.search(self.buffer)
                    if m:
                        matches.append((m.start(), name, m.end()))
                if not matches:
                    if len(self.buffer) > 30:
                        safe = self.buffer[:-30]
                        self._append_plain(safe)
                        self.buffer = self.buffer[-30:]
                    return
                matches.sort()
                pos, name, end = matches[0]
                if pos > 0:
                    self._append_plain(self.buffer[:pos])
                self.buffer = self.buffer[end:]
                self.in_block = name
                self.block_buf = ""
            else:
                if self.in_block == "win":
                    # win 块以 } 结束
                    m = re.search(r"\}", self.buffer)
                    if not m:
                        self.block_buf += self.buffer
                        self.buffer = ""
                        return
                    self.block_buf += self.buffer[:m.start()]
                    self.buffer = self.buffer[m.end():]
                    self._emit_block("win", self.block_buf)
                    self.in_block = None
                    self.block_buf = ""
                    continue
                close_rx = {
                    "code": self.CODE_CLOSE,
                    "run": self.RUN_CLOSE,
                    "html": self.HTML_CLOSE,
                    "out": self.OUT_CLOSE,
                }.get(self.in_block)
                if close_rx is None:
                    self.in_block = None
                    continue
                m = close_rx.search(self.buffer)
                if not m:
                    self.block_buf += self.buffer
                    self.buffer = ""
                    return
                self.block_buf += self.buffer[:m.start()]
                self.buffer = self.buffer[m.end():]
                self._emit_block(self.in_block, self.block_buf)
                self.in_block = None
                self.block_buf = ""

    def _append_plain(self, text: str):
        if not text:
            return
        html = _render_md_bold(text)
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()

    def _emit_block(self, kind: str, content: str):
        self.block_counter += 1
        bid = f"blk_{self.block_counter}"
        self.store[bid] = content

        if kind == "code":
            idx = content.find(",")
            fname = content[:idx].strip() if idx != -1 else content.strip()
            body = content[idx + 1:] if idx != -1 else ""
            self.store[bid] = body
            title = f"📄 文件: {fname}"
            color = "#2e7d32"
            bg = "#1b3a1f"
        elif kind == "run":
            title = "▶ 命令"
            color = "#ffb74d"
            bg = "#3a2e1b"
        elif kind == "html":
            title = "🌐 抓取"
            color = "#64b5f6"
            bg = "#1b2b3a"
        elif kind == "win":
            title = "🖱 Windows 控制"
            color = "#ce93d8"
            bg = "#2e1b3a"
        else:
            title = "⤶ 输出"
            color = "#9e9e9e"
            bg = "#2a2a2a"

        preview = content.strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + " ..."
        preview = _esc(preview)

        html_block = (
            f'<div style="margin:6px 0;">'
            f'<a href="{bid}" style="text-decoration:none;">'
            f'<span style="background:{bg};color:{color};'
            f'border:1px solid {color};border-radius:6px;'
            f'padding:4px 10px;font-family:Consolas,monospace;">'
            f'{_esc(title)}</span>'
            f'</a>'
            f'<span style="color:#888;margin-left:8px;font-size:12px;">'
            f'{preview} (点击看详情)</span>'
            f'</div>'
        )
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html_block)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()


# ============================================================
# 详情弹窗
# ============================================================

class AIDetailDialog(QDialog):
    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(content)
        layout.addWidget(editor)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(content))
        btn_row.addWidget(copy_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ============================================================
# AI 工作线程
# ============================================================

class AIFetchModelsThread(QThread):
    done = pyqtSignal(list, str)

    def __init__(self, base_url, api_key):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        try:
            client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            models = client.models.list()
            ids = sorted([m.id for m in models.data])
            self.done.emit(ids, "")
        except Exception as e:
            self.done.emit([], str(e))


class AIChatThread(QThread):
    chunk = pyqtSignal(str)
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, base_url, api_key, model, messages, enable_web, enable_think):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.enable_web = enable_web
        self.enable_think = enable_think
        self._stop_flag = False
        self._client = None
        self._stream = None

    def stop(self):
        self._stop_flag = True
        try:
            if self._stream is not None and hasattr(self._stream, "close"):
                self._stream.close()
        except Exception:
            pass
        try:
            if self._client is not None and hasattr(self._client, "close"):
                self._client.close()
        except Exception:
            pass

    def run(self):
        try:
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            kwargs = {
                "model": self.model,
                "messages": self.messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            extra = {}
            if self.enable_web:
                extra["enable_search"] = True
                extra["web_search"] = True
            if self.enable_think:
                extra["enable_thinking"] = True
                extra["thinking"] = {"type": "enabled"}
            if extra:
                kwargs["extra_body"] = extra
            try:
                stream = self._client.chat.completions.create(**kwargs)
            except Exception:
                kwargs.pop("stream_options", None)
                kwargs.pop("extra_body", None)
                stream = self._client.chat.completions.create(**kwargs)
            self._stream = stream

            usage = {}
            for event in stream:
                if self._stop_flag:
                    break
                if getattr(event, "usage", None):
                    usage = {
                        "prompt_tokens": event.usage.prompt_tokens,
                        "completion_tokens": event.usage.completion_tokens,
                        "total_tokens": event.usage.total_tokens,
                    }
                if event.choices:
                    delta = event.choices[0].delta
                    if delta is None:
                        continue
                    if getattr(delta, "content", None):
                        self.chunk.emit(delta.content)
                    rc = getattr(delta, "reasoning_content", None)
                    if rc:
                        self.chunk.emit(rc)
            self.done.emit(usage)
        except Exception as e:
            if self._stop_flag:
                self.done.emit({})
            else:
                self.error.emit(str(e))


class AIImageGenThread(QThread):
    done = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, base_url, api_key, model, prompt):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.prompt = prompt

    def run(self):
        try:
            client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            resp = client.images.generate(model=self.model, prompt=self.prompt,
                                          n=1, size="1024x1024")
            url = resp.data[0].url if resp.data and resp.data[0].url else ""
            b64 = getattr(resp.data[0], "b64_json", "") if resp.data else ""
            self.done.emit(url or "", b64 or "")
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
# AI 设置对话框（Material 3 风格）
# ============================================================

class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 设置")
        self.resize(620, 620)
        self.cfg = load_ai_config()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("AI 客户端设置")
        title.setProperty("class", "title-large")
        layout.addWidget(title)

        layout.addWidget(QLabel("API Key"))
        self.key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-...")
        layout.addWidget(self.key_edit)

        layout.addWidget(QLabel("Base URL"))
        self.url_edit = QLineEdit(self.cfg.get("base_url", "https://api.deepseek.com"))
        layout.addWidget(self.url_edit)

        row1 = QHBoxLayout()
        self.fetch_btn = QPushButton("获取模型列表")
        self.fetch_btn.setProperty("variant", "tonal")
        self.fetch_btn.clicked.connect(self.fetch_models)
        row1.addWidget(self.fetch_btn)
        self.status_label = QLabel("")
        self.status_label.setProperty("class", "body-small")
        row1.addWidget(self.status_label)
        row1.addStretch()
        layout.addLayout(row1)

        layout.addWidget(QLabel("聊天模型"))
        self.chat_combo = QComboBox()
        self.chat_combo.setEditable(True)
        layout.addWidget(self.chat_combo)

        layout.addWidget(QLabel("视觉模型（可选）"))
        self.vision_combo = QComboBox()
        self.vision_combo.setEditable(True)
        layout.addWidget(self.vision_combo)

        layout.addWidget(QLabel("图片生成模型（可选）"))
        self.image_combo = QComboBox()
        self.image_combo.setEditable(True)
        layout.addWidget(self.image_combo)

        layout.addWidget(QLabel("附加系统提示词（追加在内置协议之后）"))
        self.system_edit = QTextEdit()
        self.system_edit.setMaximumHeight(90)
        self.system_edit.setPlainText(self.cfg.get("extra_prompt", ""))
        layout.addWidget(self.system_edit)

        # Windows 控制状态
        win_status = QLabel("Windows 控制: " + WindowsController.get_status())
        win_status.setProperty("class", "body-small")
        layout.addWidget(win_status)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setProperty("variant", "text")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_and_accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        # 初始化模型列表
        models = self.cfg.get("models", [])
        for c in (self.chat_combo, self.vision_combo, self.image_combo):
            c.addItem("")
            for m in models:
                c.addItem(m)
        self.chat_combo.setCurrentText(self.cfg.get("chat_model", ""))
        self.vision_combo.setCurrentText(self.cfg.get("vision_model", ""))
        self.image_combo.setCurrentText(self.cfg.get("image_model", ""))

    def fetch_models(self):
        key = self.key_edit.text().strip()
        url = self.url_edit.text().strip()
        if not key or not url:
            QMessageBox.warning(self, "提示", "请先填写 API Key 和 Base URL")
            return
        self.status_label.setText("获取中...")
        self.fetch_btn.setEnabled(False)
        self._thread = AIFetchModelsThread(url, key)
        self._thread.done.connect(self._on_models)
        self._thread.start()

    def _on_models(self, ids, err):
        self.fetch_btn.setEnabled(True)
        if err:
            self.status_label.setText("失败: " + err)
            return
        self.status_label.setText(f"共 {len(ids)} 个模型")
        for c in (self.chat_combo, self.vision_combo, self.image_combo):
            cur = c.currentText()
            c.clear()
            c.addItem("")
            for m in ids:
                c.addItem(m)
            if cur:
                c.setCurrentText(cur)
        self._models = ids

    def save_and_accept(self):
        cfg = load_ai_config()
        cfg["api_key"] = self.key_edit.text().strip()
        cfg["base_url"] = self.url_edit.text().strip()
        cfg["chat_model"] = self.chat_combo.currentText().strip()
        cfg["vision_model"] = self.vision_combo.currentText().strip()
        cfg["image_model"] = self.image_combo.currentText().strip()
        cfg["extra_prompt"] = self.system_edit.toPlainText().strip()
        if hasattr(self, "_models"):
            cfg["models"] = self._models
        save_ai_config(cfg)
        self.accept()


# ============================================================
# AI 历史对话框
# ============================================================

class AIHistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 对话历史")
        self.resize(560, 480)
        self.selected_sid = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("打开")
        open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(open_btn)
        rename_btn = QPushButton("重命名")
        rename_btn.setProperty("variant", "tonal")
        rename_btn.clicked.connect(self._rename)
        btn_row.addWidget(rename_btn)
        del_btn = QPushButton("删除")
        del_btn.setProperty("variant", "outlined")
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setProperty("variant", "text")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        for s in AISessionStore.list_sessions():
            text = f"{s['title']}   ({s['count']} 条, {s['updated']})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.list_widget.addItem(item)

    def _current_sid(self):
        item = self.list_widget.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _open_selected(self):
        sid = self._current_sid()
        if sid:
            self.selected_sid = sid
            self.accept()

    def _rename(self):
        sid = self._current_sid()
        if not sid:
            return
        data = AISessionStore.load(sid)
        if not data:
            return
        new_title, ok = QInputDialog.getText(
            self, "重命名", "新标题:", text=data.get("title", ""))
        if ok and new_title.strip():
            AISessionStore.rename(sid, new_title.strip())
            self._refresh()

    def _delete(self):
        sid = self._current_sid()
        if not sid:
            return
        r = QMessageBox.question(
            self, "确认删除", "确定要删除这个对话吗?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if r == QMessageBox.StandardButton.Yes:
            AISessionStore.delete(sid)
            self._refresh()


# ============================================================
# AI 聊天面板（嵌入主窗口的 Tab）
# ============================================================

class AIChatPanel(QWidget):
    MAX_LOOPS = 8

    # 请求读取当前编辑器代码
    request_editor_context = pyqtSignal(str)  # 参数: 用途标记

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_ai_config()
        self.history = []
        self.current_image_b64 = ""
        self.thread = None
        self.gen_thread = None
        self.loop_count = 0
        self._ai_text = ""
        self.workspace = Path.cwd() / "ai_workspace"
        self.workspace.mkdir(exist_ok=True)
        self.executor = AIActionExecutor(self.workspace)
        self.store = {}
        self.session_id = None
        self._editor_context_text = ""

        self._build_ui()
        self.reload_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        self.info_label = QLabel("")
        top.addWidget(self.info_label)
        top.addStretch()
        self.token_label = QLabel("Token: 0 / 0 / 0")
        top.addWidget(self.token_label)

        ctx_btn = QPushButton("载入当前代码")
        ctx_btn.setProperty("variant", "tonal")
        ctx_btn.setFixedHeight(36)
        ctx_btn.clicked.connect(self.load_editor_context)
        top.addWidget(ctx_btn)

        history_btn = QPushButton("历史")
        history_btn.setProperty("variant", "outlined")
        history_btn.setFixedHeight(36)
        history_btn.clicked.connect(self.show_history_dialog)
        top.addWidget(history_btn)

        self.always_allow_btn = QPushButton()
        self.always_allow_btn.setProperty("variant", "outlined")
        self.always_allow_btn.setFixedHeight(36)
        self.always_allow_btn.clicked.connect(self.toggle_always_allow)
        top.addWidget(self.always_allow_btn)
        self.update_always_allow_button()

        new_btn = QPushButton("新对话")
        new_btn.setProperty("variant", "outlined")
        new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self.new_session)
        top.addWidget(new_btn)

        settings_btn = QPushButton("设置")
        settings_btn.setProperty("variant", "outlined")
        settings_btn.setFixedHeight(36)
        settings_btn.clicked.connect(self.open_settings)
        top.addWidget(settings_btn)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_anchor_clicked)
        self.browser.setStyleSheet(f"""
            QTextBrowser {{
                background: {M3.c('surface_container_high').name()};
                color: {M3.c('on_surface').name()};
                font-size: 14px; padding: 8px;
                border: 1px solid {M3.c('outline_variant').name()};
                border-radius: 14px;
            }}
        """)
        splitter.addWidget(self.browser)
        self.renderer = AIChatRenderer(self.browser, self.store)

        right = QWidget()
        rv = QVBoxLayout(right)
        self.image_label = QLabel("无图片")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumWidth(260)
        self.image_label.setStyleSheet(
            f"border: 1px solid {M3.c('outline_variant').name()}; border-radius: 6px;")
        rv.addWidget(self.image_label)
        clear_img = QPushButton("清除图片")
        clear_img.setProperty("variant", "outlined")
        clear_img.clicked.connect(self.clear_image)
        rv.addWidget(clear_img)

        ctx_label = QLabel("编辑器上下文")
        ctx_label.setProperty("class", "title-medium")
        rv.addWidget(ctx_label)
        self.ctx_preview = QTextEdit()
        self.ctx_preview.setReadOnly(True)
        self.ctx_preview.setFont(QFont(mono_family(), 9))
        self.ctx_preview.setMaximumHeight(180)
        rv.addWidget(self.ctx_preview)
        rv.addStretch()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        opt_row = QHBoxLayout()
        self.web_cb = QCheckBox("联网")
        self.think_cb = QCheckBox("深度思考")
        self.img_gen_cb = QCheckBox("图片生成模式")
        self.auto_ctx_cb = QCheckBox("自动携带编辑器代码")
        self.auto_ctx_cb.setChecked(True)
        opt_row.addWidget(self.web_cb)
        opt_row.addWidget(self.think_cb)
        opt_row.addWidget(self.img_gen_cb)
        opt_row.addWidget(self.auto_ctx_cb)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        input_row = QHBoxLayout()
        self.input = QTextEdit()
        self.input.setMaximumHeight(90)
        self.input.setPlaceholderText("输入消息, Ctrl+Enter 发送")
        self.input.installEventFilter(self)
        input_row.addWidget(self.input, 1)

        btn_col = QVBoxLayout()
        self.img_btn = QPushButton("图片")
        self.img_btn.setProperty("variant", "outlined")
        self.img_btn.setFixedHeight(34)
        self.img_btn.clicked.connect(self.pick_image)
        btn_col.addWidget(self.img_btn)
        self.txt_btn = QPushButton("文本")
        self.txt_btn.setProperty("variant", "outlined")
        self.txt_btn.setFixedHeight(34)
        self.txt_btn.clicked.connect(self.pick_text)
        btn_col.addWidget(self.txt_btn)
        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedHeight(34)
        self.send_btn.clicked.connect(self.send_or_stop)
        btn_col.addWidget(self.send_btn)
        input_row.addLayout(btn_col)
        layout.addLayout(input_row)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.send_or_stop()
                    return True
        return super().eventFilter(obj, event)

    # ---------- 编辑器上下文 ----------
    def load_editor_context(self):
        self.request_editor_context.emit("manual")

    def set_editor_context(self, code: str, file_path: str):
        if not code.strip():
            self.ctx_preview.setPlainText("(空)")
            self._editor_context_text = ""
            return
        fname = os.path.basename(file_path) if file_path else "未命名"
        preview = code if len(code) < 3000 else code[:3000] + "\n... (已截断)"
        self.ctx_preview.setPlainText(preview)
        self._editor_context_text = (
            f"\n\n----- 当前编辑器代码 ({fname}) -----\n{code}\n----- 代码结束 -----\n"
        )

    # ---------- 设置 ----------
    def open_settings(self):
        dlg = AISettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload_config()
            self.append_status("[设置已更新]", "#81c784")

    def update_always_allow_button(self):
        enabled = QSettings(
            "PyEdit", "PyEditIDE"
        ).value("actions/always_allow", False, type=bool)
        self.always_allow_btn.setText(
            "取消始终允许" if enabled else "始终允许")

    def toggle_always_allow(self):
        settings = QSettings("PyEdit", "PyEditIDE")
        enabled = settings.value("actions/always_allow", False, type=bool)
        settings.setValue("actions/always_allow", not enabled)
        settings.sync()
        self.update_always_allow_button()

    def reload_config(self):
        self.cfg = load_ai_config()
        model = self.cfg.get("chat_model", "(未配置)")
        self.info_label.setText(f"模型: {model}")
        if self.session_id:
            data = AISessionStore.load(self.session_id)
            if data:
                self.history = data.get("history", [])
                if not self.history or self.history[0].get("role") != "system":
                    self.history.insert(0, {"role": "system",
                                            "content": self.build_system_prompt()})
                else:
                    self.history[0] = {"role": "system",
                                       "content": self.build_system_prompt()}
                return
        self.session_id = AISessionStore.new_session("新对话")
        self.history = [{"role": "system", "content": self.build_system_prompt()}]
        AISessionStore.save(self.session_id, self.history)

    def build_system_prompt(self):
        extra = self.cfg.get("extra_prompt", "").strip()
        sysp = BASE_SYSTEM_PROMPT
        if extra:
            sysp += "\n\n用户附加要求:\n" + extra
        return sysp

    def _persist(self):
        if self.session_id:
            AISessionStore.save(self.session_id, self.history)

    # ---------- 会话 ----------
    def new_session(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "提示", "请先停止当前输出")
            return
        self.session_id = AISessionStore.new_session("新对话")
        self.reload_config()
        self.browser.clear()
        self.append_status("[已创建新对话]", "#81c784")

    def show_history_dialog(self):
        dlg = AIHistoryDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_sid:
            self.load_session(dlg.selected_sid)

    def load_session(self, sid):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "提示", "请先停止当前输出")
            return
        data = AISessionStore.load(sid)
        if not data:
            QMessageBox.warning(self, "错误", "会话不存在")
            return
        self.session_id = sid
        self.reload_config()
        self.browser.clear()
        for msg in data.get("history", []):
            if msg.get("role") == "system":
                continue
            content = msg.get("content", "")
            if msg.get("role") == "user":
                if isinstance(content, list):
                    text_parts = []
                    has_img = False
                    for part in content:
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            has_img = True
                    self.append_user(" ".join(text_parts))
                    if has_img:
                        self.append_status("[含图片]", "#888")
                else:
                    self.append_user(content)
            elif msg.get("role") == "assistant":
                self.append_ai_prefix()
                self.renderer = AIChatRenderer(self.browser, self.store)
                self.renderer.feed(content)
                self.renderer.flush()

    # ---------- 渲染 ----------
    def on_anchor_clicked(self, url: QUrl):
        bid = url.toString()
        if bid.startswith("blk_") and bid in self.store:
            dlg = AIDetailDialog(f"详情 - {bid}", self.store[bid], self)
            dlg.exec()

    def append_user(self, text: str):
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        html = (
            f'<div style="margin:10px 0 4px 0;">'
            f'<span style="color:#4fc3f7;font-weight:bold;">[我]</span> '
            f'{_render_md_bold(text)}'
            f'</div>'
        )
        cursor.insertHtml(html)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()

    def append_ai_prefix(self):
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            '<div style="margin:10px 0 4px 0;">'
            '<span style="color:#81c784;font-weight:bold;">[AI]</span> '
            '</div>'
        )
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()

    def append_result(self, text: str):
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        html = f'<div style="color:#888;font-size:13px;margin:4px 0;">{_render_md_bold(text)}</div>'
        cursor.insertHtml(html)
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()

    def append_status(self, text: str, color="#ffb74d"):
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            f'<div style="color:{color};font-size:13px;margin:6px 0;">{_esc(text)}</div>'
        )
        self.browser.setTextCursor(cursor)
        self.browser.ensureCursorVisible()

    # ---------- 图片/文本 ----------
    def clear_image(self):
        self.current_image_b64 = ""
        self.image_label.setText("无图片")
        self.image_label.setPixmap(QPixmap())

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            ext = Path(path).suffix.lower().lstrip(".")
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                    "gif": "gif", "webp": "webp", "bmp": "bmp"}.get(ext, "png")
            self.current_image_b64 = f"data:image/{mime};base64," + base64.b64encode(data).decode()
            pix = QPixmap(path)
            if not pix.isNull():
                self.image_label.setPixmap(pix.scaled(
                    260, 260, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def pick_text(self):
        exts = " ".join("*" + e for e in sorted(EDITABLE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文本文件", "", f"文本文件 ({exts});;所有文件 (*)")
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"读取失败: {e}")
            return
        name = Path(path).name
        block = f"\n\n----- 文件: {name} -----\n{content}\n----- 文件结束 -----\n"
        self.input.setPlainText(self.input.toPlainText() + block)

    # ---------- 发送 / 停止 ----------
    def send_or_stop(self):
        if self.thread and self.thread.isRunning():
            self.stop_generation()
        else:
            self.send()

    def stop_generation(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.append_status("[已停止输出]", "#ff7043")
            self.send_btn.setText("停止中...")
            self.send_btn.setEnabled(False)

    def send(self):
        if not HAS_OPENAI:
            QMessageBox.warning(self, "提示", "未安装 openai 库：pip install openai")
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if self.thread and self.thread.isRunning():
            return
        if not self.cfg.get("api_key"):
            QMessageBox.warning(self, "提示", "请先在设置中配置 API Key")
            return

        self.input.clear()
        self.loop_count = 0
        self.img_gen_cb.setEnabled(False)

        if self.img_gen_cb.isChecked():
            model = self.cfg.get("image_model", "").strip()
            if not model:
                QMessageBox.warning(self, "提示", "未配置图片生成模型")
                self.img_gen_cb.setEnabled(True)
                return
            self.append_user(text)
            self.append_status("图片生成中...", "#ffb74d")
            self.gen_thread = AIImageGenThread(
                self.cfg.get("base_url"), self.cfg.get("api_key"), model, text)
            self.gen_thread.done.connect(self.on_image_done)
            self.gen_thread.error.connect(self.on_error)
            self.gen_thread.start()
            return

        content = text
        use_vision = bool(self.current_image_b64)
        if use_vision:
            content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": self.current_image_b64}},
            ]
        self.history.append({"role": "user", "content": content})
        self._persist()

        data = AISessionStore.load(self.session_id) if self.session_id else None
        if data and data.get("title") == "新对话":
            AISessionStore.rename(self.session_id, text[:20] if len(text) > 20 else text)

        self.append_user(text)
        if use_vision:
            self.append_status("[含图片]", "#888")
        self.append_ai_prefix()
        self._start_chat_request()

    def _current_model(self):
        model = self.cfg.get("chat_model")
        for m in reversed(self.history):
            if m.get("role") == "user":
                if isinstance(m.get("content"), list):
                    vm = self.cfg.get("vision_model", "").strip()
                    if vm:
                        return vm
                break
        return model

    def _start_chat_request(self):
        self.send_btn.setEnabled(True)
        self.send_btn.setText("停止")
        self._ai_text = ""
        self.renderer = AIChatRenderer(self.browser, self.store)

        # 自动携带编辑器代码
        messages = list(self.history)
        if self.auto_ctx_cb.isChecked() and self._editor_context_text:
            # 注入到最后一条 user 消息之前
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    if isinstance(messages[i]["content"], str):
                        messages[i] = {
                            "role": "user",
                            "content": messages[i]["content"] + self._editor_context_text,
                        }
                    elif isinstance(messages[i]["content"], list):
                        messages[i]["content"] = list(messages[i]["content"]) + [
                            {"type": "text", "text": self._editor_context_text}]
                    break

        self.thread = AIChatThread(
            self.cfg.get("base_url"), self.cfg.get("api_key"),
            self._current_model(), messages,
            self.web_cb.isChecked(), self.think_cb.isChecked()
        )
        self.thread.chunk.connect(self.on_chunk)
        self.thread.done.connect(self.on_done)
        self.thread.error.connect(self.on_error)
        self.thread.start()

    def on_chunk(self, s):
        self._ai_text += s
        self.renderer.feed(s)

    def on_done(self, usage):
        self.renderer.flush()
        stopped = self.thread is not None and self.thread._stop_flag

        if self._ai_text:
            self.history.append({"role": "assistant", "content": self._ai_text})
            self._persist()
        if usage:
            self.token_label.setText(
                f"Token: 输入 {usage.get('prompt_tokens',0)} / 输出 {usage.get('completion_tokens',0)} / 共 {usage.get('total_tokens',0)}"
            )

        if stopped:
            self.send_btn.setEnabled(True)
            self.send_btn.setText("发送")
            self.img_gen_cb.setEnabled(True)
            self.append_status("[已停止]", "#ff7043")
            return

        if self.executor.has_actions(self._ai_text) and self.loop_count < self.MAX_LOOPS:
            self.loop_count += 1
            self.append_status("\n[执行动作中...]", "#ffb74d")
            result = self.executor.execute_all(self._ai_text)
            self.append_result(result)
            self.history.append({"role": "user", "content": result})
            self._persist()
            self.append_ai_prefix()
            self._start_chat_request()
            return

        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.img_gen_cb.setEnabled(True)
        self.clear_image()

    def on_error(self, err):
        self.renderer.flush()
        self.append_status(f"[错误] {err}", "#ef5350")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.img_gen_cb.setEnabled(True)

    def on_image_done(self, url, b64):
        if url:
            self.append_status(f"[图片URL] {url}", "#4fc3f7")
            self.image_label.setText(f'<a href="{url}">查看图片</a>')
            self.image_label.setOpenExternalLinks(True)
        elif b64:
            data = base64.b64decode(b64)
            img = QImage.fromData(data)
            pix = QPixmap.fromImage(img)
            self.image_label.setPixmap(pix.scaled(
                260, 260, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self.append_status("[图片已生成]", "#81c784")
        self.img_gen_cb.setEnabled(True)


# ============================================================
# 主窗口
# ============================================================

class PyEditIDE(QMainWindow):
    append_output_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        local_appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        self.workspace_dir = os.path.join(local_appdata, "PyEdit")
        os.makedirs(self.workspace_dir, exist_ok=True)

        self.python_files_dir = os.path.join(self.workspace_dir, "PythonFiles")
        os.makedirs(self.python_files_dir, exist_ok=True)
        self.save_dir = self.python_files_dir

        self.settings = QSettings("PyEdit", "PyEditIDE")
        saved_mode = self.settings.value("theme/mode", "light")
        saved_seed = self.settings.value("theme/seed", "#6750A4")
        saved_hct = self.settings.value("theme/hct", None)

        if saved_hct is not None:
            try:
                if isinstance(saved_hct, str):
                    h, c, t = [float(x) for x in saved_hct.split(",")]
                else:
                    h, c, t = saved_hct
                M3.init_from_hct(h, c, t)
            except Exception:
                M3.init(saved_seed)
        else:
            M3.init(saved_seed)

        M3.set_mode(saved_mode)
        self.current_theme = saved_mode
        self.current_seed = saved_seed

        self.current_file = None
        self.current_encoding = "utf-8"
        self.is_running = False
        self.terminal_expanded = False
        self.terminal_manager = TerminalManager()
        self.execution_thread = None
        self.execution_process = None
        self.stop_execution = False
        self.default_file = os.path.join(tempfile.gettempdir(), "default.py")

        self.history_manager = HistoryManager(self.workspace_dir)
        self.append_output_signal.connect(self._append_output_impl)

        self._sheet = None
        self.init_ui()

    def _append_output_impl(self, text):
        cursor = self.output_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output_area.setTextCursor(cursor)
        self.output_area.ensureCursorVisible()

    def _append_output(self, text):
        self.append_output_signal.emit(text)

    # ---------------- 主题 ----------------

    def _save_theme_settings(self):
        self.settings.setValue("theme/mode", self.current_theme)
        if self.current_seed:
            self.settings.setValue("theme/seed", self.current_seed)
        hct = M3.get_hct()
        if hct is not None:
            self.settings.setValue("theme/hct", f"{hct[0]},{hct[1]},{hct[2]}")
        self.settings.sync()

    def apply_theme(self):
        self.setStyleSheet(build_stylesheet())
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab and isinstance(tab, EditorTab):
                tab.editor.highlighter = PythonSyntaxHighlighter(tab.editor.document())
        self.update_status()

    def toggle_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        M3.set_mode(self.current_theme)
        self._save_theme_settings()
        self.apply_theme()

    def set_seed(self, hex_color):
        self.current_seed = hex_color
        M3.init(hex_color)
        self._save_theme_settings()
        self.apply_theme()

    def set_seed_from_wallpaper(self):
        img_path, _ = QFileDialog.getOpenFileName(
            self, "选择壁纸图片", os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not img_path:
            return
        M3.init_from_image(img_path)
        self.current_seed = "#from_wallpaper"
        self._save_theme_settings()
        self.apply_theme()
        self.status_bar.showMessage(f"已从壁纸生成动态配色: {os.path.basename(img_path)}")

    # ---------------- UI ----------------

    def init_ui(self):
        self.setWindowTitle("PyEdit IDE + AI — Material 3")
        self.setGeometry(100, 100, 1500, 920)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 工具栏
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction("新建", self.open_new_file_dialog)
        toolbar.addAction("打开", self.open_file)

        save_action = toolbar.addAction("保存", self.save_code)
        save_action.setShortcut(QKeySequence("Ctrl+S"))

        run_action = toolbar.addAction("运行", self.run_code)
        run_action.setShortcut(QKeySequence("F5"))

        toolbar.addAction("停止", self.stop_code)
        toolbar.addSeparator()
        toolbar.addAction("终端", self.toggle_terminal)
        toolbar.addAction("停止终端", self.stop_terminal)
        toolbar.addSeparator()
        toolbar.addAction("历史", self.show_history_dialog)
        toolbar.addSeparator()
        toolbar.addAction("主题", self.toggle_theme)
        toolbar.addAction("调色", self.show_theme_sheet)
        toolbar.addSeparator()

        # AI 快捷
        toolbar.addAction("AI 设置", self.open_ai_settings)
        toolbar.addAction("AI 历史", self.open_ai_history)

        # 主分栏
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)

        left_card = QFrame()
        left_card.setProperty("class", "card")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(0)

        self.workspace_browser = WorkspaceBrowser(
            self.workspace_dir, self.history_manager.history_dir, self)
        self.workspace_browser.file_double_clicked.connect(self.open_workspace_file)
        self.workspace_browser.status_message.connect(
            lambda msg: self.status_bar.showMessage(msg))
        left_layout.addWidget(self.workspace_browser)

        main_splitter.addWidget(left_card)

        right_card = QFrame()
        right_card.setProperty("class", "card")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)

        # 主 Tab：编辑器页 / AI 页
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setDocumentMode(True)

        # --- 编辑器页 ---
        editor_page = QWidget()
        ep_layout = QVBoxLayout(editor_page)
        ep_layout.setContentsMargins(0, 0, 0, 0)
        ep_layout.setSpacing(8)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        ep_layout.addWidget(self.tab_widget, 2)

        output_label = QLabel("输出结果")
        output_label.setProperty("class", "title-medium")
        ep_layout.addWidget(output_label)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont(mono_family(), 10))
        self.output_area.setMaximumHeight(180)
        ep_layout.addWidget(self.output_area)

        program_input_layout = QHBoxLayout()
        program_input_layout.setSpacing(8)
        self.program_input = QLineEdit()
        self.program_input.setPlaceholderText("在此输入程序 input() 的内容，回车发送")
        self.program_input.returnPressed.connect(self.send_program_input)
        program_input_layout.addWidget(self.program_input, 1)

        send_program_btn = QPushButton("发送输入")
        send_program_btn.setProperty("variant", "tonal")
        send_program_btn.setFixedHeight(40)
        send_program_btn.clicked.connect(self.send_program_input)
        program_input_layout.addWidget(send_program_btn)
        ep_layout.addLayout(program_input_layout)

        self.main_tab_widget.addTab(editor_page, "编辑器")

        # --- AI 页 ---
        self.ai_panel = AIChatPanel(self)
        self.ai_panel.request_editor_context.connect(self._provide_editor_context)
        self.main_tab_widget.addTab(self.ai_panel, "AI 助手")

        right_layout.addWidget(self.main_tab_widget)
        main_splitter.addWidget(right_card)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setSizes([320, 1180])

        main_layout.addWidget(main_splitter, 1)

        # 底部终端
        self.terminal_group = QFrame()
        self.terminal_group.setProperty("class", "card")
        terminal_layout = QVBoxLayout(self.terminal_group)
        terminal_layout.setContentsMargins(14, 12, 14, 12)
        terminal_layout.setSpacing(10)

        term_title = QLabel("终端")
        term_title.setProperty("class", "title-medium")
        terminal_layout.addWidget(term_title)

        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFont(QFont(mono_family(), 10))
        self.terminal_output.setMinimumHeight(140)
        self.terminal_output.setText(self.terminal_manager.get_prompt())
        terminal_layout.addWidget(self.terminal_output)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("输入命令…")
        self.terminal_input.returnPressed.connect(self.execute_terminal_command)
        input_layout.addWidget(self.terminal_input, 1)

        send_btn = QPushButton("发送命令")
        send_btn.setFixedHeight(40)
        send_btn.clicked.connect(self.execute_terminal_command)
        input_layout.addWidget(send_btn)

        send_text_btn = QPushButton("发送输入")
        send_text_btn.setProperty("variant", "tonal")
        send_text_btn.setFixedHeight(40)
        send_text_btn.clicked.connect(self.send_terminal_input)
        input_layout.addWidget(send_text_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setProperty("variant", "outlined")
        clear_btn.setFixedHeight(40)
        clear_btn.clicked.connect(self.clear_terminal)
        input_layout.addWidget(clear_btn)

        terminal_layout.addLayout(input_layout)
        self.terminal_group.setVisible(False)
        main_layout.addWidget(self.terminal_group)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.create_new_tab()
        self.apply_theme()

    # ---------------- 编辑器上下文回传 ----------------

    def _provide_editor_context(self, _):
        tab = self.current_tab()
        if tab is None:
            return
        code = tab.get_content()
        self.ai_panel.set_editor_context(code, tab.file_path or "")

    # ---------------- Bottom Sheet ----------------

    def _close_sheet(self):
        self._sheet = None

    def _open_sheet(self, title, content_widget, max_h=520):
        if self._sheet is not None:
            self._sheet.dismiss()
        sheet = ModalBottomSheet(self, title=title,
                                 content_widget=content_widget,
                                 max_height=max_h)
        sheet.closed.connect(self._close_sheet)
        self._sheet = sheet
        sheet.show_sheet()

    def show_theme_sheet(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 8, 24, 8)
        v.setSpacing(12)

        v.addWidget(QLabel("预设配色"))
        preset_row = QHBoxLayout()
        preset_row.setSpacing(10)
        for name, hexc in M3.PRESETS:
            b = QPushButton(name)
            b.setFixedHeight(40)
            b.setStyleSheet(
                f"QPushButton {{ background: {hexc}; color: white; "
                f"border-radius: 20px; padding: 8px 14px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {_lighter(QColor(hexc)).name()}; }}")
            b.clicked.connect(lambda _, h=hexc: self.set_seed(h))
            preset_row.addWidget(b)
        preset_row.addStretch()
        v.addLayout(preset_row)

        v.addSpacing(6)
        v.addWidget(QLabel("从壁纸取色（动态取色 / Monet）"))

        wall_btn = QPushButton("选择壁纸图片")
        wall_btn.setProperty("variant", "tonal")
        wall_btn.setFixedHeight(48)
        wall_btn.clicked.connect(self.set_seed_from_wallpaper)
        v.addWidget(wall_btn)

        v.addSpacing(6)
        v.addWidget(QLabel("当前主题模式"))
        mode_row = QHBoxLayout()
        light_btn = QPushButton("浅色")
        light_btn.setProperty("variant", "outlined")
        light_btn.setFixedHeight(44)
        light_btn.clicked.connect(self._set_light_mode)
        mode_row.addWidget(light_btn)

        dark_btn = QPushButton("深色")
        dark_btn.setProperty("variant", "outlined")
        dark_btn.setFixedHeight(44)
        dark_btn.clicked.connect(self._set_dark_mode)
        mode_row.addWidget(dark_btn)
        mode_row.addStretch()
        v.addLayout(mode_row)

        v.addStretch()
        self._open_sheet("主题与动态取色", w, max_h=460)

    def _set_light_mode(self):
        self.current_theme = "light"
        M3.set_mode("light")
        self._save_theme_settings()
        self.apply_theme()

    def _set_dark_mode(self):
        self.current_theme = "dark"
        M3.set_mode("dark")
        self._save_theme_settings()
        self.apply_theme()

    def show_new_file_sheet(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 8, 24, 8)
        v.setSpacing(12)

        v.addWidget(QLabel(f"保存到: {self.save_dir}"))
        v.addWidget(QLabel("文件名"))
        fn = QLineEdit()
        fn.setPlaceholderText("example.py")
        v.addWidget(fn)

        v.addWidget(QLabel("编码"))
        enc = QComboBox()
        enc.addItems(["utf-8", "gbk", "utf-16"])
        v.addWidget(enc)

        v.addStretch()
        row = QHBoxLayout()
        row.addStretch()

        cancel = QPushButton("取消")
        cancel.setProperty("variant", "text")
        cancel.setFixedHeight(44)
        cancel.clicked.connect(lambda: self._sheet and self._sheet.dismiss())
        row.addWidget(cancel)

        create = QPushButton("创建")
        create.setFixedHeight(44)
        create.clicked.connect(lambda: self._do_create_from_sheet(fn.text(),
                                                                  enc.currentText()))
        row.addWidget(create)
        v.addLayout(row)

        self._open_sheet("新建文件", w, max_h=460)

    def _do_create_from_sheet(self, filename, encoding):
        if not filename:
            QMessageBox.warning(self, "提示", "请输入文件名")
            return
        if not filename.endswith(".py"):
            filename += ".py"
        fp = os.path.join(self.save_dir, filename)
        content = "# 新建文件\nprint('Hello PyEdit!')\n"
        try:
            with open(fp, 'w', encoding=encoding) as f:
                f.write(content)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建文件失败: {e}")
            return
        self.create_new_tab(content, fp, encoding)
        if self._sheet:
            self._sheet.dismiss()
        self.workspace_browser.refresh()
        self.update_status()

    # ---------------- AI 设置 / 历史快捷入口 ----------------

    def open_ai_settings(self):
        dlg = AISettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.ai_panel.reload_config()
            self.status_bar.showMessage("AI 设置已更新")

    def open_ai_history(self):
        self.main_tab_widget.setCurrentWidget(self.ai_panel)
        self.ai_panel.show_history_dialog()

    # ---------------- 历史 ----------------

    def show_history_sheet(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 8, 24, 8)
        v.setSpacing(10)

        filter_row = QHBoxLayout()
        self._hist_current_only = QPushButton("仅当前文件")
        self._hist_current_only.setCheckable(True)
        self._hist_current_only.setChecked(True)
        self._hist_current_only.setProperty("variant", "tonal")
        self._hist_current_only.setFixedHeight(38)
        filter_row.addWidget(self._hist_current_only)

        self._hist_all = QPushButton("全部文件")
        self._hist_all.setCheckable(True)
        self._hist_all.setProperty("variant", "outlined")
        self._hist_all.setFixedHeight(38)
        filter_row.addWidget(self._hist_all)
        filter_row.addStretch()

        grp = QButtonGroup(w)
        grp.setExclusive(True)
        grp.addButton(self._hist_current_only)
        grp.addButton(self._hist_all)

        v.addLayout(filter_row)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        left_label = QLabel("历史版本")
        left_label.setProperty("class", "title-medium")
        left_layout.addWidget(left_label)

        lw = QListWidget()
        lw.setMinimumWidth(240)
        left_layout.addWidget(lw)

        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        right_label = QLabel("内容预览")
        right_label.setProperty("class", "title-medium")
        right_layout.addWidget(right_label)

        pv = QTextEdit()
        pv.setReadOnly(True)
        pv.setFont(QFont(mono_family(), 10))
        right_layout.addWidget(pv)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([280, 420])
        v.addWidget(split, 1)

        row = QHBoxLayout()
        row.addStretch()

        restore = QPushButton("恢复此版本")
        restore.setFixedHeight(44)

        def reload_history():
            lw.clear()
            if self._hist_current_only.isChecked():
                tab = self.current_tab()
                fp = tab.file_path if tab else None
                if not fp:
                    lw.addItem("(当前文件未保存，无历史)")
                    return
                entries = self.history_manager.list_history(fp)
            else:
                entries = self.history_manager.list_history(None)

            if not entries:
                lw.addItem("(暂无历史记录)")
                return

            for hp, n in entries:
                base = os.path.basename(hp).split("-第")[0] if "-第" in os.path.basename(hp) else os.path.basename(hp)
                display = f"{base}  第{n}次记录"
                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, hp)
                lw.addItem(item)

        def on_sel(item):
            hp = item.data(Qt.ItemDataRole.UserRole)
            if not hp:
                return
            content, _ = self.history_manager.load_history(hp)
            pv.setPlainText(content)

        lw.itemClicked.connect(on_sel)

        def do_restore():
            item = lw.currentItem()
            if not item:
                return
            hp = item.data(Qt.ItemDataRole.UserRole)
            if not hp:
                return
            content, enc = self.history_manager.load_history(hp)
            self.create_new_tab(content, None, enc)
            if self._sheet:
                self._sheet.dismiss()

        restore.clicked.connect(do_restore)
        row.addWidget(restore)

        close = QPushButton("关闭")
        close.setProperty("variant", "outlined")
        close.setFixedHeight(44)
        close.clicked.connect(lambda: self._sheet and self._sheet.dismiss())
        row.addWidget(close)
        v.addLayout(row)

        def on_filter_changed():
            reload_history()
            if lw.count() > 0:
                lw.setCurrentRow(0)
                on_sel(lw.item(0))

        self._hist_current_only.clicked.connect(on_filter_changed)
        self._hist_all.clicked.connect(on_filter_changed)

        reload_history()
        if lw.count() > 0 and lw.item(0).data(Qt.ItemDataRole.UserRole):
            lw.setCurrentRow(0)
            on_sel(lw.item(0))

        self._open_sheet("历史记录（多版本）", w, max_h=600)

    # ---------------- Tab / 文件 ----------------

    def create_new_tab(self, content="", file_path=None, encoding='utf-8'):
        tab = EditorTab(self)
        tab.set_content(content, file_path, encoding)
        index = self.tab_widget.addTab(tab, tab.get_display_name())
        self.tab_widget.setCurrentIndex(index)
        return tab

    def current_tab(self):
        return self.tab_widget.currentWidget()

    def close_tab(self, index):
        tab = self.tab_widget.widget(index)
        if tab and tab.modified:
            reply = QMessageBox.question(
                self, "确认", f"'{tab.get_display_name()}' 已修改，是否保存？",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self.save_tab(tab)
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self.tab_widget.removeTab(index)
        if self.tab_widget.count() == 0:
            self.create_new_tab()

    def on_tab_changed(self, index):
        tab = self.tab_widget.widget(index)
        if tab:
            self.current_file = tab.file_path
            self.current_encoding = tab.encoding
            self.update_status()

    def update_tab_title(self, tab):
        index = self.tab_widget.indexOf(tab)
        if index >= 0:
            name = tab.get_display_name()
            if tab.modified:
                name += " •"
            self.tab_widget.setTabText(index, name)

    # ---------------- 归档 ----------------

    def _archive_history_if_changed(self, tab):
        content = tab.get_content()
        file_path = tab.file_path or self.default_file

        latest = self.history_manager.latest_history_content(file_path)
        if latest is not None and latest == content:
            return False

        hp = self.history_manager.save_history(file_path, content, tab.encoding)
        if hp:
            self.workspace_browser.refresh()
            return True
        return False

    # ---------------- 保存 ----------------

    def save_tab(self, tab):
        if tab.file_path is None:
            tab.file_path = self.default_file

        content = tab.get_content()

        try:
            with open(tab.file_path, 'w', encoding=tab.encoding) as f:
                f.write(content)
            tab.modified = False
            self.update_tab_title(tab)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
            return False

        archived = self._archive_history_if_changed(tab)

        if archived:
            self.status_bar.showMessage(f"已保存并归档: {tab.file_path}")
        else:
            self.status_bar.showMessage(f"已保存（内容无变化，未归档）: {tab.file_path}")
        return True

    def save_old_on_run(self, tab):
        if self._archive_history_if_changed(tab):
            self.status_bar.showMessage("已归档当前版本")

    def save_code(self):
        tab = self.current_tab()
        if tab is None:
            return False
        return self.save_tab(tab)

    def _read_file_auto(self, path):
        for enc in ['utf-8', 'gbk', 'utf-16']:
            try:
                with open(path, 'r', encoding=enc) as f:
                    return f.read(), enc
            except UnicodeDecodeError:
                continue
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), 'utf-8'

    def open_workspace_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法打开文件: {e}")
            return
        if ext in EDITABLE_EXTS or self._is_probably_text(path):
            try:
                content, enc = self._read_file_auto(path)
                self.create_new_tab(content, path, enc)
                self.status_bar.showMessage(f"已打开: {path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"打开失败: {e}")
        else:
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法打开文件: {e}")

    def _is_probably_text(self, path):
        try:
            with open(path, 'rb') as f:
                chunk = f.read(1024)
            if b'\x00' in chunk:
                return False
            chunk.decode('utf-8')
            return True
        except Exception:
            return False

    def open_file(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "打开文件", self.save_dir, "All Files (*)")
        if fp:
            try:
                content, enc = self._read_file_auto(fp)
                self.create_new_tab(content, fp, enc)
                self.check_syntax(content, fp)
                self.status_bar.showMessage(f"已打开: {fp}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"打开文件失败: {e}")

    def open_new_file_dialog(self):
        self.show_new_file_sheet()

    def check_syntax(self, code, filename):
        try:
            compile(code, filename, 'exec')
            self._append_output("✓ 语法检查通过\n")
            return True
        except SyntaxError as e:
            self._append_output("⚠ 语法检查发现问题:\n")
            self._append_output(f"  第 {e.lineno} 行, 第 {e.offset or 0} 列: {e.msg}\n")
            if e.text:
                self._append_output(f"  {e.text.rstrip()}\n")
                if e.offset:
                    self._append_output(f"  {' ' * (e.offset - 1)}^\n")
            return False
        except Exception as e:
            self._append_output(f"⚠ 检查时出错: {e}\n")
            return False

    # ---------------- 运行 ----------------

    def stop_code(self):
        if not self.is_running:
            QMessageBox.warning(self, "提示", "没有正在运行的代码")
            return
        self.stop_execution = True
        self.status_bar.showMessage("正在停止代码...")
        self._append_output("\n--- 正在停止代码 ---\n")

        proc = self.execution_process
        if proc and proc.poll() is None:
            try:
                pid = proc.pid
                if platform.system() == "Windows":
                    try:
                        subprocess.run(f'taskkill /F /T /PID {pid}', shell=True,
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception:
                        pass
                try:
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        try: child.kill()
                        except Exception: pass
                    parent.kill()
                except Exception:
                    pass
                try: proc.wait(timeout=1)
                except Exception: pass
            except Exception:
                pass

        self.is_running = False
        self.execution_process = None

    def run_code(self):
        if self.is_running:
            QMessageBox.warning(self, "提示", "代码正在执行中")
            return

        tab = self.current_tab()
        if tab is None:
            return
        code = tab.get_content()
        if not code.strip():
            QMessageBox.warning(self, "提示", "没有代码可执行")
            return

        if tab.file_path is None:
            tab.file_path = self.default_file

        try:
            with open(tab.file_path, 'w', encoding=tab.encoding) as f:
                f.write(code)
            tab.modified = False
            self.update_tab_title(tab)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
            return

        self.save_old_on_run(tab)
        self.output_area.clear()

        try:
            compile(code, tab.file_path, 'exec')
        except SyntaxError as e:
            self._append_output("⚠ 语法检查发现问题，未运行:\n")
            self._append_output(f"  第 {e.lineno} 行, 第 {e.offset or 0} 列: {e.msg}\n")
            if e.text:
                self._append_output(f"  {e.text.rstrip()}\n")
                if e.offset:
                    self._append_output(f"  {' ' * (e.offset - 1)}^\n")
            return

        self.is_running = True
        self.stop_execution = False
        self.update_status()
        self._append_output(f"运行: {tab.file_path}\n\n")

        file_path = tab.file_path

        def execute():
            try:
                env = os.environ.copy()
                env['PYTHONUNBUFFERED'] = '1'
                env['PYTHONIOENCODING'] = 'utf-8'
                cf = subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0

                self.execution_process = subprocess.Popen(
                    [sys.executable, "-u", file_path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    cwd=os.path.dirname(file_path) or None,
                    creationflags=cf, env=env, bufsize=0
                )

                stdout = self.execution_process.stdout
                buf = bytearray()
                while True:
                    try:
                        b = stdout.read(1)
                    except Exception:
                        break
                    if not b:
                        break
                    buf.extend(b)
                    try:
                        text = buf.decode('utf-8')
                        if text:
                            self._append_output(text)
                            buf.clear()
                    except UnicodeDecodeError:
                        if len(buf) > 4:
                            try:
                                text = buf.decode('utf-8', errors='replace')
                                self._append_output(text)
                                buf.clear()
                            except Exception:
                                pass

                if buf:
                    try:
                        self._append_output(buf.decode('utf-8', errors='replace'))
                    except Exception:
                        pass
                try:
                    self.execution_process.wait()
                except Exception:
                    pass
            except Exception as e:
                self._append_output(f"\n运行错误: {e}\n")
            finally:
                self.is_running = False
                self.execution_process = None
                self._append_output("\n--- 执行结束 ---\n")

        self.execution_thread = threading.Thread(target=execute, daemon=True)
        self.execution_thread.start()

    def send_program_input(self):
        if (not self.is_running or self.execution_process is None
                or self.execution_process.poll() is not None):
            QMessageBox.warning(self, "提示", "没有正在运行的程序")
            return
        text = self.program_input.text()
        try:
            self.execution_process.stdin.write((text + "\n").encode('utf-8'))
            self.execution_process.stdin.flush()
            self._append_output(text + "\n")
            self.program_input.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"发送输入失败: {e}")

    # ---------------- 终端 ----------------

    def toggle_terminal(self):
        self.terminal_expanded = not self.terminal_expanded
        self.terminal_group.setVisible(self.terminal_expanded)

    def execute_terminal_command(self):
        command = self.terminal_input.text().strip()
        if not command:
            return

        def output_callback(text):
            if text:
                QMetaObject.invokeMethod(
                    self.terminal_output, "append",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, text))

        def run_command():
            if self.terminal_manager.is_running:
                QMetaObject.invokeMethod(
                    self.terminal_output, "append",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, "\n终端正在执行命令，请先停止再执行新命令\n"))
                return
            QMetaObject.invokeMethod(
                self.terminal_output, "append",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, f"{self.terminal_manager.get_prompt()}{command}"))
            self.terminal_manager.execute_command(command, output_callback)
            while self.terminal_manager.is_running:
                time.sleep(0.1)
            QMetaObject.invokeMethod(
                self.terminal_output, "append",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, self.terminal_manager.get_prompt()))
            QMetaObject.invokeMethod(
                self.terminal_input, "clear",
                Qt.ConnectionType.QueuedConnection)

        threading.Thread(target=run_command, daemon=True).start()

    def send_terminal_input(self):
        text = self.terminal_input.text().strip()
        if not text:
            return
        if self.terminal_manager.send_input(text):
            QMetaObject.invokeMethod(
                self.terminal_output, "append",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, text))
            QMetaObject.invokeMethod(
                self.terminal_input, "clear",
                Qt.ConnectionType.QueuedConnection)
        else:
            QMessageBox.warning(self, "提示", "无法发送输入，终端没有正在运行的命令")

    def stop_terminal(self):
        if not self.terminal_manager.is_running:
            QMessageBox.information(self, "提示", "终端没有正在运行的命令")
            return
        self.terminal_manager.stop_command()
        self.terminal_output.append("\n--- 终端命令已停止 ---")
        self.terminal_output.append(self.terminal_manager.get_prompt())
        self.status_bar.showMessage("终端命令已停止")

    def clear_terminal(self):
        self.terminal_manager.stop_command()
        self.terminal_output.setText(self.terminal_manager.get_prompt())

    def show_history_dialog(self):
        self.show_history_sheet()

    # ---------------- 状态 / 退出 ----------------

    def update_status(self):
        tab = self.current_tab()
        file_info = tab.file_path if tab and tab.file_path else '未打开文件'
        enc = tab.encoding if tab else self.current_encoding
        theme = "深色" if M3.is_dark() else "浅色"
        self.status_bar.showMessage(
            f"主题: {theme}  |  编码: {enc}  |  文件: {file_info}")

    def closeEvent(self, event):
        self._save_theme_settings()

        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab and tab.file_path:
                try:
                    with open(tab.file_path, 'w', encoding=tab.encoding) as f:
                        f.write(tab.get_content())
                except Exception:
                    pass
            elif tab and tab.get_content().strip():
                try:
                    with open(self.default_file, 'w', encoding=tab.encoding) as f:
                        f.write(tab.get_content())
                except Exception:
                    pass

        if self.is_running and self.execution_process and self.execution_process.poll() is None:
            try:
                pid = self.execution_process.pid
                if platform.system() == "Windows":
                    try:
                        subprocess.run(f'taskkill /F /T /PID {pid}', shell=True,
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception:
                        pass
                try:
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        try: child.kill()
                        except Exception: pass
                    parent.kill()
                except Exception:
                    pass
            except Exception:
                pass

        if self.terminal_manager.is_running:
            try:
                self.terminal_manager.stop_command()
            except Exception:
                pass

        event.accept()


def main():
    if HAS_OPENAI is False:
        print("提示: 未安装 openai，AI 功能将不可用。pip install openai")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("PyEdit")
    app.setApplicationName("PyEditIDE")
    window = PyEditIDE()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
