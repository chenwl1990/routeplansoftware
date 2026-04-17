import os
import math

import pygmt
import numpy as np
import json
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QColor, QPixmap, QWheelEvent, QImage, QPainter, QPen, QBrush, QPainterPath, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QFileDialog,
    QTextEdit,
    QLineEdit,
    QDialog,
    QDialogButtonBox,
    QColorDialog,
    QMessageBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QSplitter,
    QGraphicsEllipseItem,
    QGraphicsRectItem,
    QGraphicsPathItem,
)

ROI_MAP_PNG = "roi_map.png"

BOX_FILE = "rov_box_points.txt"
POINTS_FILE = "points.txt"
CONFIG_FILE = "roi_last_config.json"
MAIN_CONFIG_FILE = "gmt_last_config.json"
ADDPOINT_TXT = "addpoint.txt"
USER_POINT_SHAPES = ["circle", "square", "triangle", "star"]
USER_POINT_LABEL_POSITIONS = ["右上", "左上", "右下", "左下", "上中", "下中", "左中", "右中"]
POINTS_SPEED_MPS = 0.5


# =========================
# 配置记忆
# =========================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)


def load_main_point_speeds():
    try:
        with open(MAIN_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return []
    speeds = []
    for value in cfg.get("point_speeds", []):
        try:
            speeds.append(float(value))
        except (TypeError, ValueError):
            continue
    return speeds


def normalize_user_points(raw_points):
    normalized = []
    if not isinstance(raw_points, list):
        return normalized
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        try:
            lon = float(item.get("lon"))
            lat = float(item.get("lat"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "#ff0000")).strip() or "#ff0000"
        shape = str(item.get("shape", "circle")).strip().lower()
        if shape not in USER_POINT_SHAPES:
            shape = "circle"
        label_pos = str(item.get("label_pos", "右上")).strip()
        if label_pos not in USER_POINT_LABEL_POSITIONS:
            label_pos = "右上"
        try:
            font_size = int(item.get("font_size", 8))
        except (TypeError, ValueError):
            font_size = 8
        font_size = max(8, min(24, font_size))
        normalized.append(
            {
                "lon": lon,
                "lat": lat,
                "name": name,
                "color": color,
                "shape": shape,
                "label_pos": label_pos,
                "font_size": font_size,
            }
        )
    return normalized


def load_addpoint_txt():
    if not os.path.isfile(ADDPOINT_TXT):
        return []
    points = []
    with open(ADDPOINT_TXT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                continue
            points.append(
                {
                    "lon": lon,
                    "lat": lat,
                    "name": parts[2],
                    "color": parts[3],
                    "shape": parts[4],
                    "label_pos": parts[5] if len(parts) >= 6 else "右上",
                    "font_size": int(parts[6]) if len(parts) >= 7 else 8,
                }
            )
    return normalize_user_points(points)


def _format_addpoint_line(point):
    return (
        f"{float(point['lon']):.4f} "
        f"{float(point['lat']):.4f} "
        f"{str(point.get('name', '')).strip()} "
        f"{str(point.get('color', '#ff0000')).strip() or '#ff0000'} "
        f"{str(point.get('shape', 'circle')).strip().lower() or 'circle'} "
        f"{str(point.get('label_pos', '右上')).strip() or '右上'} "
        f"{int(point.get('font_size', 8))}"
    )


def write_addpoint_txt(points):
    with open(ADDPOINT_TXT, "w", encoding="utf-8") as f:
        for point in normalize_user_points(points):
            f.write(_format_addpoint_line(point) + "\n")


def append_addpoint_txt(point_dict):
    point = normalize_user_points([point_dict])
    if not point:
        return
    with open(ADDPOINT_TXT, "a", encoding="utf-8") as f:
        f.write(_format_addpoint_line(point[0]) + "\n")


def user_point_plot_style(shape):
    return {
        "circle": "c0.22c",
        "square": "s0.22c",
        "triangle": "t0.26c",
        "star": "a0.30c",
    }.get(shape, "c0.22c")


# =========================
def load_box():
    pts = []
    with open(BOX_FILE, "r") as f:
        for line in f:
            x, y = map(float, line.split())
            pts.append((x, y))
    return pts

def save_box(box):
    with open(BOX_FILE, "w") as f:
        for x, y in box:
            f.write(f"{x} {y}\n")


def load_track():
    pts = []
    with open(POINTS_FILE, "r") as f:
        for line in f:
            x, y = map(float, line.split())
            pts.append((x, y))
    return pts


def write_dark_cpt():
    with open("dark.cpt", "w") as f:
        f.write("""-10000 0 0 0 -0.1 0 0 0
-0.1 0 0 0 10000 0 0 0
""")


def densify_track_with_project(points, spacing_m=100):
    if not points:
        return np.array([]), np.array([])
    if len(points) == 1:
        return np.array([points[0][0]]), np.array([points[0][1]])

    spacing_km = spacing_m / 1000.0
    dense_pts = []

    for i in range(len(points) - 1):
        lon1, lat1 = points[i]
        lon2, lat2 = points[i + 1]
        seg = pygmt.project(
            center=[lon1, lat1],
            endpoint=[lon2, lat2],
            generate=spacing_km,
            unit=True,
        )
        for _, row in seg.iterrows():
            dense_pts.append((float(row["r"]), float(row["s"])))

    dense_unique = []
    for p in dense_pts:
        if not dense_unique or p != dense_unique[-1]:
            dense_unique.append(p)
    if dense_unique[-1] != points[-1]:
        dense_unique.append(points[-1])

    lons = np.array([p[0] for p in dense_unique], dtype=float)
    lats = np.array([p[1] for p in dense_unique], dtype=float)
    return lons, lats


def grid_z_to_depth_m(z):
    z = np.asarray(z, dtype=float)
    if z.size == 0:
        return z
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        return z
    med = np.nanmedian(finite)
    if np.isfinite(med) and med <= 0:
        return np.where(np.isnan(z), np.nan, -z)
    return z


def haversine_distance_m(lon1, lat1, lon2, lat2):
    r = 6371000.0
    lon1_r, lat1_r = math.radians(lon1), math.radians(lat1)
    lon2_r, lat2_r = math.radians(lon2), math.radians(lat2)
    dlon = lon2_r - lon1_r
    dlat = lat2_r - lat1_r
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def build_segment_labels(points, speed_mps=POINTS_SPEED_MPS, speeds_mps=None):
    labels = []
    if not points or len(points) < 2:
        return labels
    speed_mps = max(float(speed_mps), 0.01)
    speeds_mps = list(speeds_mps) if speeds_mps is not None else [speed_mps] * len(points)
    if len(speeds_mps) < len(points):
        speeds_mps.extend([speed_mps] * (len(points) - len(speeds_mps)))
    for i in range(1, len(points)):
        lon1, lat1 = points[i - 1]
        lon2, lat2 = points[i]
        seg_m = haversine_distance_m(lon1, lat1, lon2, lat2)
        row_speed = max(float(speeds_mps[i]), 0.01)
        seg_h = seg_m / row_speed / 3600.0
        labels.append(f"S{i}_{seg_h:.1f}h")
    return labels


def nice_tick(span, n=4):
    raw = span / n
    if raw == 0:
        return 1
    mag = 10 ** np.floor(np.log10(raw))
    r = raw / mag
    if r <= 1:
        return 1 * mag
    elif r <= 2:
        return 2 * mag
    elif r <= 5:
        return 5 * mag
    return 10 * mag


def to_dm(v):
    sign = "-" if v < 0 else ""
    v = abs(v)
    deg = int(v)
    minutes = (v - deg) * 60
    return f"{sign}{deg}°{minutes:.4f}'"


def _merc_y_rad(lat_rad):
    return math.log(math.tan(math.pi / 4 + lat_rad / 2))


def _lat_from_merc_y_rad(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def lonlat_to_image_xy(lon, lat, map_rect, region, proj_mode="Mercator"):
    mx, my, mw, mh = map_rect
    lon0, lon1, lat0, lat1 = region
    if mw <= 1 or mh <= 1:
        return mx, my
    lon = max(min(lon, lon1), lon0)
    lat = max(min(lat, lat1), lat0)
    sx = (lon - lon0) / (lon1 - lon0) * (mw - 1)
    if proj_mode == "Mercator":
        m = _merc_y_rad(math.radians(lat))
        m_n = _merc_y_rad(math.radians(lat1))
        m_s = _merc_y_rad(math.radians(lat0))
        denom = m_s - m_n
        sy = (m - m_n) / denom * (mh - 1) if abs(denom) > 1e-15 else (mh - 1) / 2
    elif proj_mode == "Cylindrical Equidistant":
        sy = (lat1 - lat) / (lat1 - lat0) * (mh - 1)
    else:
        sy = (lat1 - lat) / (lat1 - lat0) * (mh - 1)
    return mx + sx, my + sy


def image_xy_to_lonlat(px, py, map_rect, region, proj_mode="Mercator"):
    mx, my, mw, mh = map_rect
    lon0, lon1, lat0, lat1 = region
    if mw <= 1 or mh <= 1:
        return lon0, lat0
    px = max(mx, min(mx + mw - 1, float(px)))
    py = max(my, min(my + mh - 1, float(py)))
    sx = px - mx
    sy = py - my
    lon = lon0 + (sx / (mw - 1)) * (lon1 - lon0)
    if proj_mode == "Mercator":
        m_n = _merc_y_rad(math.radians(lat1))
        m_s = _merc_y_rad(math.radians(lat0))
        t = sy / (mh - 1)
        m = m_n + t * (m_s - m_n)
        lat = _lat_from_merc_y_rad(m)
    else:
        lat = lat1 - (sy / (mh - 1)) * (lat1 - lat0)
    return lon, lat


def five_point_star_path(cx, cy, outer_r=7.0, inner_r=3.0):
    path = QPainterPath()
    for i in range(10):
        ang = math.pi / 2 - i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        x = cx + r * math.cos(ang)
        y = cy - r * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def label_anchor_xy(label_pos, sx, sy, br):
    offsets = {
        "右上": (8, -br.height() - 6),
        "左上": (-br.width() - 8, -br.height() - 6),
        "右下": (8, 6),
        "左下": (-br.width() - 8, 6),
        "上中": (-br.width() / 2, -br.height() - 8),
        "下中": (-br.width() / 2, 8),
        "左中": (-br.width() - 10, -br.height() / 2),
        "右中": (10, -br.height() / 2),
    }
    dx, dy = offsets.get(label_pos, offsets["右上"])
    return sx + dx, sy + dy


def detect_map_rect(image):
    w = image.width()
    h = image.height()
    if image.isNull() or w < 10 or h < 10:
        return 0, 0, w, h

    def dark_count_col(x):
        count = 0
        for y in range(h):
            c = QColor(image.pixel(x, y))
            if c.red() < 80 and c.green() < 80 and c.blue() < 80:
                count += 1
        return count

    def dark_count_row(y):
        count = 0
        for x in range(w):
            c = QColor(image.pixel(x, y))
            if c.red() < 80 and c.green() < 80 and c.blue() < 80:
                count += 1
        return count

    left_range = range(0, max(1, int(w * 0.3)))
    right_range = range(max(0, int(w * 0.7)), w)
    top_range = range(0, max(1, int(h * 0.3)))
    bottom_range = range(max(0, int(h * 0.7)), h)

    left = max(left_range, key=dark_count_col)
    right = max(right_range, key=dark_count_col)
    top = max(top_range, key=dark_count_row)
    bottom = max(bottom_range, key=dark_count_row)

    if right <= left or bottom <= top:
        return 0, 0, w, h
    return left, top, right - left, bottom - top


# =========================
# 🌍 真实地理圆（关键新增）
# =========================
class RoiMapPreviewView(QGraphicsView):
    """小图预览：滚轮以光标处缩放（向下滑放大），左键拖拽平移。"""

    _ZOOM_STEP = 1.15
    _SCALE_MIN = 0.03
    _SCALE_MAX = 80.0
    user_point_clicked = Signal(float, float)
    user_point_edit_clicked = Signal(float, float)
    user_point_delete_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._map_rect = (0, 0, 0, 0)
        self._region = None
        self._proj_mode = "Mercator"
        self._overlay_items = []
        self._user_point_pick_mode = False
        self._user_point_edit_mode = False
        self._user_point_delete_mode = False
        self.setMinimumWidth(520)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(240, 240, 240))
        self._show_placeholder()

    def _show_placeholder(self):
        self._scene.clear()
        self._pixmap_item = None
        self._overlay_items = []
        self._region = None
        t = self._scene.addText(
            "点击「生成下潜计划小图」后在此预览 roi_map.png\n"
            "滚轮：向下滑放大、向上滑缩小；左键拖拽平移。"
        )
        t.setDefaultTextColor(QColor(90, 90, 90))
        br = t.boundingRect()
        t.setPos(-br.width() / 2, -br.height() / 2)
        self.setSceneRect(-320, -100, 640, 200)
        self.resetTransform()

    def set_map_pixmap(self, pix: QPixmap, region=None, map_rect=None, proj_mode="Mercator"):
        if pix.isNull():
            return
        self._scene.clear()
        self._overlay_items = []
        self._pixmap_item = self._scene.addPixmap(pix)
        self._pixmap_item.setZValue(0)
        self.setSceneRect(self._pixmap_item.boundingRect())
        self._region = region
        self._proj_mode = proj_mode
        self._map_rect = map_rect or (0, 0, pix.width(), pix.height())
        self.resetTransform()

    def show_load_error(self, path: str):
        self._scene.clear()
        self._pixmap_item = None
        t = self._scene.addText(f"无法加载预览：{path}")
        t.setDefaultTextColor(QColor(192, 0, 0))
        br = t.boundingRect()
        t.setPos(-br.width() / 2, -br.height() / 2)
        self.setSceneRect(-280, -50, 560, 100)
        self.resetTransform()

    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap_item is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = self._ZOOM_STEP if delta < 0 else 1.0 / self._ZOOM_STEP
        old = self.transform()
        self.scale(factor, factor)
        s = self.transform().m11()
        if s < self._SCALE_MIN or s > self._SCALE_MAX:
            self.setTransform(old)
        event.accept()

    def set_user_point_pick_mode(self, enabled: bool):
        self._user_point_pick_mode = bool(enabled)
        if enabled:
            self._user_point_edit_mode = False
            self._user_point_delete_mode = False
        self.setCursor(Qt.CursorShape.CrossCursor if (self._user_point_pick_mode or self._user_point_edit_mode or self._user_point_delete_mode) else Qt.CursorShape.ArrowCursor)

    def set_user_point_edit_mode(self, enabled: bool):
        self._user_point_edit_mode = bool(enabled)
        if enabled:
            self._user_point_pick_mode = False
            self._user_point_delete_mode = False
        self.setCursor(Qt.CursorShape.CrossCursor if (self._user_point_pick_mode or self._user_point_edit_mode or self._user_point_delete_mode) else Qt.CursorShape.ArrowCursor)

    def set_user_point_delete_mode(self, enabled: bool):
        self._user_point_delete_mode = bool(enabled)
        if enabled:
            self._user_point_pick_mode = False
            self._user_point_edit_mode = False
        self.setCursor(Qt.CursorShape.CrossCursor if (self._user_point_pick_mode or self._user_point_edit_mode or self._user_point_delete_mode) else Qt.CursorShape.ArrowCursor)

    def _clear_overlay_only(self):
        for item in self._overlay_items:
            self._scene.removeItem(item)
        self._overlay_items.clear()

    def _build_user_point_item(self, shape, sx, sy, color):
        pen = QPen(color.darker(150))
        pen.setWidthF(1.0)
        brush = QBrush(color)
        if shape == "square":
            item = QGraphicsRectItem(sx - 5, sy - 5, 10, 10)
            item.setPen(pen)
            item.setBrush(brush)
            return item
        if shape == "triangle":
            path = QPainterPath()
            path.moveTo(sx, sy - 6)
            path.lineTo(sx - 5.5, sy + 4.5)
            path.lineTo(sx + 5.5, sy + 4.5)
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setBrush(brush)
            return item
        if shape == "star":
            item = QGraphicsPathItem(five_point_star_path(sx, sy))
            item.setPen(pen)
            item.setBrush(brush)
            return item
        item = QGraphicsEllipseItem(sx - 5, sy - 5, 10, 10)
        item.setPen(pen)
        item.setBrush(brush)
        return item

    def _add_user_point_label(self, point, sx, sy):
        name = str(point.get("name", "")).strip()
        if not name:
            return
        text_item = self._scene.addSimpleText(name)
        font = text_item.font()
        font.setPointSize(max(8, min(24, int(point.get("font_size", 8)))))
        text_item.setFont(font)
        text_item.setBrush(QBrush(QColor("black")))
        br = text_item.boundingRect()
        text_x, text_y = label_anchor_xy(str(point.get("label_pos", "右上")), sx, sy, br)
        bg = QGraphicsRectItem(text_x - 3, text_y - 2, br.width() + 6, br.height() + 4)
        bg_pen = QPen()
        bg_pen.setStyle(Qt.PenStyle.NoPen)
        bg.setPen(bg_pen)
        bg.setBrush(QColor(255, 255, 255, 128))
        bg.setZValue(6)
        text_item.setPos(text_x, text_y)
        text_item.setZValue(7)
        self._scene.addItem(bg)
        self._overlay_items.extend([bg, text_item])

    def update_user_points_overlay(self, user_points):
        self._clear_overlay_only()
        if self._pixmap_item is None or self._region is None:
            return
        for point in normalize_user_points(user_points):
            sx, sy = lonlat_to_image_xy(point["lon"], point["lat"], self._map_rect, self._region, self._proj_mode)
            color = QColor(str(point.get("color", "#ff0000")))
            if not color.isValid():
                color = QColor("#ff0000")
            item = self._build_user_point_item(str(point.get("shape", "circle")).lower(), sx, sy, color)
            item.setZValue(5)
            self._scene.addItem(item)
            self._overlay_items.append(item)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and (self._user_point_pick_mode or self._user_point_edit_mode or self._user_point_delete_mode) and self._pixmap_item is not None and self._region is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            lon, lat = image_xy_to_lonlat(scene_pos.x(), scene_pos.y(), self._map_rect, self._region, self._proj_mode)
            if self._user_point_pick_mode:
                self.user_point_clicked.emit(lon, lat)
            elif self._user_point_edit_mode:
                self.user_point_edit_clicked.emit(lon, lat)
            else:
                self.user_point_delete_clicked.emit(lon, lat)
            event.accept()
            return
        super().mousePressEvent(event)


def draw_geo_circle(fig, lon, lat, radius_m, n=120):
    R = 6378137.0
    ang = np.linspace(0, 2*np.pi, n)

    lons = []
    lats = []

    for a in ang:
        dx = radius_m * np.cos(a)
        dy = radius_m * np.sin(a)

        dlon = dx / (R * np.cos(np.radians(lat))) * 180/np.pi
        dlat = dy / R * 180/np.pi

        lons.append(lon + dlon)
        lats.append(lat + dlat)

    fig.plot(x=lons, y=lats, pen="0.8p,red")


class PointEditorDialog(QDialog):
    def __init__(self, parent=None, point=None):
        super().__init__(parent)
        self.setWindowTitle("编辑点")
        self.point_data = None

        point = point or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lon_edit = QLineEdit(str(point.get("lon", "")))
        self.lat_edit = QLineEdit(str(point.get("lat", "")))
        self.name_edit = QLineEdit(str(point.get("name", "")))

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(USER_POINT_SHAPES)
        self.shape_combo.setCurrentText(str(point.get("shape", "circle")).lower())

        self.label_pos_combo = QComboBox()
        self.label_pos_combo.addItems(USER_POINT_LABEL_POSITIONS)
        self.label_pos_combo.setCurrentText(str(point.get("label_pos", "右上")))

        self.font_size_edit = QLineEdit(str(point.get("font_size", 8)))
        self.color_btn = QPushButton("选择颜色")
        self._color = str(point.get("color", "#ff0000"))
        self.color_btn.clicked.connect(self._pick_color)
        self._sync_color_btn()

        form.addRow("经度", self.lon_edit)
        form.addRow("纬度", self.lat_edit)
        form.addRow("名称", self.name_edit)
        form.addRow("颜色", self.color_btn)
        form.addRow("形状", self.shape_combo)
        form.addRow("标注位置", self.label_pos_combo)
        form.addRow("字体大小", self.font_size_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_color_btn(self):
        self.color_btn.setText(self._color)
        self.color_btn.setStyleSheet(f"background:{self._color}; color:black;")

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, "选择颜色")
        if color.isValid():
            self._color = color.name()
            self._sync_color_btn()

    def accept(self):
        try:
            lon = float(self.lon_edit.text().strip())
            lat = float(self.lat_edit.text().strip())
            font_size = int(self.font_size_edit.text().strip() or "8")
        except ValueError:
            QMessageBox.warning(self, "输入错误", "经纬度和字体大小必须是有效数字。")
            return
        self.point_data = {
            "lon": lon,
            "lat": lat,
            "name": self.name_edit.text().strip(),
            "color": self._color,
            "shape": self.shape_combo.currentText(),
            "label_pos": self.label_pos_combo.currentText(),
            "font_size": max(8, min(24, font_size)),
        }
        super().accept()


class PointModeDialog(QDialog):
    MODE_MANUAL = "manual"
    MODE_PICK = "pick"
    MODE_EDIT = "edit"
    MODE_DELETE = "delete"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("点功能")
        self.selected_mode = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择点标注模式："))
        for text, mode in [
            ("手动添加点", self.MODE_MANUAL),
            ("鼠标点击添加点", self.MODE_PICK),
            ("编辑点", self.MODE_EDIT),
            ("删除点", self.MODE_DELETE),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, m=mode: self._select(m))
            layout.addWidget(btn)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _select(self, mode):
        self.selected_mode = mode
        self.accept()


# =========================
class ROIApp(QWidget):

    def __init__(self, tif_file=None):
        super().__init__()

        self.setWindowTitle("HOV 下潜底图制作")

        self.cfg = load_config()
        self.data_file = tif_file or self.cfg.get("file")

        left = QWidget()
        left.setMinimumWidth(500)
        layout = QVBoxLayout(left)

        self.file_label = QLabel(self.data_file if self.data_file else "未选择数据文件")

        btn_file = QPushButton("选择TIF / GRD")
        btn_file.clicked.connect(self.select_file)

        layout.addWidget(self.file_label)
        layout.addWidget(btn_file)

        # ROI
        self.xmin = QLineEdit(str(self.cfg.get("xmin", "")))
        self.xmax = QLineEdit(str(self.cfg.get("xmax", "")))
        self.ymin = QLineEdit(str(self.cfg.get("ymin", "")))
        self.ymax = QLineEdit(str(self.cfg.get("ymax", "")))

        layout.addWidget(QLabel("xmin"))
        layout.addWidget(self.xmin)
        layout.addWidget(QLabel("xmax"))
        layout.addWidget(self.xmax)
        layout.addWidget(QLabel("ymin"))
        layout.addWidget(self.ymin)
        layout.addWidget(QLabel("ymax"))
        layout.addWidget(self.ymax)

        # 潜次号
        self.dive_id = QLineEdit(str(self.cfg.get("dive_id", "")))
        layout.addWidget(QLabel("潜次号"))
        layout.addWidget(self.dive_id)

        # 等值线
        self.contour = QLineEdit(str(self.cfg.get("contour", 100)))
        self.annotation = QLineEdit(str(self.cfg.get("annotation", 100)))

        layout.addWidget(QLabel("等值线"))
        layout.addWidget(self.contour)
        layout.addWidget(QLabel("标注"))
        layout.addWidget(self.annotation)

        # 颜色
        self.contour_color = QComboBox()
        self.contour_color.addItems(["black", "white", "red", "blue", "yellow", "pink"])
        self.contour_color.setCurrentText(self.cfg.get("contour_color", "black"))

        layout.addWidget(QLabel("等值线颜色"))
        layout.addWidget(self.contour_color)

        # 色标
        self.cmap = QComboBox()
        self.cmap.addItems(["geo", "haxby", "viridis", "turbo", "rainbow", "batlow", "dark"])
        self.cmap.setCurrentText(self.cfg.get("cmap", "geo"))

        layout.addWidget(QLabel("色标"))
        layout.addWidget(self.cmap)
        
        self.proj = QComboBox()
        self.proj.addItems(["Mercator","UTM","Transverse Mercator","Cylindrical Equidistant"])
        self.proj.setCurrentText(self.cfg.get("proj", "Mercator"))
        
        layout.addWidget(QLabel("投影系统"))
        layout.addWidget(self.proj)
        self.btn_point_tools = QPushButton("点功能")
        self.btn_point_tools.setMinimumHeight(40)
        self.btn_point_tools.clicked.connect(self.open_point_tools)
        layout.addWidget(self.btn_point_tools)
        
        self.lines_input = QTextEdit()
        self.lines_input.setPlaceholderText(
            "lon lat name color\n"
            "lon lat name color\n"
            "\n"
            "lon lat name color\n"
            "（空行表示新线）"
        )
        self.lines_input.setMinimumHeight(120)

        layout.addWidget(QLabel("手动线 (lon lat name color)"))
        layout.addWidget(self.lines_input)


        
        
        btn = QPushButton("生成下潜计划小图")
        btn.setMinimumHeight(44)
        btn.clicked.connect(self.run)
        layout.addWidget(btn)

        self.preview = RoiMapPreviewView()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 1120])

        outer = QVBoxLayout(self)
        outer.addWidget(splitter)
        self.setLayout(outer)

        self.setMinimumSize(1520, 960)
        self.resize(1720, 1040)
        self.user_points = load_addpoint_txt()
        self._pending_user_point_pick = False
        self._pending_user_point_edit = False
        self._pending_user_point_delete = False
        self.preview.user_point_clicked.connect(self._handle_user_point_picked)
        self.preview.user_point_edit_clicked.connect(self._handle_user_point_edit_clicked)
        self.preview.user_point_delete_clicked.connect(self._handle_user_point_delete_clicked)

        if os.path.isfile(ROI_MAP_PNG):
            pix = QPixmap(ROI_MAP_PNG)
            if not pix.isNull():
                map_rect = detect_map_rect(pix.toImage())
                region = self._current_region_from_inputs()
                self.preview.set_map_pixmap(pix, region=region, map_rect=map_rect, proj_mode=self.proj.currentText().strip())
                self.preview.update_user_points_overlay(self.user_points)

    # =========================
    def get_projection(self, xmin, xmax):
        mode = self.proj.currentText()

        if mode == "Mercator":
            return "M6i"

        if mode == "UTM":
            zone = int(((xmin + xmax) / 2 + 180) / 6) + 1
            return f"U{zone}/6i"

        if mode == "Transverse Mercator":
            return "T6i"

        if mode == "Cylindrical Equidistant":
            return "Q6i"

        return "M6i"

    def _current_region_from_inputs(self):
        try:
            return [
                float(self.xmin.text()),
                float(self.xmax.text()),
                float(self.ymin.text()),
                float(self.ymax.text()),
            ]
        except ValueError:
            return None

    def _refresh_preview_user_points(self):
        self.user_points = load_addpoint_txt()
        self.preview.update_user_points_overlay(self.user_points)

    def _stop_user_point_modes(self):
        self.preview.set_user_point_pick_mode(False)
        self.preview.set_user_point_edit_mode(False)
        self.preview.set_user_point_delete_mode(False)
        self._pending_user_point_pick = False
        self._pending_user_point_edit = False
        self._pending_user_point_delete = False

    def open_point_tools(self):
        dlg = PointModeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.selected_mode == PointModeDialog.MODE_MANUAL:
            self._open_user_point_editor()
        elif dlg.selected_mode == PointModeDialog.MODE_PICK:
            self.start_user_point_pick_mode()
        elif dlg.selected_mode == PointModeDialog.MODE_EDIT:
            self.start_user_point_edit_mode()
        elif dlg.selected_mode == PointModeDialog.MODE_DELETE:
            self.start_user_point_delete_mode()

    def _open_user_point_editor(self, point=None, replace_index=None):
        dlg = PointEditorDialog(self, point=point)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.point_data:
            if replace_index is not None:
                self.user_points = load_addpoint_txt()
                if 0 <= replace_index < len(self.user_points):
                    self.user_points[replace_index] = dlg.point_data
                    write_addpoint_txt(self.user_points)
                else:
                    append_addpoint_txt(dlg.point_data)
            else:
                append_addpoint_txt(dlg.point_data)
            self.user_points = load_addpoint_txt()
            self._stop_user_point_modes()
            self._refresh_preview_user_points()

    def start_user_point_pick_mode(self):
        if self.preview._region is None:
            QMessageBox.information(self, "提示", "请先生成下潜计划小图。")
            return
        self._stop_user_point_modes()
        self._pending_user_point_pick = True
        self.preview.set_user_point_pick_mode(True)

    def start_user_point_edit_mode(self):
        self.user_points = load_addpoint_txt()
        if not self.user_points:
            QMessageBox.information(self, "提示", "当前没有可编辑的点。")
            return
        if self.preview._region is None:
            QMessageBox.information(self, "提示", "请先生成下潜计划小图。")
            return
        self._stop_user_point_modes()
        self._pending_user_point_edit = True
        self.preview.set_user_point_edit_mode(True)

    def start_user_point_delete_mode(self):
        self.user_points = load_addpoint_txt()
        if not self.user_points:
            QMessageBox.information(self, "提示", "当前没有可删除的点。")
            return
        if self.preview._region is None:
            QMessageBox.information(self, "提示", "请先生成下潜计划小图。")
            return
        self._stop_user_point_modes()
        self._pending_user_point_delete = True
        self.preview.set_user_point_delete_mode(True)

    def _handle_user_point_picked(self, lon, lat):
        if not self._pending_user_point_pick:
            return
        self._stop_user_point_modes()
        self._open_user_point_editor({"lon": lon, "lat": lat, "font_size": 8, "label_pos": "右上"})

    def _handle_user_point_edit_clicked(self, lon, lat):
        if not self._pending_user_point_edit:
            return
        self.user_points = load_addpoint_txt()
        idx = self._find_nearest_user_point(lon, lat)
        if idx is None:
            return
        point = dict(self.user_points[idx])
        self._stop_user_point_modes()
        self._open_user_point_editor(point=point, replace_index=idx)

    def _find_nearest_user_point(self, lon, lat):
        if self.preview._region is None or not self.user_points:
            return None
        best_idx = None
        best_dist = None
        click_x, click_y = lonlat_to_image_xy(lon, lat, self.preview._map_rect, self.preview._region, self.preview._proj_mode)
        for i, point in enumerate(self.user_points):
            px, py = lonlat_to_image_xy(point["lon"], point["lat"], self.preview._map_rect, self.preview._region, self.preview._proj_mode)
            dist = math.hypot(px - click_x, py - click_y)
            if best_dist is None or dist < best_dist:
                best_idx = i
                best_dist = dist
        if best_dist is not None and best_dist <= 16.0:
            return best_idx
        return None

    def _handle_user_point_delete_clicked(self, lon, lat):
        if not self._pending_user_point_delete:
            return
        self.user_points = load_addpoint_txt()
        idx = self._find_nearest_user_point(lon, lat)
        if idx is not None:
            self.user_points.pop(idx)
            write_addpoint_txt(self.user_points)
            self._refresh_preview_user_points()
        self._stop_user_point_modes()

    def _show_roi_preview(self):
        pix = QPixmap(ROI_MAP_PNG)
        if pix.isNull():
            self.preview.show_load_error(ROI_MAP_PNG)
        else:
            region = self._current_region_from_inputs()
            map_rect = detect_map_rect(pix.toImage())
            self.preview.set_map_pixmap(pix, region=region, map_rect=map_rect, proj_mode=self.proj.currentText().strip())
            self._refresh_preview_user_points()

    def _paint_addpoints_on_roi_image(self, image_path, region):
        user_points = load_addpoint_txt()
        track = load_track()
        segment_labels = build_segment_labels(track, speeds_mps=load_main_point_speeds())
        if not user_points and not segment_labels:
            return
        image = QImage(image_path)
        if image.isNull():
            return
        map_rect = detect_map_rect(image)
        proj_mode = self.proj.currentText().strip()
        mx, my, mw, mh = map_rect
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if len(track) >= 2:
            seg_font = QFont("Helvetica", 8)
            seg_font.setBold(True)
            painter.setFont(seg_font)
            fm = painter.fontMetrics()
            for i in range(1, len(track)):
                x0, y0 = lonlat_to_image_xy(
                    track[i - 1][0], track[i - 1][1], map_rect, region, proj_mode=proj_mode
                )
                x1, y1 = lonlat_to_image_xy(
                    track[i][0], track[i][1], map_rect, region, proj_mode=proj_mode
                )
                mid_x = (x0 + x1) / 2.0
                mid_y = (y0 + y1) / 2.0
                angle_deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
                if angle_deg > 90:
                    angle_deg -= 180
                elif angle_deg < -90:
                    angle_deg += 180
                label = (
                    segment_labels[i - 1]
                    if i - 1 < len(segment_labels)
                    else f"S{i}"
                )
                text_w = fm.horizontalAdvance(label)
                text_h = fm.height()
                painter.save()
                painter.translate(mid_x, mid_y)
                painter.rotate(angle_deg)
                painter.fillRect(
                    int(-text_w / 2 - 5),
                    int(-text_h / 2 - 3),
                    text_w + 10,
                    text_h + 6,
                    QColor(173, 216, 230, 200),
                )
                painter.setPen(QPen(QColor("black")))
                painter.drawText(
                    int(-text_w / 2),
                    int(-text_h / 2 + fm.ascent()),
                    label,
                )
                painter.restore()

        for point in user_points:
            lon = float(point["lon"])
            lat = float(point["lat"])
            if not (region[0] <= lon <= region[1] and region[2] <= lat <= region[3]):
                continue
            sx, sy = lonlat_to_image_xy(lon, lat, map_rect, region, proj_mode=proj_mode)
            name = str(point.get("name", "")).strip()
            if not name:
                continue
            font = QFont("Helvetica", int(point.get("font_size", 8)))
            painter.setFont(font)
            fm = painter.fontMetrics()
            br = fm.boundingRect(name)
            text_x, text_y = label_anchor_xy(
                str(point.get("label_pos", "右上")),
                sx,
                sy,
                br,
            )
            text_x = int(text_x)
            text_y = int(text_y)
            text_w = fm.horizontalAdvance(name) + 6
            text_h = fm.height() + 4
            label_rect = (text_x - 3, text_y - 2, text_w, text_h)
            if (
                label_rect[0] < mx
                or label_rect[1] < my
                or label_rect[0] + label_rect[2] > mx + mw
                or label_rect[1] + label_rect[3] > my + mh
            ):
                continue
            painter.fillRect(
                label_rect[0],
                label_rect[1],
                label_rect[2],
                label_rect[3],
                QColor(255, 255, 255, 128),
            )
            painter.setPen(QPen(QColor("black")))
            painter.drawText(text_x, text_y + fm.ascent(), name)
        painter.end()
        image.save(image_path)

    def select_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据",
            "",
            "Grid (*.tif *.grd *.nc)"
        )
        if f:
            self.data_file = f
            self.file_label.setText(f)

    # =========================
    def save_state(self):
        cfg = {
            "file": self.data_file,
            "xmin": self.xmin.text(),
            "xmax": self.xmax.text(),
            "ymin": self.ymin.text(),
            "ymax": self.ymax.text(),
            "contour": self.contour.text(),
            "annotation": self.annotation.text(),
            "contour_color": self.contour_color.currentText(),
            "cmap": self.cmap.currentText(),
            "proj": self.proj.currentText(),
            "dive_id": self.dive_id.text()
            
        }
        save_config(cfg)

    # =========================
    def run(self):

        if not self.data_file:
            print("❌ 未选择数据")
            return

        track = load_track()
        dive_id = self.dive_id.text().strip()

        try:
            xmin = float(self.xmin.text())
            xmax = float(self.xmax.text())
            ymin = float(self.ymin.text())
            ymax = float(self.ymax.text())

            box = [
                [xmin, ymin],
                [xmax, ymin],
                [xmax, ymax],
                [xmin, ymax],
                [xmin, ymin]
            ]
            save_box(box)

        except:
            box = load_box()
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)

        region = [xmin, xmax, ymin, ymax]
        projection = self.get_projection(xmin, xmax)

        x_tick = nice_tick(xmax - xmin)
        y_tick = nice_tick(ymax - ymin)

        cmap = self.cmap.currentText()
        if cmap == "dark":
            write_dark_cpt()
            cmap = "dark.cpt"

        fig = pygmt.Figure()

        pygmt.config(
            MAP_FRAME_TYPE="plain",
            FORMAT_GEO_MAP="ddd.xxxxF",
            MAP_FRAME_PEN="1p,black"
        )

        # =========================
        # 地形
        # =========================
        fig.grdimage(
            grid=self.data_file,
            region=region,
            projection=projection,
            cmap=cmap
        )

        fig.grdcontour(
            grid=self.data_file,
            interval=float(self.contour.text()),
            annotation=float(self.annotation.text()),
            pen=f"0.7p,{self.contour_color.currentText()}"
        )

        # =========================
        # track
        # =========================
        depths = None
        start_depth = np.nan

        if track:
            try:
                dense_lons, dense_lats = densify_track_with_project(track, spacing_m=100)
            except Exception as e:
                print(f"⚠️ dense point 计算失败，回退原始航点: {e}")
                dense_lons = np.array([p[0] for p in track], dtype=float)
                dense_lats = np.array([p[1] for p in track], dtype=float)

            dense_points_path = "_tmp_roi_dense_points.txt"
            with open(dense_points_path, "w") as f:
                for lon, lat in zip(dense_lons, dense_lats):
                    f.write(f"{lon} {lat}\n")

            try:
                df = pygmt.grdtrack(points=dense_points_path, grid=self.data_file)
                arr = np.asarray(df.to_numpy(), dtype=float)
            except Exception as e:
                print(f"⚠️ ROI grdtrack 失败: {e}")
                arr = np.empty((0, 3), dtype=float)

            if arr.ndim == 2 and arr.shape[1] >= 3 and arr.shape[0] > 0:
                xs = arr[:, 0]
                ys = arr[:, 1]
                depths = np.abs(grid_z_to_depth_m(arr[:, 2]))
            else:
                xs = dense_lons
                ys = dense_lats
                depths = None

            fig.plot(x=xs, y=ys, pen="2p,red")

            sx, sy = track[0]
            fig.plot(x=[sx], y=[sy], style="a0.5c", fill="red", pen="1p,red")

            if depths is not None and len(depths) > 0:
                start_depth = float(depths[0])

        # =========================
        # frame
        # =========================
        fig.basemap(
            region=region,
            projection=projection,
            frame=[f"xaf{x_tick}", f"yaf{y_tick}", "WSen"],
        )

        pts = np.loadtxt("points.txt")
        x0, y0 = pts[0]

        # =========================
        # 真实 半径为xxxm 圆
        # =========================
        draw_geo_circle(fig, x0, y0, 5000)

        # =========================
        # 📏 正确比例尺（修复 + 放底部）
        # =========================
        xmid = (xmin + xmax) / 2
        ymid = (ymin + ymax) / 2
        yscale = ymin - (ymax - ymin) * 0.08

        fig.basemap(
            region=region,
            projection=projection,
            map_scale=f"x0.5i/-0.5i+c{xmid}/{ymid}+w2k+f+l"
        )

        # =========================
        # UL / LR
        # =========================
        fig.text(
            x=xmin,
            y=ymax,
            text=f"UL: {xmin:.4f} {ymax:.4f}",
            justify="TL",
            font="10p,Helvetica,black",
            fill="white",
            pen="1p,black"
        )

        fig.text(
            x=xmax,
            y=ymin,
            text=f"LR: {xmax:.4f} {ymin:.4f}",
            justify="BR",
            font="10p,Helvetica,black",
            fill="white",
            pen="1p,black"
        )

        # =========================
        # 左下信息
        # =========================
        if track:
            sx, sy = track[0]
            diving_deg = f"{sx:.4f}, {sy:.4f}"
            diving_dm = f"{to_dm(sx)}, {to_dm(sy)}"
        else:
            diving_deg = "N/A"
            diving_dm = "N/A"

        if dive_id:
            diving_line = f"{dive_id} Diving: {diving_deg}"
        else:
            diving_line = f"Diving: {diving_deg}"

        if depths is not None and len(depths) > 0:
            min_dep = float(np.min(depths))
            max_dep = float(np.max(depths))
        else:
            min_dep = max_dep = start_depth if np.isfinite(start_depth) else 0

        fig.text(
            x=xmin,
            y=ymin,
            text=f"{diving_line} | {diving_dm}",
            justify="BL",
            font="10p,Helvetica,black",
            fill="pink"
        )

        depth_start_text = -abs(start_depth) if np.isfinite(start_depth) else 0.0
        depth_min_text = -abs(min_dep)
        depth_max_text = -abs(max_dep)

        fig.text(
            x=xmax,
            y=ymax,
            text=f"Depth:  {depth_start_text:.1f} /{depth_min_text:.1f} / {depth_max_text:.1f}",
            justify="TR",
            font="10p,Helvetica,black",
            fill="lightblue"
        )

        addpoint_points = [
            point
            for point in load_addpoint_txt()
            if region[0] <= float(point["lon"]) <= region[1]
            and region[2] <= float(point["lat"]) <= region[3]
        ]
        for point in addpoint_points:
            fig.plot(
                x=[float(point["lon"])],
                y=[float(point["lat"])],
                style=user_point_plot_style(str(point.get("shape", "circle")).lower()),
                fill=str(point.get("color", "#ff0000")),
                pen="0.8p,black",
            )
        

        # =========================
        # 🟦 手动线绘制
        # =========================
        raw_lines = self.lines_input.toPlainText().strip().split("\n")

        current_line = []
        current_name = None
        current_color = "red"

        def draw_line(fig, line_pts, name, color):
            if len(line_pts) < 2:
                return

            xs = [p[0] for p in line_pts]
            ys = [p[1] for p in line_pts]

            fig.plot(
                x=xs,
                y=ys,
                pen=f"1.2p,{color}"
            )

            x0, y0 = line_pts[0]
            fig.text(
                x=x0,
                y=y0,
                text=name,
                offset="0.2c/0.2c",
                justify="BL",
                font="10p,Helvetica,black",
                fill="white@50"
            )

        for line in raw_lines:

            line = line.strip()

            if line == "":
                draw_line(fig, current_line, current_name, current_color)
                current_line = []
                current_name = None
                current_color = "red"
                continue

            try:
                lon, lat, name, color = line.split()

                lon = float(lon)
                lat = float(lat)

                if current_name is None:
                    current_name = name
                    current_color = color

                current_line.append((lon, lat))

            except:
                continue

        draw_line(fig, current_line, current_name, current_color)
        
        fig.savefig(ROI_MAP_PNG, dpi=300)
        self._paint_addpoints_on_roi_image(ROI_MAP_PNG, region)
        self._show_roi_preview()
        self.save_state()

        print(f"✔ {ROI_MAP_PNG} 已生成")
