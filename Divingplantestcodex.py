find . -name "Divingplantestcodex.py"# conda activate gmt


import math
import os
import sys
import json
import html
import numpy as np
import pygmt
import subprocess

from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QMimeData
from PySide6.QtGui import QColor, QPen, QPainterPath, QPixmap, QWheelEvent, QBrush, QPolygonF, QPainter, QImage, QFont, QFontMetrics, QLinearGradient, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QWidget,
    QFormLayout,
    QVBoxLayout,
    QPushButton,
    QPlainTextEdit,
    QFileDialog,
    QLineEdit,
    QLabel,
    QMessageBox,
    QInputDialog,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QScrollArea,
    QSplitter,
    QToolTip,
)

from roi_window import ROIApp   # ⭐新增

CONFIG_FILE = "gmt_last_config.json"
ROUTE_MAP_PNG = "route_map.png"
DIGITIZE_BASE_PNG = "route_basemap.png"
PREVIEW_COLORBAR_PNG = "route_basemap_colorbar.png"
DEPTH_PROFILE_PNG = "depth_profile.png"
ADDPOINT_TXT = "addpoint.txt"
LINES_TXT = "lines.txt"
POINTS_SPEED_MPS = 0.5
USER_POINT_SHAPES = ["circle", "square", "triangle", "star"]
USER_POINT_LABEL_POSITIONS = ["右上", "左上", "右下", "左下", "上中", "下中", "左中", "右中"]
DEFAULT_LINE_COLOR = "#00a6ff"
USER_LINE_STYLES = ["实线", "虚线", "点线", "点划线"]
HAXBY_STOPS = [
    (0.00, "#1f3b7a"),
    (0.12, "#225ea8"),
    (0.24, "#1d91c0"),
    (0.36, "#41b6c4"),
    (0.48, "#7fcdbb"),
    (0.60, "#c7e9b4"),
    (0.72, "#ffffbf"),
    (0.84, "#fdae61"),
    (1.00, "#d73027"),
]


class ExcelLikeTableWidget(QTableWidget):
    copy_requested = Signal()
    paste_requested = Signal()
    select_all_requested = Signal()

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.state() != QAbstractItemView.State.EditingState:
                if event.key() == Qt.Key.Key_A:
                    self.select_all_requested.emit()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_C:
                    self.copy_requested.emit()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_V:
                    self.paste_requested.emit()
                    event.accept()
                    return
        super().keyPressEvent(event)


class BatchImportDialog(QDialog):
    def __init__(self, title, placeholder_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        info_label = QLabel("每行必须输入 3 列：名称 经度 纬度。支持空格或 Tab 分隔。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(placeholder_text)
        layout.addWidget(self.editor, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 360)

    def text(self):
        return self.editor.toPlainText()


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


def user_point_plot_style(shape):
    return {
        "circle": "c0.22c",
        "square": "s0.22c",
        "triangle": "t0.26c",
        "star": "a0.30c",
    }.get(shape, "c0.22c")


def normalize_user_lines(raw_lines):
    normalized = []
    if not isinstance(raw_lines, list):
        return normalized
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        raw_points = item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            continue
        points = []
        for pt in raw_points:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                points = []
                break
            try:
                lon = float(pt[0])
                lat = float(pt[1])
            except (TypeError, ValueError):
                points = []
                break
            points.append([lon, lat])
        if len(points) < 2:
            continue
        color = str(item.get("color", DEFAULT_LINE_COLOR)).strip() or DEFAULT_LINE_COLOR
        name = str(item.get("name", "")).strip()
        line_style = str(item.get("line_style", "实线")).strip() or "实线"
        if line_style not in USER_LINE_STYLES:
            line_style = "实线"
        try:
            font_size = int(item.get("font_size", 8))
        except (TypeError, ValueError):
            font_size = 8
        font_size = max(8, min(24, font_size))
        normalized.append(
            {
                "name": name,
                "color": color,
                "line_style": line_style,
                "font_size": font_size,
                "points": points,
            }
        )
    return normalized


def _format_line_point_line(line, lon, lat):
    return (
        f"{str(line.get('name', '')).strip()} "
        f"{float(lon):.6f} "
        f"{float(lat):.6f} "
        f"{str(line.get('color', DEFAULT_LINE_COLOR)).strip() or DEFAULT_LINE_COLOR} "
        f"{str(line.get('line_style', '实线')).strip() or '实线'} "
        f"{int(line.get('font_size', 8))}"
    )


def user_line_pen_style(line_style):
    return {
        "实线": Qt.PenStyle.SolidLine,
        "虚线": Qt.PenStyle.DashLine,
        "点线": Qt.PenStyle.DotLine,
        "点划线": Qt.PenStyle.DashDotLine,
    }.get(line_style, Qt.PenStyle.SolidLine)


def write_lines_txt(lines):
    with open(LINES_TXT, "w", encoding="utf-8") as f:
        for line in normalize_user_lines(lines):
            for lon, lat in line.get("points", []):
                f.write(_format_line_point_line(line, lon, lat) + "\n")


def load_lines_txt():
    grouped = []
    by_name = {}
    if not os.path.isfile(LINES_TXT):
        return []
    with open(LINES_TXT, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            if len(parts) < 3:
                continue
            name = parts[0]
            try:
                lon = float(parts[1])
                lat = float(parts[2])
            except ValueError:
                continue
            color = parts[3] if len(parts) >= 4 else DEFAULT_LINE_COLOR
            line_style = parts[4] if len(parts) >= 5 else "实线"
            font_size = parts[5] if len(parts) >= 6 else 8
            if name not in by_name:
                line = {
                    "name": name,
                    "color": color,
                    "line_style": line_style,
                    "font_size": font_size,
                    "points": [],
                }
                by_name[name] = line
                grouped.append(line)
            by_name[name]["points"].append([lon, lat])
    return normalize_user_lines(grouped)


def generate_axis_ticks(vmin, vmax, step):
    if step <= 0 or vmax <= vmin:
        return []
    start = math.ceil(vmin / step) * step
    ticks = []
    value = start
    limit = vmax + step * 1e-9
    while value <= limit:
        ticks.append(round(value, 10))
        value += step
    return ticks


def format_lon_label(value):
    hemi = "E" if value >= 0 else "W"
    return f"{abs(value):.2f}°{hemi}"


def format_lat_label(value):
    hemi = "N" if value >= 0 else "S"
    return f"{abs(value):.2f}°{hemi}"


def nice_colorbar_step(span):
    if not np.isfinite(span) or span <= 0:
        return 1.0
    raw = span / 5.0
    magnitude = 10 ** np.floor(np.log10(raw))
    residual = raw / magnitude
    if residual <= 1:
        return 1 * magnitude
    if residual <= 2:
        return 2 * magnitude
    if residual <= 5:
        return 5 * magnitude
    return 10 * magnitude


def render_haxby_colorbar(
    path,
    width=150,
    height=420,
    depth_min=None,
    depth_max=None,
    scale=3,
    horizontal=False,
    transparent_background=False,
    font_pt=12,
):
    scale = max(1, int(scale))
    width = int(width) * scale
    height = int(height) * scale

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255, 0 if transparent_background else 230))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    if horizontal:
        bar_x = 36 * scale
        bar_y = 42 * scale
        bar_w = width - 72 * scale
        bar_h = 22 * scale
        gradient = QLinearGradient(bar_x, bar_y, bar_x + bar_w, bar_y)
    else:
        bar_x = 18 * scale
        bar_y = 18 * scale
        bar_w = 30 * scale
        bar_h = height - 36 * scale
        gradient = QLinearGradient(bar_x, bar_y, bar_x, bar_y + bar_h)
    for pos, color in HAXBY_STOPS:
        gradient.setColorAt(1.0 - pos, QColor(color))
    painter.fillRect(bar_x, bar_y, bar_w, bar_h, QBrush(gradient))
    painter.setPen(QPen(QColor("black"), max(1, scale // 2)))
    painter.drawRect(bar_x, bar_y, bar_w, bar_h)

    font = QFont("Helvetica", font_pt * scale)
    painter.setFont(font)
    fm = painter.fontMetrics()
    if depth_min is None or depth_max is None or not np.isfinite(depth_min) or not np.isfinite(depth_max):
        if horizontal:
            top_y = bar_y - 8 * scale
            painter.drawText(bar_x, top_y, "Shallow")
            painter.drawText(bar_x + bar_w - fm.horizontalAdvance("Deep"), top_y, "Deep")
        else:
            text_x = bar_x + bar_w + 10 * scale
            painter.drawText(text_x, bar_y + fm.ascent(), "Shallow")
            painter.drawText(text_x, bar_y + bar_h, "0")
            painter.drawText(text_x, bar_y + bar_h // 2 + fm.ascent() // 2, "-")
            painter.drawText(text_x, bar_y + bar_h - 6 * scale, "Deep")
    else:
        d0 = min(float(depth_min), float(depth_max))
        d1 = max(float(depth_min), float(depth_max))
        step = nice_colorbar_step(d1 - d0)
        ticks = []
        value = math.ceil(d0 / step) * step
        limit = d1 + step * 1e-9
        while value <= limit:
            ticks.append(round(value, 10))
            value += step
        if not ticks or abs(ticks[0] - d0) > 1e-9:
            ticks.insert(0, d0)
        if abs(ticks[-1] - d1) > 1e-9:
            ticks.append(d1)
        painter.setPen(QPen(QColor("black"), 1))
        for depth in ticks:
            t = 0.0 if abs(d1 - d0) < 1e-12 else (depth - d0) / (d1 - d0)
            if horizontal:
                x = bar_x + t * bar_w
                painter.drawLine(int(x), bar_y - 4 * scale, int(x), bar_y)
                label = f"{-depth:.0f}"
                painter.drawText(
                    int(x - fm.horizontalAdvance(label) / 2),
                    bar_y - 8 * scale,
                    label,
                )
            else:
                text_x = bar_x + bar_w + 10 * scale
                y = bar_y + t * bar_h
                painter.drawLine(bar_x + bar_w, int(y), bar_x + bar_w + 5 * scale, int(y))
                painter.drawText(text_x, int(y + fm.ascent() / 2), f"{-depth:.0f}")
    if not transparent_background:
        painter.setPen(QPen(QColor(80, 80, 80), max(1, scale // 2)))
        painter.drawRect(0, 0, width - 1, height - 1)

    painter.end()
    return image.save(path)


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


def load_addpoint_txt():
    points = []
    try:
        with open(ADDPOINT_TXT, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                except ValueError:
                    continue
                name = parts[2]
                color = parts[3]
                shape = parts[4]
                label_pos = parts[5] if len(parts) >= 6 else "右上"
                font_size = parts[6] if len(parts) >= 7 else 8
                points.append(
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
    except FileNotFoundError:
        return []
    return normalize_user_points(points)


def write_addpoint_txt(points):
    with open(ADDPOINT_TXT, "w") as f:
        for point in normalize_user_points(points):
            f.write(_format_addpoint_line(point) + "\n")


def append_addpoint_txt(point_dict):
    point = normalize_user_points([point_dict])
    if not point:
        return
    with open(ADDPOINT_TXT, "a") as f:
        f.write(_format_addpoint_line(point[0]) + "\n")


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)


def write_points(points):
    with open("points.txt", "w") as f:
        for x, y in points:
            f.write(f"{x} {y}\n")


# ⭐新增：写ROV box
def write_box(box):
    with open("rov_box_points.txt", "w") as f:
        for x, y in box:
            f.write(f"{x} {y}\n")


def compute_center(points):
    arr = np.array(points)
    return np.mean(arr[:, 0]), np.mean(arr[:, 1])


def haversine_distance_m(lon1, lat1, lon2, lat2):
    """相邻航点大圆距离 (m)，与 GMT mapproject -G 沿轨累加一致思路。"""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    dp = math.radians(lat2 - lat1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return R * c


def bearing_degrees(lon1, lat1, lon2, lat2):
    """由前一点指向当前点的艏向角，0-360 度。"""
    lon1_r, lat1_r = math.radians(lon1), math.radians(lat1)
    lon2_r, lat2_r = math.radians(lon2), math.radians(lat2)
    dlon = lon2_r - lon1_r
    y = math.sin(dlon) * math.cos(lat2_r)
    x = (
        math.cos(lat1_r) * math.sin(lat2_r)
        - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    )
    ang = math.degrees(math.atan2(y, x))
    return (ang + 360.0) % 360.0



def densify_track_with_project(points, spacing_m=100):

    spacing_km = spacing_m / 1000.0

    dense_pts = []

    for i in range(len(points) - 1):
        lon1, lat1 = points[i]
        lon2, lat2 = points[i + 1]

        seg = pygmt.project(
            center=[lon1, lat1],
            endpoint=[lon2, lat2],
            generate=spacing_km,
            unit=True
        )

        for _, row in seg.iterrows():
            dense_pts.append((row["r"], row["s"]))

    # 去重
    dense_unique = []
    for p in dense_pts:
        if not dense_unique or p != dense_unique[-1]:
            dense_unique.append(p)

    lons = np.array([p[0] for p in dense_unique])
    lats = np.array([p[1] for p in dense_unique])

    print(f"✔ densify 点数: {len(lons)}")

    return lons, lats

# def densify_track_with_project(points, spacing_m=2):
#     """
#     使用 GMT project 沿航线加密点（每 spacing_m 一个点）
#     返回：dense_lons, dense_lats
#     """
# 
#     # 写原始航点
#     with open("tmp_track.txt", "w") as f:
#         for lon, lat in points:
#             f.write(f"{lon} {lat}\n")
# 
#     dense_pts = []
# 
#     for i in range(len(points) - 1):
#         lon1, lat1 = points[i]
#         lon2, lat2 = points[i + 1]
# 
#         cmd = [
#             "gmt", "project",
#             f"-C{lon1}/{lat1}",
#             f"-E{lon2}/{lat2}",
#             f"-G{spacing_m}k",
#             "-Q"   # 输出经纬度
#         ]
#         print("CMD:", " ".join(cmd))   # ⭐调试用
#         result = subprocess.run(cmd, capture_output=True, text=True)
# 
#         if result.returncode != 0:
#             print("❌ project 执行失败:", result.stderr)
#             continue
# 
#         for line in result.stdout.strip().split("\n"):
#             parts = line.split()
#             if len(parts) >= 2:
#                 dense_pts.append((float(parts[0]), float(parts[1])))
# 
#     # 去重（避免节点重复）
#     dense_pts_unique = []
#     for p in dense_pts:
#         if not dense_pts_unique or p != dense_pts_unique[-1]:
#             dense_pts_unique.append(p)
# 
#     lons = np.array([p[0] for p in dense_pts_unique])
#     lats = np.array([p[1] for p in dense_pts_unique])
# 
#     return lons, lats

def cumulative_distance_along_track_km(lons, lats):
    """自起点沿航线累积距离 (km)。"""
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    if lons.size < 1:
        return np.array([0.0])
    d_m = [0.0]
    for i in range(1, lons.size):
        d_m.append(
            d_m[-1]
            + haversine_distance_m(lons[i - 1], lats[i - 1], lons[i], lats[i])
        )
    return np.array(d_m) / 1000.0


def build_points_metrics(points, depths=None, speed_mps=POINTS_SPEED_MPS, speeds_mps=None):
    """为航点生成累计/分段距离与用时。"""
    if not points:
        return []

    metrics = []
    cumulative_km = 0.0
    cumulative_hours = 0.0
    speed_mps = float(speed_mps)
    depths = list(depths) if depths is not None else [np.nan] * len(points)
    speeds_mps = list(speeds_mps) if speeds_mps is not None else [speed_mps] * len(points)
    if len(speeds_mps) < len(points):
        speeds_mps.extend([speed_mps] * (len(points) - len(speeds_mps)))

    for i, (lon, lat) in enumerate(points):
        row_speed_mps = float(speeds_mps[i]) if np.isfinite(speeds_mps[i]) else speed_mps
        if i == 0:
            segment_km = 0.0
            segment_hours = 0.0
            avg_slope_deg = np.nan
            heading_deg = np.nan
        else:
            prev_lon, prev_lat = points[i - 1]
            segment_m = haversine_distance_m(prev_lon, prev_lat, lon, lat)
            segment_km = segment_m / 1000.0
            segment_hours = segment_m / row_speed_mps / 3600.0 if row_speed_mps > 0 else np.nan
            cumulative_km += segment_km
            cumulative_hours += segment_hours
            heading_deg = bearing_degrees(prev_lon, prev_lat, lon, lat)
            prev_depth = depths[i - 1] if i - 1 < len(depths) else np.nan
            curr_depth = depths[i] if i < len(depths) else np.nan
            if segment_m > 0 and np.isfinite(prev_depth) and np.isfinite(curr_depth):
                avg_slope_deg = math.degrees(math.atan2(curr_depth - prev_depth, segment_m))
            else:
                avg_slope_deg = np.nan

        metrics.append(
            {
                "seg_no": i,
                "heading_deg": heading_deg,
                "cum_dist_km": cumulative_km,
                "cum_time_h": cumulative_hours,
                "seg_dist_km": segment_km,
                "seg_time_h": segment_hours,
                "avg_slope_deg": avg_slope_deg,
                "speed_mps": row_speed_mps,
            }
        )

    return metrics


def grid_z_to_depth_m(z):
    """网格 Z 转为向下为正的深度 (m)：高程型海下为负时取反。"""
    z = np.asarray(z, dtype=float)
    if z.size == 0:
        return z
    med = np.nanmedian(z[np.isfinite(z)])
    if np.isfinite(med) and med <= 0:
        return np.where(np.isnan(z), np.nan, -z)
    return z


def nice_tick(span, n=4):
    raw = span / n
    if raw == 0:
        return 1

    magnitude = 10 ** np.floor(np.log10(raw))
    residual = raw / magnitude

    if residual <= 1:
        return 1 * magnitude
    elif residual <= 2:
        return 2 * magnitude
    elif residual <= 5:
        return 5 * magnitude
    return 10 * magnitude


def _merc_y_rad(lat_rad):
    """球面墨卡托 Y（弧度），与 GMT -JM 一致。"""
    return math.log(math.tan(math.pi / 4 + lat_rad / 2))


def _lat_from_merc_y_rad(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def scene_xy_to_lonlat(sx, sy, w, h, lon_min, lon_max, lat_min, lat_max):
    """底图像素 (左上为原点) → 经纬度；水平线性经度，垂直按墨卡托 Y 插值（与 -JM 一致）。"""
    if w <= 1 or h <= 1:
        return lon_min, lat_min
    sx = max(0.0, min(float(w - 1), float(sx)))
    sy = max(0.0, min(float(h - 1), float(sy)))
    lon = lon_min + (sx / (w - 1)) * (lon_max - lon_min)
    m_n = _merc_y_rad(math.radians(lat_max))
    m_s = _merc_y_rad(math.radians(lat_min))
    t = sy / (h - 1)
    m = m_n + t * (m_s - m_n)
    lat = _lat_from_merc_y_rad(m)
    return lon, lat


def five_point_star_path(cx, cy, outer_r=11.0, inner_r=4.5):
    """朝上五角星，场景坐标（y 向下）。"""
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


def lonlat_to_scene_xy(lon, lat, w, h, lon_min, lon_max, lat_min, lat_max):
    """经纬度 → 底图像素坐标（用于叠加航线）。"""
    if w <= 1 or h <= 1:
        return 0.0, 0.0
    lon = max(min(lon, lon_max), lon_min)
    lat = max(min(lat, lat_max), lat_min)
    sx = (lon - lon_min) / (lon_max - lon_min) * (w - 1)
    m = _merc_y_rad(math.radians(lat))
    m_n = _merc_y_rad(math.radians(lat_max))
    m_s = _merc_y_rad(math.radians(lat_min))
    denom = m_s - m_n
    if abs(denom) < 1e-15:
        sy = (h - 1) / 2
    else:
        sy = (m - m_n) / denom * (h - 1)
    sy = max(0.0, min(float(h - 1), sy))
    return sx, sy


class ZoomView(QGraphicsView):
    """剖面图预览：滚轮缩放 + 鼠标拖动（GIS风格）"""

    _ZOOM_STEP = 1.1
    _SCALE_MIN = 0.03
    _SCALE_MAX = 80.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item = None

        self.setMinimumWidth(360)

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.setBackgroundBrush(QColor(240, 240, 240))

    def set_image(self, pixmap: QPixmap):
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)

    def wheelEvent(self, event):
        factor = self._ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self._ZOOM_STEP

        # 限制缩放
        current_scale = self.transform().m11()
        new_scale = current_scale * factor

        if new_scale < self._SCALE_MIN or new_scale > self._SCALE_MAX:
            return

        self.scale(factor, factor)



class DepthProfileDialog(QDialog):
    """支持鼠标缩放 + 拖动的剖面图"""

    def __init__(self, png_path: str, parent=None):
        super().__init__(parent)

        self.setWindowTitle("深度剖面（可缩放/拖动）")

        layout = QVBoxLayout(self)

        self.view = ZoomView()
        scene = QGraphicsScene()

        pix = QPixmap(png_path)

        if pix.isNull():
            layout.addWidget(QLabel(f"无法加载：{png_path}"))
        else:
            scene.addPixmap(pix)
            self.view.setScene(scene)
            layout.addWidget(self.view)

        info = QLabel(f"已导出：{png_path}")
        layout.addWidget(info)

        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

        if not pix.isNull():
            self.resize(min(1200, pix.width() + 120),
                        min(800, pix.height() + 160))


class PointEditorDialog(QDialog):
    def __init__(self, parent=None, point=None):
        super().__init__(parent)
        self.setWindowTitle("编辑点标注")
        self._color = "#ff0000"

        point = point or {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lon_edit = QLineEdit(str(point.get("lon", "")))
        self.lat_edit = QLineEdit(str(point.get("lat", "")))
        self.name_edit = QLineEdit(str(point.get("name", "")))

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(USER_POINT_SHAPES)
        shape = str(point.get("shape", "circle")).strip().lower()
        idx = self.shape_combo.findText(shape)
        if idx >= 0:
            self.shape_combo.setCurrentIndex(idx)

        self.label_pos_combo = QComboBox()
        self.label_pos_combo.addItems(USER_POINT_LABEL_POSITIONS)
        label_pos = str(point.get("label_pos", "右上")).strip()
        idx = self.label_pos_combo.findText(label_pos)
        if idx >= 0:
            self.label_pos_combo.setCurrentIndex(idx)

        self.font_size_edit = QLineEdit(str(point.get("font_size", 8)))

        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self.choose_color)

        form.addRow("经度 lon", self.lon_edit)
        form.addRow("纬度 lat", self.lat_edit)
        form.addRow("点名称 name", self.name_edit)
        form.addRow("点颜色 color", self.color_btn)
        form.addRow("点形状 shape", self.shape_combo)
        form.addRow("标注位置", self.label_pos_combo)
        form.addRow("字体大小", self.font_size_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.set_color(str(point.get("color", "#ff0000")).strip() or "#ff0000")

    def set_color(self, color_name):
        color = QColor(color_name)
        if not color.isValid():
            color = QColor("#ff0000")
        self._color = color.name()
        self.color_btn.setText(self._color)
        self.color_btn.setStyleSheet(
            f"background-color: {self._color}; color: black; min-height: 28px;"
        )

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, "选择点颜色")
        if color.isValid():
            self.set_color(color.name())

    def accept(self):
        try:
            lon = float(self.lon_edit.text().strip())
            lat = float(self.lat_edit.text().strip())
            font_size = int(self.font_size_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "输入错误", "经纬度和字体大小必须是有效数字。")
            return
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "输入错误", "点名称不能为空。")
            return
        font_size = max(8, min(24, font_size))

        self.point_data = {
            "lon": lon,
            "lat": lat,
            "name": self.name_edit.text().strip(),
            "color": self._color,
            "shape": self.shape_combo.currentText(),
            "label_pos": self.label_pos_combo.currentText(),
            "font_size": font_size,
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

        btn_manual = QPushButton("手动添加点")
        btn_manual.clicked.connect(lambda: self._select(self.MODE_MANUAL))
        layout.addWidget(btn_manual)

        btn_pick = QPushButton("鼠标点击添加点")
        btn_pick.clicked.connect(lambda: self._select(self.MODE_PICK))
        layout.addWidget(btn_pick)

        btn_edit = QPushButton("编辑点")
        btn_edit.clicked.connect(lambda: self._select(self.MODE_EDIT))
        layout.addWidget(btn_edit)

        btn_delete = QPushButton("删除点")
        btn_delete.clicked.connect(lambda: self._select(self.MODE_DELETE))
        layout.addWidget(btn_delete)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _select(self, mode):
        self.selected_mode = mode
        self.accept()


class LineEditorDialog(QDialog):
    def __init__(self, parent=None, line=None):
        super().__init__(parent)
        self.setWindowTitle("编辑线标注")
        self._color = DEFAULT_LINE_COLOR
        self._line_style = "实线"
        line = line or {}
        pts = line.get("points") or [["", ""], ["", ""]]
        if len(pts) < 2:
            pts = pts + [["", ""]] * (2 - len(pts))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(str(line.get("name", "")))
        self.points_edit = QPlainTextEdit()
        self.points_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.points_edit.setPlaceholderText("每行一个点：lon lat")
        self.points_edit.setMinimumHeight(180)
        point_lines = []
        for pt in pts:
            if len(pt) < 2:
                continue
            try:
                point_lines.append(f"{float(pt[0]):.6f} {float(pt[1]):.6f}")
            except (TypeError, ValueError):
                continue
        self.points_edit.setPlainText("\n".join(point_lines))
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self.choose_color)
        self.style_combo = QComboBox()
        self.style_combo.addItems(USER_LINE_STYLES)
        self.font_size_edit = QLineEdit(str(line.get("font_size", 8)))

        form.addRow("线名称", self.name_edit)
        form.addRow("经纬度点列", self.points_edit)
        form.addRow("线颜色", self.color_btn)
        form.addRow("线型", self.style_combo)
        form.addRow("字体大小", self.font_size_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self.set_color(str(line.get("color", DEFAULT_LINE_COLOR)).strip() or DEFAULT_LINE_COLOR)
        line_style = str(line.get("line_style", "实线")).strip() or "实线"
        if line_style not in USER_LINE_STYLES:
            line_style = "实线"
        self._line_style = line_style
        self.style_combo.setCurrentText(line_style)

    def set_color(self, color_name):
        color = QColor(color_name)
        if not color.isValid():
            color = QColor(DEFAULT_LINE_COLOR)
        self._color = color.name()
        self.color_btn.setText(self._color)
        self.color_btn.setStyleSheet(
            f"background-color: {self._color}; color: black; min-height: 28px;"
        )

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, "选择线颜色")
        if color.isValid():
            self.set_color(color.name())

    def accept(self):
        points = []
        raw_lines = [line.strip() for line in self.points_edit.toPlainText().splitlines() if line.strip()]
        for raw in raw_lines:
            parts = raw.replace(",", " ").split()
            if len(parts) < 2:
                QMessageBox.warning(self, "输入错误", "每行必须包含经度和纬度两个数字。")
                return
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                QMessageBox.warning(self, "输入错误", "线的经纬度必须是有效数字。")
                return
            points.append([lon, lat])
        if len(points) < 2:
            QMessageBox.warning(self, "输入错误", "至少需要 2 个点才能组成一条线。")
            return
        try:
            font_size = int(self.font_size_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "输入错误", "字体大小必须是整数。")
            return
        font_size = max(8, min(24, font_size))
        name = self.name_edit.text().strip()
        self.line_data = {
            "name": name,
            "color": self._color,
            "line_style": self.style_combo.currentText(),
            "font_size": font_size,
            "points": points,
        }
        super().accept()


class LineModeDialog(QDialog):
    MODE_MANUAL = "manual"
    MODE_PICK = "pick"
    MODE_DELETE = "delete"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("线功能")
        self.selected_mode = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择线标注模式："))

        btn_manual = QPushButton("手动添加线")
        btn_manual.clicked.connect(lambda: self._select(self.MODE_MANUAL))
        layout.addWidget(btn_manual)

        btn_pick = QPushButton("鼠标点击添加线")
        btn_pick.clicked.connect(lambda: self._select(self.MODE_PICK))
        layout.addWidget(btn_pick)

        btn_delete = QPushButton("删除线")
        btn_delete.clicked.connect(lambda: self._select(self.MODE_DELETE))
        layout.addWidget(btn_delete)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _select(self, mode):
        self.selected_mode = mode
        self.accept()


class PointInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("规划点详细信息")
        self.on_user_points_table_edited = None
        self.on_user_lines_table_edited = None
        self.on_plan_table_edited = None
        layout = QVBoxLayout(self)
        self.info_label = QLabel("暂无规划点。")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info_label)

        plan_header = QHBoxLayout()
        plan_header.addWidget(QLabel("规划路线点信息"))
        self.copy_plan_button = QPushButton("复制表格信息")
        self.copy_plan_button.clicked.connect(lambda: self.copy_table_to_clipboard(self.table))
        plan_header.addStretch(1)
        plan_header.addWidget(self.copy_plan_button)
        layout.addLayout(plan_header)

        self.table = ExcelLikeTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(
            ["段号", "经度", "纬度", "艏向角", "深度", "累计距离(km)", "累计时间(h)", "段距离(km)", "段时间(h)", "平均坡度(deg)", "航速(m/s)"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._configure_table_shortcuts(self.table)
        layout.addWidget(self.table, stretch=1)
        tables_row = QHBoxLayout()
        points_wrap = QVBoxLayout()
        points_header = QHBoxLayout()
        points_header.addWidget(QLabel("点功能添加点信息"))
        self.import_points_button = QPushButton("批量导入点")
        self.import_points_button.clicked.connect(self.import_user_points)
        points_header.addWidget(self.import_points_button)
        self.copy_points_button = QPushButton("复制表格信息")
        self.copy_points_button.clicked.connect(lambda: self.copy_table_to_clipboard(self.user_points_table))
        points_header.addStretch(1)
        points_header.addWidget(self.copy_points_button)
        points_wrap.addLayout(points_header)

        self.user_points_table = ExcelLikeTableWidget()
        self.user_points_table.setColumnCount(4)
        self.user_points_table.setHorizontalHeaderLabels(
            ["名称", "经度", "纬度", "深度"]
        )
        self.user_points_table.setRowCount(100)
        self.user_points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.user_points_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.user_points_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.user_points_table.setShowGrid(True)
        self.user_points_table.setWordWrap(False)
        self.user_points_table.setAlternatingRowColors(True)
        self.user_points_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.user_points_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._configure_table_shortcuts(self.user_points_table)
        points_wrap.addWidget(self.user_points_table, stretch=1)

        lines_wrap = QVBoxLayout()
        lines_header = QHBoxLayout()
        lines_header.addWidget(QLabel("线功能添加线信息"))
        self.import_lines_button = QPushButton("批量导入线")
        self.import_lines_button.clicked.connect(self.import_user_lines)
        lines_header.addWidget(self.import_lines_button)
        self.copy_lines_button = QPushButton("复制表格信息")
        self.copy_lines_button.clicked.connect(lambda: self.copy_table_to_clipboard(self.user_lines_table))
        lines_header.addStretch(1)
        lines_header.addWidget(self.copy_lines_button)
        lines_wrap.addLayout(lines_header)
        self.user_lines_table = ExcelLikeTableWidget()
        self.user_lines_table.setColumnCount(4)
        self.user_lines_table.setHorizontalHeaderLabels(
            ["线名", "经度", "纬度", "线长度(km)"]
        )
        self.user_lines_table.setRowCount(100)
        self.user_lines_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.user_lines_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.user_lines_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.user_lines_table.setShowGrid(True)
        self.user_lines_table.setWordWrap(False)
        self.user_lines_table.setAlternatingRowColors(True)
        self.user_lines_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.user_lines_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._configure_table_shortcuts(self.user_lines_table)
        lines_wrap.addWidget(self.user_lines_table, stretch=1)

        tables_row.addLayout(points_wrap, 1)
        tables_row.addLayout(lines_wrap, 1)
        layout.addLayout(tables_row, stretch=1)
        self.resize(1080, 580)

    def _configure_table_shortcuts(self, table):
        if isinstance(table, ExcelLikeTableWidget):
            table.copy_requested.connect(lambda t=table: self.copy_selection_to_clipboard(t))
            table.paste_requested.connect(lambda t=table: self.paste_selection_from_clipboard(t))
            table.select_all_requested.connect(lambda t=table: self.select_all_table_cells(t))
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
        copy_shortcut.activated.connect(lambda t=table: self.copy_selection_to_clipboard(t))
        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, table)
        paste_shortcut.activated.connect(lambda t=table: self.paste_selection_from_clipboard(t))
        select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, table)
        select_all_shortcut.activated.connect(lambda t=table: self.select_all_table_cells(t))
        shortcuts = getattr(self, "_table_shortcuts", [])
        shortcuts.extend([copy_shortcut, paste_shortcut, select_all_shortcut])
        self._table_shortcuts = shortcuts

    def _notify_table_edited(self, table):
        if table is self.table and callable(self.on_plan_table_edited):
            self.on_plan_table_edited()
        elif table is self.user_points_table and callable(self.on_user_points_table_edited):
            self.on_user_points_table_edited()
        elif table is self.user_lines_table and callable(self.on_user_lines_table_edited):
            self.on_user_lines_table_edited()

    def _open_batch_import_dialog(self, title, example_text):
        dialog = BatchImportDialog(title, placeholder_text=example_text, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.text()

    def _parse_batch_import_text(self, raw_text, entity_name):
        rows = []
        raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line_no, line in enumerate(raw_lines, start=1):
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"第 {line_no} 行格式不对，必须正好 3 列：名称 经度 纬度")
            name = parts[0].strip()
            if not name:
                raise ValueError(f"第 {line_no} 行名称不能为空")
            try:
                lon = float(parts[1])
                lat = float(parts[2])
            except ValueError as exc:
                raise ValueError(f"第 {line_no} 行经纬度不是有效数字") from exc
            rows.append((name, lon, lat))
        if not rows:
            raise ValueError(f"请先输入要导入的{entity_name}数据")
        return rows

    def _replace_table_rows(self, table, rows, readonly_columns=None, minimum_rows=100):
        readonly_columns = set(readonly_columns or [])
        table.blockSignals(True)
        table.clearContents()
        table.setRowCount(max(minimum_rows, len(rows)))
        for r, row_values in enumerate(rows):
            for c in range(table.columnCount()):
                value = row_values[c] if c < len(row_values) else ""
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c in readonly_columns:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)
        table.blockSignals(False)
        table.resizeColumnsToContents()
        self._notify_table_edited(table)

    def import_user_points(self):
        raw_text = self._open_batch_import_dialog(
            "批量导入点",
            "P1 120.1234 30.5678\nP2 120.2234 30.6678",
        )
        if raw_text is None:
            return
        try:
            rows = self._parse_batch_import_text(raw_text, "点")
        except ValueError as exc:
            QMessageBox.warning(self, "批量导入点", str(exc))
            return
        table_rows = [(name, f"{lon:.4f}", f"{lat:.4f}", "") for name, lon, lat in rows]
        self._replace_table_rows(self.user_points_table, table_rows, readonly_columns={3})

    def import_user_lines(self):
        raw_text = self._open_batch_import_dialog(
            "批量导入线",
            "L1 120.1234 30.5678\nL1 120.2234 30.6678\nL2 120.3234 30.7678",
        )
        if raw_text is None:
            return
        try:
            rows = self._parse_batch_import_text(raw_text, "线")
        except ValueError as exc:
            QMessageBox.warning(self, "批量导入线", str(exc))
            return
        table_rows = [(name, f"{lon:.4f}", f"{lat:.4f}", "") for name, lon, lat in rows]
        self._replace_table_rows(self.user_lines_table, table_rows, readonly_columns={3})

    def select_all_table_cells(self, table):
        table.setFocus()
        table.selectAll()

    def _selected_rect(self, table):
        indexes = table.selectedIndexes()
        if not indexes:
            return None
        rows = [index.row() for index in indexes]
        cols = [index.column() for index in indexes]
        return min(rows), max(rows), min(cols), max(cols)

    def _is_row_empty(self, table, row, left_col=0, right_col=None, selected_cells=None):
        if right_col is None:
            right_col = table.columnCount() - 1
        for c in range(left_col, right_col + 1):
            if selected_cells is not None and (row, c) not in selected_cells:
                continue
            item = table.item(row, c)
            if item and item.text().strip():
                return False
        return True

    def _set_clipboard_from_rect(self, table, top_row, bottom_row, left_col, right_col, selected_cells=None):
        rows = []
        html_rows = []
        header_items = []
        header_html = []
        for c in range(left_col, right_col + 1):
            header_item = table.horizontalHeaderItem(c)
            header_text = header_item.text() if header_item else ""
            header_items.append(header_text)
            header_html.append(f"<th>{html.escape(header_text)}</th>")
        rows.append("\t".join(header_items))
        html_rows.append("<tr>" + "".join(header_html) + "</tr>")
        for r in range(top_row, bottom_row + 1):
            if self._is_row_empty(table, r, left_col, right_col, selected_cells=selected_cells):
                continue
            cols = []
            html_cols = []
            for c in range(left_col, right_col + 1):
                text = ""
                if selected_cells is None or (r, c) in selected_cells:
                    item = table.item(r, c)
                    text = item.text() if item else ""
                cols.append(text)
                html_cols.append(f"<td>{html.escape(text)}</td>")
            rows.append("\t".join(cols))
            html_rows.append("<tr>" + "".join(html_cols) + "</tr>")
        mime = QMimeData()
        mime.setText("\n".join(rows))
        mime.setHtml("<table>" + "".join(html_rows) + "</table>")
        QApplication.clipboard().setMimeData(mime)

    def copy_selection_to_clipboard(self, table):
        rect = self._selected_rect(table)
        if rect is None:
            return
        top_row, bottom_row, left_col, right_col = rect
        selected_cells = {(index.row(), index.column()) for index in table.selectedIndexes()}
        self._set_clipboard_from_rect(
            table,
            top_row,
            bottom_row,
            left_col,
            right_col,
            selected_cells=selected_cells,
        )

    def copy_table_to_clipboard(self, table):
        if table.rowCount() <= 0 or table.columnCount() <= 0:
            return
        self._set_clipboard_from_rect(
            table,
            0,
            table.rowCount() - 1,
            0,
            table.columnCount() - 1,
            selected_cells=None,
        )

    def paste_selection_from_clipboard(self, table):
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        rows = [line.split("\t") for line in text.splitlines() if line.strip()]
        if not rows:
            return
        start_items = table.selectedIndexes()
        if not start_items:
            return
        start_row = min(index.row() for index in start_items)
        start_col = min(index.column() for index in start_items)
        header_texts = [
            table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else ""
            for c in range(table.columnCount())
        ]
        if rows and rows[0] == header_texts[start_col:start_col + len(rows[0])]:
            rows = rows[1:]
        should_batch = table in (self.table, self.user_points_table, self.user_lines_table)
        if should_batch:
            table.blockSignals(True)
        for r_offset, row_values in enumerate(rows):
            target_row = start_row + r_offset
            if target_row >= table.rowCount():
                break
            for c_offset, value in enumerate(row_values):
                target_col = start_col + c_offset
                if target_col >= table.columnCount():
                    break
                item = table.item(target_row, target_col)
                if item is not None and not (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    continue
                if item is None:
                    item = QTableWidgetItem("")
                    table.setItem(target_row, target_col, item)
                item.setText(value.strip())
        if should_batch:
            table.blockSignals(False)
            self._notify_table_edited(table)


class ColorbarDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("色棒")
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(160, 260)
        layout.addWidget(self.label)
        self._pix = QPixmap()
        self.set_image(image_path)
        self.resize(320, 560)

    def set_image(self, image_path):
        self._pix = QPixmap(image_path)
        if self._pix.isNull():
            self.label.setText(f"无法加载：{image_path}")
            self.label.setPixmap(QPixmap())
        else:
            self.label.setText("")
            self._update_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        if self._pix.isNull():
            return
        scaled = self._pix.scaled(
            self.label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.label.setPixmap(scaled)

# class DepthProfileDialog(QDialog):
#     """显示并提示已导出的深度剖面 PNG。"""
# 
#     def __init__(self, png_path: str, parent=None):
#         super().__init__(parent)
#         self.setWindowTitle("航线深度剖面（距出发点距离）")
#         layout = QVBoxLayout(self)
#         scroll = QScrollArea()
#         scroll.setWidgetResizable(True)
#         inner = QWidget()
#         inner_l = QVBoxLayout(inner)
#         lbl = QLabel()
#         pix = QPixmap(png_path)
#         if pix.isNull():
#             lbl.setText(f"无法加载：{png_path}")
#         else:
#             lbl.setPixmap(pix)
#             lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
#         inner_l.addWidget(lbl)
#         scroll.setWidget(inner)
#         layout.addWidget(scroll)
#         info = QLabel(f"已导出：{png_path}")
#         info.setWordWrap(True)
#         layout.addWidget(info)
#         btn = QPushButton("关闭")
#         btn.clicked.connect(self.accept)
#         layout.addWidget(btn)
#         if not pix.isNull():
#             self.resize(min(1120, pix.width() + 100), min(820, pix.height() + 140))
#         else:
#             self.resize(520, 240)


class RouteMapPreviewView(QGraphicsView):
    """大图预览：滚轮缩放；规划模式关时左键拖平移，开时左键加点、右键拖平移。"""

    digitize_clicked = Signal(float, float)
    user_point_clicked = Signal(float, float)
    user_point_edit_clicked = Signal(float, float)
    user_point_delete_clicked = Signal(float, float)
    user_line_clicked = Signal(float, float)
    user_line_delete_clicked = Signal(float, float)
    user_line_finish_requested = Signal()

    _ZOOM_STEP = 1.15
    _SCALE_MIN = 0.03
    _SCALE_MAX = 80.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._region = None
        self._img_w = 0
        self._img_h = 0
        self._map_rect = (0.0, 0.0, 0.0, 0.0)
        self._colorbar_pixmap = QPixmap()
        self._plan_mode = False
        self._user_point_pick_mode = False
        self._user_point_edit_mode = False
        self._user_point_delete_mode = False
        self._user_line_pick_mode = False
        self._user_line_delete_mode = False
        self._overlay_items = []
        self._temporary_line_points = []
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._pan_anchor = None
        self._hover_info_text = ""
        self._hover_depth_cache = {}
        self._hover_info_enabled = False

        self.setMinimumWidth(360)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(0, 0, 0))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._show_placeholder(
            "请先点击「生成规划底图」；生成后才可勾选「规划路线」在图上加点。\n"
            "（生成下潜计划大图后需重新生成底图才能再次规划。）\n"
            "滚轮缩放；非规划时左键拖平移；规划时右键拖平移。",
            error=False,
        )

    def _clear_overlay_only(self):
        for it in self._overlay_items:
            self._scene.removeItem(it)
        self._overlay_items.clear()

    def _show_placeholder(self, text, error):
        self._clear_overlay_only()
        self._scene.clear()
        self._pixmap_item = None
        self._region = None
        self._hover_info_text = ""
        item = self._scene.addText(text)
        item.setDefaultTextColor(QColor(255, 110, 110) if error else QColor(220, 220, 220))
        br = item.boundingRect()
        item.setPos(-br.width() / 2, -br.height() / 2)
        self.setSceneRect(-280, -120, 560, 240)
        self.resetTransform()
        self.viewport().update()

    def set_route_pixmap(self, pix: QPixmap, region=None, map_rect=None):
        if pix.isNull():
            return
        self._clear_overlay_only()
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pix)
        self._pixmap_item.setZValue(0)
        self.setSceneRect(self._pixmap_item.boundingRect())
        self._img_w = pix.width()
        self._img_h = pix.height()
        self._region = region
        if map_rect is None:
            self._map_rect = (0.0, 0.0, float(self._img_w), float(self._img_h))
        else:
            self._map_rect = tuple(map_rect)
        self._hover_info_text = ""
        self.resetTransform()
        self.viewport().update()

    def set_colorbar_pixmap(self, pix: QPixmap | None):
        self._colorbar_pixmap = pix if pix is not None else QPixmap()

    def set_temporary_line_points(self, points):
        self._temporary_line_points = list(points or [])
        self.viewport().update()

    def set_hover_info_enabled(self, enabled: bool):
        self._hover_info_enabled = bool(enabled)
        if not self._hover_info_enabled:
            self._hover_info_text = ""
        self.viewport().update()

    def _lonlat_to_scene_xy(self, lon, lat):
        mx, my, mw, mh = self._map_rect
        lon0, lon1, lat0, lat1 = self._region
        sx, sy = lonlat_to_scene_xy(lon, lat, mw, mh, lon0, lon1, lat0, lat1)
        return mx + sx, my + sy

    def set_plan_mode(self, enabled: bool):
        self._plan_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def set_user_point_pick_mode(self, enabled: bool):
        self._user_point_pick_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def set_user_point_edit_mode(self, enabled: bool):
        self._user_point_edit_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def set_user_point_delete_mode(self, enabled: bool):
        self._user_point_delete_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def set_user_line_pick_mode(self, enabled: bool):
        self._user_line_pick_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def set_user_line_delete_mode(self, enabled: bool):
        self._user_line_delete_mode = bool(enabled)
        self._press_pos = None
        self._dragging = False
        self._panning = False
        self._apply_cursor_and_drag_mode()

    def _apply_cursor_and_drag_mode(self):
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ):
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def update_route_overlay(self, points, box=None, user_points=None, user_lines=None, segment_labels=None):
        """叠加航线、顶点、起点五角星、ROV 方框与用户标注点。"""
        self._clear_overlay_only()
        if self._pixmap_item is None or self._region is None or self._img_w < 2 or self._img_h < 2:
            return
        user_points = user_points or []
        user_lines = user_lines or []
        if not points and not box and not user_points and not user_lines:
            return
        pen = QPen(QColor(255, 0, 0))
        pen.setWidthF(2.0)
        pen.setCosmetic(True)
        dot_pen = QPen(QColor(200, 0, 0))
        dot_pen.setCosmetic(True)

        if len(points) >= 2:
            path = QPainterPath()
            scene_pts = []
            first = True
            for lon, lat in points:
                sx, sy = self._lonlat_to_scene_xy(lon, lat)
                scene_pts.append((sx, sy))
                if first:
                    path.moveTo(sx, sy)
                    first = False
                else:
                    path.lineTo(sx, sy)
            path_item = QGraphicsPathItem(path)
            path_item.setPen(pen)
            path_item.setZValue(2)
            self._scene.addItem(path_item)
            self._overlay_items.append(path_item)
            self._add_segment_labels(scene_pts, segment_labels=segment_labels)

        if box and len(box) >= 2:
            bpath = QPainterPath()
            for i, (bx, by) in enumerate(box):
                sx, sy = self._lonlat_to_scene_xy(bx, by)
                if i == 0:
                    bpath.moveTo(sx, sy)
                else:
                    bpath.lineTo(sx, sy)
            bpath.closeSubpath()
            box_item = QGraphicsPathItem(bpath)
            box_item.setPen(pen)
            box_item.setZValue(2)
            self._scene.addItem(box_item)
            self._overlay_items.append(box_item)

        if points:
            slon, slat = points[0]
            sx, sy = self._lonlat_to_scene_xy(slon, slat)
            star = QGraphicsPathItem(five_point_star_path(sx, sy))
            star.setPen(QPen(QColor(180, 0, 0)))
            star.setBrush(QColor(255, 0, 0, 220))
            star.setZValue(4)
            self._scene.addItem(star)
            self._overlay_items.append(star)

        for i, (lon, lat) in enumerate(points):
            if i == 0:
                continue
            sx, sy = self._lonlat_to_scene_xy(lon, lat)
            el = QGraphicsEllipseItem(sx - 4, sy - 4, 8, 8)
            el.setPen(dot_pen)
            el.setBrush(QColor(255, 80, 80, 200))
            el.setZValue(3)
            self._scene.addItem(el)
            self._overlay_items.append(el)

        for line in user_lines:
            pts_line = line.get("points") or []
            if len(pts_line) < 2:
                continue
            try:
                scene_pts = [
                    self._lonlat_to_scene_xy(float(pt[0]), float(pt[1]))
                    for pt in pts_line
                ]
            except (TypeError, ValueError, IndexError):
                continue
            color = QColor(str(line.get("color", DEFAULT_LINE_COLOR)))
            if not color.isValid():
                color = QColor(DEFAULT_LINE_COLOR)
            line_pen = QPen(color)
            line_pen.setWidthF(2.0)
            line_pen.setCosmetic(True)
            line_pen.setStyle(user_line_pen_style(str(line.get("line_style", "实线"))))
            path = QPainterPath()
            path.moveTo(scene_pts[0][0], scene_pts[0][1])
            for x1, y1 in scene_pts[1:]:
                path.lineTo(x1, y1)
            path_item = QGraphicsPathItem(path)
            path_item.setPen(line_pen)
            path_item.setZValue(1.5)
            self._scene.addItem(path_item)
            self._overlay_items.append(path_item)
            line_name = str(line.get("name", "")).strip()
            if line_name:
                text_item = self._scene.addSimpleText(line_name)
                font = text_item.font()
                font.setPointSize(max(8, min(24, int(line.get("font_size", 8)))))
                text_item.setFont(font)
                text_item.setBrush(QBrush(QColor("black")))
                text_item.setZValue(7)
                br = text_item.boundingRect()
                start_x, start_y = scene_pts[0]
                next_x, next_y = scene_pts[1]
                angle_deg = math.degrees(math.atan2(next_y - start_y, next_x - start_x))
                if angle_deg > 90:
                    angle_deg -= 180
                elif angle_deg < -90:
                    angle_deg += 180
                label_x = start_x + 8
                label_y = start_y - br.height() - 6
                center_x = label_x + br.width() / 2
                center_y = label_y + br.height() / 2
                bg = QGraphicsRectItem(
                    label_x - 3,
                    label_y - 2,
                    br.width() + 6,
                    br.height() + 4,
                )
                bg_pen = QPen()
                bg_pen.setStyle(Qt.PenStyle.NoPen)
                bg.setPen(bg_pen)
                bg.setBrush(QColor(255, 255, 255, 128))
                bg.setZValue(6)
                text_item.setPos(label_x, label_y)
                bg.setTransformOriginPoint(center_x, center_y)
                bg.setRotation(angle_deg)
                text_item.setTransformOriginPoint(br.width() / 2, br.height() / 2)
                text_item.setRotation(angle_deg)
                self._scene.addItem(bg)
                self._overlay_items.extend([bg, text_item])

        for point in user_points:
            try:
                lon = float(point["lon"])
                lat = float(point["lat"])
            except (KeyError, TypeError, ValueError):
                continue

            sx, sy = self._lonlat_to_scene_xy(lon, lat)
            color = QColor(str(point.get("color", "#ff0000")))
            if not color.isValid():
                color = QColor("#ff0000")
            shape = str(point.get("shape", "circle")).lower()

            item = self._build_user_point_item(shape, sx, sy, color)
            if item is not None:
                item.setZValue(5)
                self._scene.addItem(item)
                self._overlay_items.append(item)

            name = str(point.get("name", "")).strip()
            if name:
                self._add_user_point_label(
                    name,
                    sx,
                    sy,
                    str(point.get("label_pos", "右上")),
                    int(point.get("font_size", 8)),
                )

    def _build_user_point_item(self, shape, sx, sy, color):
        pen = QPen(color.darker(150))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        brush = QBrush(color)

        if shape == "square":
            item = QGraphicsRectItem(sx - 5, sy - 5, 10, 10)
            item.setPen(pen)
            item.setBrush(brush)
            return item
        if shape == "triangle":
            poly = QPolygonF(
                [
                    QPointF(sx, sy - 6),
                    QPointF(sx - 5.5, sy + 4.5),
                    QPointF(sx + 5.5, sy + 4.5),
                ]
            )
            path = QPainterPath()
            path.addPolygon(poly)
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setBrush(brush)
            return item
        if shape == "star":
            item = QGraphicsPathItem(five_point_star_path(sx, sy, outer_r=7.0, inner_r=3.0))
            item.setPen(pen)
            item.setBrush(brush)
            return item

        item = QGraphicsEllipseItem(sx - 5, sy - 5, 10, 10)
        item.setPen(pen)
        item.setBrush(brush)
        return item

    def _label_anchor_xy(self, label_pos, sx, sy, br):
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

    def _add_user_point_label(self, name, sx, sy, label_pos="右上", font_size=10):
        text_item = self._scene.addSimpleText(name)
        font = text_item.font()
        font.setPointSize(max(8, min(24, int(font_size))))
        text_item.setFont(font)
        text_item.setBrush(QBrush(QColor(0, 0, 0)))
        text_item.setZValue(7)
        br = text_item.boundingRect()
        text_x, text_y = self._label_anchor_xy(label_pos, sx, sy, br)
        bg = QGraphicsRectItem(
            text_x - 3,
            text_y - 2,
            br.width() + 6,
            br.height() + 4,
        )
        bg_pen = QPen()
        bg_pen.setStyle(Qt.PenStyle.NoPen)
        bg.setPen(bg_pen)
        bg.setBrush(QColor(255, 255, 255, 128))
        bg.setZValue(6)
        text_item.setPos(text_x, text_y)
        self._scene.addItem(bg)
        self._overlay_items.append(bg)
        self._overlay_items.append(text_item)

    def _add_segment_labels(self, scene_pts, segment_labels=None):
        if len(scene_pts) < 2:
            return
        for i in range(1, len(scene_pts)):
            x0, y0 = scene_pts[i - 1]
            x1, y1 = scene_pts[i]
            mx = (x0 + x1) / 2.0
            my = (y0 + y1) / 2.0
            angle_deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
            if angle_deg > 90:
                angle_deg -= 180
            elif angle_deg < -90:
                angle_deg += 180
            label = (
                segment_labels[i - 1]
                if segment_labels and i - 1 < len(segment_labels)
                else f"S{i}"
            )
            text_item = self._scene.addSimpleText(label)
            font = text_item.font()
            font.setPointSize(8)
            font.setBold(True)
            text_item.setFont(font)
            text_item.setBrush(QBrush(QColor("black")))
            text_item.setZValue(7)
            br = text_item.boundingRect()
            rect_x = mx - br.width() / 2 - 3
            rect_y = my - br.height() / 2 - 2
            bg = QGraphicsRectItem(
                rect_x,
                rect_y,
                br.width() + 6,
                br.height() + 4,
            )
            bg_pen = QPen()
            bg_pen.setStyle(Qt.PenStyle.NoPen)
            bg.setPen(bg_pen)
            bg.setBrush(QColor(173, 216, 230, 200))
            bg.setZValue(6)
            bg.setTransformOriginPoint(mx, my)
            bg.setRotation(angle_deg)
            text_item.setPos(mx - br.width() / 2, my - br.height() / 2)
            text_item.setTransformOriginPoint(br.width() / 2, br.height() / 2)
            text_item.setRotation(angle_deg)
            self._scene.addItem(bg)
            self._overlay_items.append(bg)
            self._overlay_items.append(text_item)

    def show_load_error(self, path: str):
        self._show_placeholder(f"无法加载预览：{path}", error=True)

    def _inside_pixmap_scene(self, scene_pt):
        if self._pixmap_item is None:
            return None
        local = self._pixmap_item.mapFromScene(scene_pt)
        x, y = local.x(), local.y()
        mx, my, mw, mh = self._map_rect
        if mx <= x < mx + mw and my <= y < my + mh:
            return x - mx, y - my
        return None

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._region is None or self._pixmap_item is None or self._plot_mode_for_scalebar() != "interactive":
            self._draw_hover_info()
            return
        self._draw_scalebar()
        self._draw_colorbar()
        self._draw_temporary_line()
        self._draw_hover_info()

    def _hover_lonlat_depth(self, scene_pt):
        if not self._hover_info_enabled:
            return None
        if self._region is None or self._pixmap_item is None:
            return None
        inside = self._inside_pixmap_scene(scene_pt)
        if inside is None:
            return None
        sx, sy = inside
        lon0, lon1, lat0, lat1 = self._region
        mx, my, mw, mh = self._map_rect
        lon, lat = scene_xy_to_lonlat(
            sx, sy, mw, mh, lon0, lon1, lat0, lat1
        )
        depth_text = "nan"
        window = self.window()
        if window is not None and hasattr(window, "file") and getattr(window, "file", None):
            cache_key = (round(float(lon), 4), round(float(lat), 4))
            if cache_key not in self._hover_depth_cache:
                depth = window.query_depth_at_point(window.file, lon, lat)
                depth = -grid_z_to_depth_m([depth])[0]
                self._hover_depth_cache[cache_key] = depth
            depth_value = self._hover_depth_cache.get(cache_key, np.nan)
            if np.isfinite(depth_value):
                depth_text = f"{depth_value:.2f} m"
        return f"经度: {lon:.5f}   纬度: {lat:.5f}   深度: {depth_text}"

    def _draw_hover_info(self):
        if not self._hover_info_text:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont("Helvetica", 10)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        margin = 14
        text_w = fm.horizontalAdvance(self._hover_info_text)
        text_h = fm.height()
        box_w = text_w + 16
        box_h = text_h + 12
        x = self.viewport().width() - box_w - margin
        y = margin
        painter.fillRect(x, y, box_w, box_h, QColor(0, 0, 0, 150))
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(x + 8, y + 8 + fm.ascent(), self._hover_info_text)
        painter.end()

    def _draw_temporary_line(self):
        if len(self._temporary_line_points) < 2 or self._region is None:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(0, 166, 255))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        scene_pts = [QPointF(*self._lonlat_to_scene_xy(lon, lat)) for lon, lat in self._temporary_line_points]
        for p0, p1 in zip(scene_pts[:-1], scene_pts[1:]):
            v0 = self.mapFromScene(p0)
            v1 = self.mapFromScene(p1)
            painter.drawLine(v0, v1)
        painter.end()

    def _plot_mode_for_scalebar(self):
        return getattr(self.window(), "_plot_mode", None)

    def _draw_scalebar(self):
        if self._region is None:
            return
        mx, my, mw, mh = self._map_rect
        top_left = self.mapFromScene(QPointF(mx, my))
        bottom_right = self.mapFromScene(QPointF(mx + mw, my + mh))
        left = min(top_left.x(), bottom_right.x())
        right = max(top_left.x(), bottom_right.x())
        top = min(top_left.y(), bottom_right.y())
        bottom = max(top_left.y(), bottom_right.y())
        visible_w = right - left
        visible_h = bottom - top
        if visible_w < 60 or visible_h < 40:
            return
        viewport_w = self.viewport().width()
        viewport_h = self.viewport().height()
        view_left = max(0, left)
        view_right = min(viewport_w, right)
        view_bottom = min(viewport_h, bottom)
        margin = 18
        target_px = min(160, max(90, (view_right - view_left) * 0.22))
        left_x = view_left + margin
        base_y = view_bottom - margin
        right_x = min(view_right - margin, left_x + target_px)
        if right_x - left_x < 20:
            return

        scene_p0 = self.mapToScene(int(left_x), int(base_y))
        scene_p1 = self.mapToScene(int(right_x), int(base_y))
        inside0 = self._inside_pixmap_scene(scene_p0)
        inside1 = self._inside_pixmap_scene(scene_p1)
        if inside0 is None or inside1 is None:
            return

        lon_min, lon_max, lat_min, lat_max = self._region
        map_w = self._map_rect[2]
        lat_ref = (lat_min + lat_max) / 2.0
        lon_a = lon_min + (inside0[0] / max(1.0, map_w - 1)) * (lon_max - lon_min)
        lon_b = lon_min + (inside1[0] / max(1.0, map_w - 1)) * (lon_max - lon_min)

        painter = QPainter(self.viewport())
        self._paint_scalebar(
            painter,
            left_x,
            base_y,
            haversine_distance_m(lon_a, lat_ref, lon_b, lat_ref),
            right_x - left_x,
        )

    def _draw_colorbar(self):
        if self._colorbar_pixmap.isNull():
            return
        mx, my, mw, mh = self._map_rect
        top_left = self.mapFromScene(QPointF(mx, my))
        bottom_right = self.mapFromScene(QPointF(mx + mw, my + mh))
        left = min(top_left.x(), bottom_right.x())
        right = max(top_left.x(), bottom_right.x())
        top = min(top_left.y(), bottom_right.y())
        bottom = max(top_left.y(), bottom_right.y())
        visible_w = right - left
        visible_h = bottom - top
        if visible_w < 80 or visible_h < 80:
            return
        margin = 18
        target_h = min(220, max(150, int(visible_h * 0.32)))
        scaled = self._colorbar_pixmap.scaledToHeight(
            target_h, Qt.TransformationMode.SmoothTransformation
        )
        painter = QPainter(self.viewport())
        bg_w = scaled.width() + 12
        bg_h = scaled.height() + 12
        x = max(margin, int(left + 18))
        y = max(margin, int(top + visible_h * 0.58))
        if y + bg_h > bottom - margin:
            y = int(bottom - margin - bg_h)
        painter.fillRect(x, y, bg_w, bg_h, QColor(255, 255, 255, 128))
        painter.setPen(QPen(QColor(80, 80, 80)))
        painter.drawRect(x, y, bg_w, bg_h)
        painter.drawPixmap(x + 6, y + 6, scaled)
        painter.end()

    def _paint_scalebar(self, painter, left_x, base_y, distance_m, target_px, close_painter=True):
        if target_px <= 0 or distance_m <= 0:
            if close_painter and painter.isActive():
                painter.end()
            return
        nice_m = self._nice_scalebar_distance(distance_m)
        bar_px = target_px * (nice_m / distance_m)
        if bar_px < 20:
            if close_painter and painter.isActive():
                painter.end()
            return

        label = f"{nice_m/1000:.2f} km" if nice_m >= 1000 else f"{int(round(nice_m))} m"
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(QFont("Helvetica", 9))
        fm = painter.fontMetrics()

        right_x = left_x + bar_px
        label_w = fm.horizontalAdvance(label)
        bg_w = max(label_w + 12, int(bar_px) + 18)
        bg_h = fm.height() + 26
        painter.fillRect(left_x - 8, base_y - bg_h + 6, bg_w, bg_h, QColor(255, 255, 255, 128))
        pen = QPen(QColor("black"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(int(left_x), int(base_y), int(right_x), int(base_y))
        painter.drawLine(int(left_x), int(base_y - 7), int(left_x), int(base_y + 7))
        painter.drawLine(int(right_x), int(base_y - 7), int(right_x), int(base_y + 7))
        painter.setPen(QPen(QColor("black")))
        painter.drawText(int(left_x + (bar_px - label_w) / 2), int(base_y - 10), label)
        if close_painter and painter.isActive():
            painter.end()

    def _nice_scalebar_distance(self, distance_m):
        if distance_m <= 0:
            return 0
        magnitude = 10 ** math.floor(math.log10(distance_m))
        residual = distance_m / magnitude
        if residual >= 5:
            nice = 5 * magnitude
        elif residual >= 2:
            nice = 2 * magnitude
        else:
            nice = magnitude
        return nice

    def mousePressEvent(self, event):
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ) and self._pixmap_item is not None and self._region is not None:
            pos = event.position().toPoint()
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_pos = pos
                self._dragging = False
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self._panning = True
                self._pan_anchor = pos
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        scene_pt = self.mapToScene(pos)
        self._hover_info_text = self._hover_lonlat_depth(scene_pt) or ""
        self.viewport().update()
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ) and self._panning and self._pan_anchor is not None:
            delta = pos - self._pan_anchor
            self._pan_anchor = pos
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ) and self._press_pos is not None:
            if (pos - self._press_pos).manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_info_text = ""
        self.viewport().update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ) and event.button() == Qt.MouseButton.RightButton:
            self._panning = False
            self._pan_anchor = None
            event.accept()
            return
        if (
            self._plan_mode
            or self._user_point_pick_mode
            or self._user_point_edit_mode
            or self._user_point_delete_mode
            or self._user_line_pick_mode
            or self._user_line_delete_mode
        ) and event.button() == Qt.MouseButton.LeftButton:
            if (
                not self._dragging
                and self._press_pos is not None
                and self._region is not None
            ):
                scene_pt = self.mapToScene(event.position().toPoint())
                inside = self._inside_pixmap_scene(scene_pt)
                if inside is not None:
                    sx, sy = inside
                    lon0, lon1, lat0, lat1 = self._region
                    lon, lat = scene_xy_to_lonlat(
                        sx, sy, self._img_w, self._img_h, lon0, lon1, lat0, lat1
                    )
                    if self._user_point_pick_mode:
                        self.user_point_clicked.emit(lon, lat)
                    elif self._user_point_edit_mode:
                        self.user_point_edit_clicked.emit(lon, lat)
                    elif self._user_point_delete_mode:
                        self.user_point_delete_clicked.emit(lon, lat)
                    elif self._user_line_pick_mode:
                        self.user_line_clicked.emit(lon, lat)
                    elif self._user_line_delete_mode:
                        self.user_line_delete_clicked.emit(lon, lat)
                    elif self._plan_mode:
                        self.digitize_clicked.emit(lon, lat)
            self._press_pos = None
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)



    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap_item is None:
            super().wheelEvent(event)
            return

        factor = self._ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self._ZOOM_STEP

        # ⭐ 关键：以鼠标位置为中心缩放
        old_pos = self.mapToScene(event.position().toPoint())

        self.scale(factor, factor)

        new_pos = self.mapToScene(event.position().toPoint())

        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

        event.accept()        

    def keyPressEvent(self, event):
        if self._user_line_pick_mode and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.user_line_finish_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        
   #  def wheelEvent(self, event: QWheelEvent):
#         if self._pixmap_item is None:
#             super().wheelEvent(event)
#             return
#         delta = event.angleDelta().y()
#         if delta == 0:
#             super().wheelEvent(event)
#             return
#         factor = self._ZOOM_STEP if delta < 0 else 1.0 / self._ZOOM_STEP
#         old = self.transform()
#         self.scale(factor, factor)
#         s = self.transform().m11()
#         if s < self._SCALE_MIN or s > self._SCALE_MAX:
#             self.setTransform(old)
#         event.accept()


class App(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("HOV GMT 双尺度制图系统")

        self.cfg = load_config()
        self._selected_projection = str(self.cfg.get("projection_name", "墨卡托")) or "墨卡托"

        left = QWidget()
        left.setMinimumWidth(440)
        layout = QVBoxLayout(left)

        self.file_label = QLabel(self.cfg.get("file", "未选择TIF"))
        btn_file = QPushButton("选择TIF")
        btn_file.clicked.connect(self.select_file)

        self.xmin = QLineEdit(str(self.cfg.get("xmin", 40)))
        self.xmax = QLineEdit(str(self.cfg.get("xmax", 140)))
        self.ymin = QLineEdit(str(self.cfg.get("ymin", 80)))
        self.ymax = QLineEdit(str(self.cfg.get("ymax", 88)))

        self.dx = QLineEdit(str(self.cfg.get("dx", 0.01)))
        self.dy = QLineEdit(str(self.cfg.get("dy", 0.01)))

        self.contour = QLineEdit(str(self.cfg.get("contour", 100)))

        self.route_preview = RouteMapPreviewView()
        self.route_preview.digitize_clicked.connect(self._append_digitized_point)
        self.route_preview.user_point_clicked.connect(self._handle_user_point_picked)
        self.route_preview.user_point_edit_clicked.connect(self._handle_user_point_edit_clicked)
        self.route_preview.user_point_delete_clicked.connect(self._handle_user_point_delete_clicked)
        self.route_preview.user_line_clicked.connect(self._handle_user_line_clicked)
        self.route_preview.user_line_delete_clicked.connect(self._handle_user_line_delete_clicked)
        self.route_preview.user_line_finish_requested.connect(self._finish_pending_user_line)

        btn_run = QPushButton("生成下潜计划大图")
        btn_run.setMinimumHeight(44)
        btn_run.clicked.connect(self.run)

        # ⭐新增 ROI按钮
        btn_roi = QPushButton("生成下潜计划小图")
        btn_roi.setMinimumHeight(44)
        btn_roi.clicked.connect(self.open_roi)

        layout.addWidget(self.file_label)
        layout.addWidget(btn_file)

        layout.addWidget(QLabel("xmin"))
        layout.addWidget(self.xmin)
        layout.addWidget(QLabel("xmax"))
        layout.addWidget(self.xmax)
        layout.addWidget(QLabel("ymin"))
        layout.addWidget(self.ymin)
        layout.addWidget(QLabel("ymax"))
        layout.addWidget(self.ymax)

        layout.addWidget(QLabel("dx dy"))
        layout.addWidget(self.dx)
        layout.addWidget(self.dy)

        layout.addWidget(QLabel("contour"))
        layout.addWidget(self.contour)

        self.cb_contour = QCheckBox("出图包含等值线（生成大图与墨卡托无刻度底图均生效）")
        self.cb_contour.setChecked(bool(self.cfg.get("show_contour", True)))
        layout.addWidget(self.cb_contour)

        self.btn_projection = QPushButton()
        self.btn_projection.setMinimumHeight(44)
        self.btn_projection.clicked.connect(self.select_projection_system)
        self._refresh_projection_button_text()
        layout.addWidget(self.btn_projection)

        self.btn_basemap = QPushButton("生成规划底图")
        self.btn_basemap.setMinimumHeight(44)
        self.btn_basemap.clicked.connect(self.build_selected_basemap)
        layout.addWidget(self.btn_basemap)

        self.btn_hover_info = QPushButton("实时点信息：关闭")
        self.btn_hover_info.setMinimumHeight(44)
        self.btn_hover_info.setCheckable(True)
        self.btn_hover_info.setChecked(False)
        self.btn_hover_info.clicked.connect(self.toggle_hover_info)
        self._refresh_hover_info_button_text()
        layout.addWidget(self.btn_hover_info)

        btn_export_preview = QPushButton("导出当前图片")
        btn_export_preview.setMinimumHeight(44)
        btn_export_preview.clicked.connect(self.export_current_preview_image)
        layout.addWidget(btn_export_preview)

        self.cb_plan = QCheckBox(
            "规划路线：左键点击地图加点 → 同步到 points（须先完成上方底图）"
        )
        self.cb_plan.setEnabled(False)
        self.cb_plan.toggled.connect(self.route_preview.set_plan_mode)
        layout.addWidget(self.cb_plan)

        hrow_pts = QHBoxLayout()
        self.btn_undo = QPushButton("撤销末点")
        self.btn_undo.setMinimumHeight(52)
        self.btn_undo.setMinimumWidth(100)
        self.btn_undo.setMaximumWidth(118)
        f = self.btn_undo.font()
        f.setPointSize(max(f.pointSize(), 12))
        self.btn_undo.setFont(f)
        self.btn_clr = QPushButton("清空航点")
        self.btn_clr.setMinimumHeight(52)
        self.btn_clr.setMinimumWidth(100)
        self.btn_clr.setMaximumWidth(118)
        self.btn_clr.setFont(f)
        self.btn_undo.clicked.connect(self.undo_last_point)
        self.btn_clr.clicked.connect(self.clear_points_track)
        self.btn_depth_profile = QPushButton("深度剖面")
        self.btn_depth_profile.setMinimumHeight(52)
        self.btn_depth_profile.setFont(f)
        self.btn_depth_profile.clicked.connect(self.show_depth_profile)
        self.btn_point_feature = QPushButton("点功能")
        self.btn_point_feature.setMinimumHeight(52)
        self.btn_point_feature.setFont(f)
        self.btn_point_feature.clicked.connect(self.open_point_feature_dialog)
        self.btn_line_feature = QPushButton("线功能")
        self.btn_line_feature.setMinimumHeight(52)
        self.btn_line_feature.setFont(f)
        self.btn_line_feature.clicked.connect(self.open_line_feature_dialog)
        hrow_pts.addWidget(self.btn_undo)
        hrow_pts.addWidget(self.btn_clr)
        hrow_pts.addWidget(self.btn_depth_profile)
        hrow_pts.addWidget(self.btn_point_feature)
        hrow_pts.addWidget(self.btn_line_feature)
        hrow_pts.addStretch(1)
        layout.addLayout(hrow_pts)

        layout.addWidget(QLabel("points"))
        self.points = QTextEdit()
        self.points.setPlaceholderText("经度 纬度")
        self.points.setMinimumHeight(320)
        if "points" in self.cfg:
            self.points.setPlainText(self.cfg["points"])
        layout.addWidget(self.points, stretch=1)

        self._overlay_timer = QTimer(self)
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self.refresh_points_text_and_overlay)
        self.points.textChanged.connect(lambda: self._overlay_timer.start(280))

        layout.addWidget(btn_run)

        frame_row = QHBoxLayout()
        self.frame_style = QComboBox()
        self.frame_style.addItems(["plain", "fancy"])
        self.frame_style.setCurrentText(str(self.cfg.get("frame_style", "plain")))
        self.lon_tick = QLineEdit(str(self.cfg.get("lon_tick", "")))
        self.lat_tick = QLineEdit(str(self.cfg.get("lat_tick", "")))
        self.lon_tick.setPlaceholderText("经度间隔")
        self.lat_tick.setPlaceholderText("纬度间隔")
        frame_row.addWidget(QLabel("框式"))
        frame_row.addWidget(self.frame_style)
        frame_row.addWidget(QLabel("经度间隔"))
        frame_row.addWidget(self.lon_tick)
        frame_row.addWidget(QLabel("纬度间隔"))
        frame_row.addWidget(self.lat_tick)
        layout.addLayout(frame_row)

        layout.addWidget(btn_roi)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.route_preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 1180])

        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

        self.setMinimumSize(1480, 980)
        self.resize(1620, 1080)
        self.route_preview.setMinimumWidth(520)
        self.file = self.cfg.get("file", None)
        self.user_points = load_addpoint_txt()
        if not self.user_points:
            self.user_points = normalize_user_points(self.cfg.get("user_points", []))
            if self.user_points:
                write_addpoint_txt(self.user_points)
        self.user_lines = load_lines_txt()
        if not self.user_lines:
            self.user_lines = normalize_user_lines(self.cfg.get("user_lines", []))
            if self.user_lines:
                write_lines_txt(self.user_lines)
        self._planning_base_region = None
        self._planning_base_path = None
        self._last_export_map_rect = None
        self._last_frame_margins = (0, 0, 0, 0)
        self._colorbar_dialog = None
        self._colorbar_visible = True
        self._point_depth_cache = {}
        self._point_speed_values = [
            float(v)
            for v in self.cfg.get("point_speeds", [])
            if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip())
        ]
        self._updating_points_table = False
        self._updating_user_points_table = False
        self._updating_user_lines_table = False
        self.point_info_dialog = PointInfoDialog(self)
        self.point_info_dialog.table.itemChanged.connect(self._handle_points_table_item_changed)
        self.point_info_dialog.user_points_table.itemChanged.connect(
            self._handle_user_points_table_item_changed
        )
        self.point_info_dialog.user_lines_table.itemChanged.connect(
            self._handle_user_lines_table_item_changed
        )
        self.point_info_dialog.on_user_points_table_edited = self._sync_user_points_from_table
        self.point_info_dialog.on_user_lines_table_edited = self._sync_user_lines_from_table
        self.point_info_dialog.on_plan_table_edited = self._sync_plan_rows_from_table
        self._plot_mode = "final"
        self._basemap_ready_for_plan = False
        self._show_digitize_decor_overlay = False
        self._pending_user_point_pick = False
        self._pending_user_point_edit = False
        self._pending_user_point_delete = False
        self._pending_user_line_pick = False
        self._pending_user_line_delete = False
        self._pending_line_points = []
        self._update_mode_controls()
        self._update_default_frame_intervals(force=not ("lon_tick" in self.cfg and "lat_tick" in self.cfg))
        self.refresh_points_text_and_overlay()
    def query_depth_at_point(self, grid, lon, lat):
        """用 grdtrack 查询单点深度"""
        tmp_file = "_tmp_point.txt"
        with open(tmp_file, "w") as f:
            f.write(f"{lon} {lat}\n")

        try:
            res = pygmt.grdtrack(points=tmp_file, grid=grid)
            arr = np.asarray(res.to_numpy(), dtype=float)
            if arr.ndim == 2 and arr.shape[1] >= 3:
                return float(arr[0, 2])
        except Exception as e:
            print(f"⚠️ 深度查询失败: {e}")

        return np.nan

    def _grid_depth_range(self, region):
        if not self.file or region is None:
            return None, None
        lon0, lon1, lat0, lat1 = region
        try:
            res = subprocess.run(
                [
                    "gmt",
                    "grdinfo",
                    self.file,
                    f"-R{lon0}/{lon1}/{lat0}/{lat1}",
                    "-C",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            parts = res.stdout.strip().split()
            if len(parts) >= 7:
                zmin = float(parts[5])
                zmax = float(parts[6])
                depths = np.abs(grid_z_to_depth_m([zmin, zmax]))
                return float(np.min(depths)), float(np.max(depths))
        except Exception as e:
            print(f"⚠️ 色棒深度范围查询失败: {e}")
        return None, None
    def parse_plan_region(self):
        """规划/底图/GMT 共用范围：xmin–xmax / ymin–ymax。"""
        xmin = float(self.xmin.text())
        xmax = float(self.xmax.text())
        ymin = float(self.ymin.text())
        ymax = float(self.ymax.text())
        return xmin, xmax, ymin, ymax

    def _set_route_planning_available(self, available: bool):
        """仅在有墨卡托无刻度底图时可勾选规划；生成大图后关闭。"""
        self._basemap_ready_for_plan = available
        self.cb_plan.setEnabled(available)
        if not available:
            self.cb_plan.blockSignals(True)
            self.cb_plan.setChecked(False)
            self.cb_plan.blockSignals(False)
            self.route_preview.set_plan_mode(False)
        self._update_mode_controls()

    def _set_plot_mode(self, mode: str):
        self._plot_mode = mode
        if mode == "final":
            self._stop_user_point_modes()
            self.route_preview.set_plan_mode(False)
            if self.cb_plan.isChecked():
                self.cb_plan.blockSignals(True)
                self.cb_plan.setChecked(False)
                self.cb_plan.blockSignals(False)
        self._update_mode_controls()

    def _update_mode_controls(self):
        interactive_ready = self._plot_mode == "interactive" and self._basemap_ready_for_plan
        self.btn_point_feature.setEnabled(interactive_ready)
        self.btn_line_feature.setEnabled(interactive_ready)
        self.btn_hover_info.setEnabled(interactive_ready)
        if self._plot_mode == "final":
            self.btn_point_feature.setToolTip("当前为下潜计划大图预览，禁止点模式交互")
            self.btn_line_feature.setToolTip("当前为下潜计划大图预览，禁止线模式交互")
            self.btn_hover_info.setToolTip("当前为下潜计划大图预览，实时点信息不可用")
        elif not self._basemap_ready_for_plan:
            self.btn_point_feature.setToolTip("请先生成墨卡托无刻度底图")
            self.btn_line_feature.setToolTip("请先生成墨卡托无刻度底图")
            self.btn_hover_info.setToolTip("请先生成规划底图")
        else:
            self.btn_point_feature.setToolTip("")
            self.btn_line_feature.setToolTip("")
            self.btn_hover_info.setToolTip("")
        if not interactive_ready and self.btn_hover_info.isChecked():
            self.btn_hover_info.blockSignals(True)
            self.btn_hover_info.setChecked(False)
            self.btn_hover_info.blockSignals(False)
            self.route_preview.set_hover_info_enabled(False)
            self._refresh_hover_info_button_text()

    def _ensure_interactive_mode(self):
        if self._plot_mode != "interactive" or not self._basemap_ready_for_plan:
            QMessageBox.information(
                self,
                "点功能",
                "当前是下潜计划大图预览模式，禁止点线编辑。请先生成墨卡托无刻度底图进入规划模式。",
            )
            return False
        return True

    def _refresh_projection_button_text(self):
        self.btn_projection.setText(f"选择投影系统：{self._selected_projection}")

    def _refresh_hover_info_button_text(self):
        state_text = "开启" if self.btn_hover_info.isChecked() else "关闭"
        self.btn_hover_info.setText(f"实时点信息：{state_text}")

    def select_projection_system(self):
        options = ["墨卡托"]
        current_index = options.index(self._selected_projection) if self._selected_projection in options else 0
        choice, ok = QInputDialog.getItem(
            self,
            "选择投影系统",
            "投影系统：",
            options,
            current_index,
            False,
        )
        if not ok or not choice:
            return
        self._selected_projection = choice
        self._refresh_projection_button_text()
        self.save_state()

    def build_selected_basemap(self):
        if self._selected_projection == "墨卡托":
            self.build_mercator_basemap()
            return
        QMessageBox.information(self, "投影系统", f"暂不支持 {self._selected_projection} 投影。")

    def toggle_hover_info(self, checked):
        if checked and not self._ensure_interactive_mode():
            self.btn_hover_info.blockSignals(True)
            self.btn_hover_info.setChecked(False)
            self.btn_hover_info.blockSignals(False)
            checked = False
        self.route_preview.set_hover_info_enabled(checked)
        self._refresh_hover_info_button_text()

    def _update_default_frame_intervals(self, force=False, region=None):
        try:
            if region is None:
                xmin, xmax, ymin, ymax = self.parse_plan_region()
            else:
                xmin, xmax, ymin, ymax = region
        except ValueError:
            return

        lon_default = max((xmax - xmin) / 4.0, 1e-6)
        lat_default = max((ymax - ymin) / 4.0, 1e-6)

        if force or not self.lon_tick.text().strip():
            self.lon_tick.setText(f"{lon_default:.4f}".rstrip("0").rstrip("."))
        if force or not self.lat_tick.text().strip():
            self.lat_tick.setText(f"{lat_default:.4f}".rstrip("0").rstrip("."))

    def build_mercator_basemap(self):
        if not self.file:
            print("❌ 请选择TIF")
            return
        try:
            lon0, lon1, lat0, lat1 = self.parse_plan_region()
        except ValueError:
            print("❌ xmin/xmax/ymin/ymax 数值无效")
            return
        region = [lon0, lon1, lat0, lat1]
        if self.cb_contour.isChecked():
            try:
                cint = float(self.contour.text())
            except ValueError:
                print("❌ contour 间隔数值无效")
                return
        fig = pygmt.Figure()
        fig.grdimage(
            grid=self.file,
            region=region,
            projection="M7i",
            cmap="haxby",
            shading=True,
            frame=False,
        )
        if self.cb_contour.isChecked():
            fig.grdcontour(
                grid=self.file,
                interval=cint,
                annotation=cint,
                pen="0.6p,black",
            )
        fig.savefig(DIGITIZE_BASE_PNG, dpi=200)
        depth_min, depth_max = self._grid_depth_range(region)
        render_haxby_colorbar(PREVIEW_COLORBAR_PNG, depth_min=depth_min, depth_max=depth_max)
        self._planning_base_region = tuple(region)
        self._planning_base_path = DIGITIZE_BASE_PNG
        self._last_export_map_rect = None
        self._update_default_frame_intervals(region=tuple(region))
        print(f"✔ {DIGITIZE_BASE_PNG} 已生成（墨卡托 -JM7i，无刻度）")
        self._show_digitize_decor_overlay = True
        self._set_plot_mode("interactive")
        if not self._show_route_map_preview(DIGITIZE_BASE_PNG, (lon0, lon1, lat0, lat1)):
            self._show_digitize_decor_overlay = False
            return
        self._set_route_planning_available(True)
        self.cb_plan.blockSignals(True)
        self.cb_plan.setChecked(True)
        self.cb_plan.blockSignals(False)
        self.route_preview.set_plan_mode(True)
        self.save_state()

    def _append_digitized_point(self, lon, lat):
        if self._plot_mode != "interactive":
            return
        if not self.file:
            depth = np.nan
        else:
            depth = -self.query_depth_at_point(self.file, lon, lat)
            depth = -grid_z_to_depth_m([depth])[0]
        self._point_depth_cache[self._point_cache_key(lon, lat)] = depth

        line = f"{lon:.4f} {lat:.4f}"

        cur = self.points.toPlainText().rstrip()
        self.points.blockSignals(True)
        self.points.setPlainText(cur + ("\n" if cur else "") + line)
        self.points.blockSignals(False)

        self.refresh_points_text_and_overlay()
        rows = self._get_plan_rows()
        if rows:
            self._show_point_info_popup(len(rows) - 1)

    def open_point_feature_dialog(self):
        if not self._ensure_interactive_mode():
            return
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

    def open_line_feature_dialog(self):
        if not self._ensure_interactive_mode():
            return
        dlg = LineModeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.selected_mode == LineModeDialog.MODE_MANUAL:
            self._open_user_line_editor()
        elif dlg.selected_mode == LineModeDialog.MODE_PICK:
            self.start_user_line_pick_mode()
        elif dlg.selected_mode == LineModeDialog.MODE_DELETE:
            self.start_user_line_delete_mode()

    def _stop_user_point_modes(self):
        self.route_preview.set_user_point_pick_mode(False)
        self.route_preview.set_user_point_edit_mode(False)
        self.route_preview.set_user_point_delete_mode(False)
        self.route_preview.set_user_line_pick_mode(False)
        self.route_preview.set_user_line_delete_mode(False)
        self.route_preview.set_temporary_line_points([])
        self._pending_user_point_pick = False
        self._pending_user_point_edit = False
        self._pending_user_point_delete = False
        self._pending_user_line_pick = False
        self._pending_user_line_delete = False
        self._pending_line_points = []

    def _open_user_point_editor(self, point=None, replace_index=None):
        if not self._ensure_interactive_mode():
            return
        dlg = PointEditorDialog(self, point=point)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if replace_index is not None:
                self.sync_user_points_from_file(fallback_current=True)
                if 0 <= replace_index < len(self.user_points):
                    self.user_points[replace_index] = dlg.point_data
                    write_addpoint_txt(self.user_points)
                else:
                    append_addpoint_txt(dlg.point_data)
            else:
                append_addpoint_txt(dlg.point_data)
            self.sync_user_points_from_file()
            self._stop_user_point_modes()
            self.reload_route_overlay_from_text()
            self.save_state()

    def _open_user_line_editor(self, line=None, replace_index=None):
        if not self._ensure_interactive_mode():
            return
        dlg = LineEditorDialog(self, line=line)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.sync_user_lines_from_file(fallback_current=True)
        line_data = dlg.line_data
        if not line_data.get("name"):
            line_data["name"] = f"L{len(self.user_lines) + 1}"
        if replace_index is not None and 0 <= replace_index < len(self.user_lines):
            self.user_lines[replace_index] = line_data
        else:
            self.user_lines.append(line_data)
        write_lines_txt(self.user_lines)
        self.sync_user_lines_from_file(fallback_current=True)
        self._stop_user_point_modes()
        self.reload_route_overlay_from_text()
        self.save_state()

    def start_user_point_pick_mode(self):
        if not self._ensure_interactive_mode():
            return
        if self.route_preview._region is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(
                self,
                "点功能",
                "请先生成并显示地图预览，再使用鼠标点击添加点。",
            )
            return
        self._stop_user_point_modes()
        self._pending_user_point_pick = True
        self.route_preview.set_user_point_pick_mode(True)
        print("✔ 点拾取模式已启用：请在右侧地图左键点击一个位置")

    def start_user_line_pick_mode(self):
        if not self._ensure_interactive_mode():
            return
        if self.route_preview._region is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(self, "线功能", "请先生成并显示地图预览，再使用鼠标点击添加线。")
            return
        self._stop_user_point_modes()
        self._pending_user_line_pick = True
        self._pending_line_points = []
        self.route_preview.set_user_line_pick_mode(True)
        self.route_preview.setFocus()
        print("✔ 线拾取模式已启用：请连续左键点击添加线点，按回车结束")

    def start_user_point_edit_mode(self):
        if not self._ensure_interactive_mode():
            return
        if self.route_preview._region is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(
                self,
                "点功能",
                "请先生成并显示地图预览，再使用编辑模式。",
            )
            return
        self.sync_user_points_from_file(fallback_current=True)
        if not self.user_points:
            QMessageBox.information(self, "点功能", "当前没有可编辑的标注点。")
            return
        self._stop_user_point_modes()
        self._pending_user_point_edit = True
        self.route_preview.set_user_point_edit_mode(True)
        print("✔ 点编辑模式已启用：请在右侧地图左键点击要编辑的标注点")

    def start_user_point_delete_mode(self):
        if not self._ensure_interactive_mode():
            return
        if self.route_preview._region is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(
                self,
                "点功能",
                "请先生成并显示地图预览，再使用删除模式。",
            )
            return
        self.sync_user_points_from_file(fallback_current=True)
        if not self._get_plan_rows() and not self.user_points:
            QMessageBox.information(self, "点功能", "当前没有可删除的点。")
            return
        self._stop_user_point_modes()
        self._pending_user_point_delete = True
        self.route_preview.set_user_point_delete_mode(True)
        print("✔ 点删除模式已启用：请在右侧地图左键点击要删除的点附近")

    def start_user_line_delete_mode(self):
        if not self._ensure_interactive_mode():
            return
        if self.route_preview._region is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(self, "线功能", "请先生成并显示地图预览，再使用删除线。")
            return
        if not self.user_lines:
            QMessageBox.information(self, "线功能", "当前没有可删除的线。")
            return
        self._stop_user_point_modes()
        self._pending_user_line_delete = True
        self.route_preview.set_user_line_delete_mode(True)
        print("✔ 线删除模式已启用：请在右侧地图左键点击要删除的线附近")

    def _handle_user_point_picked(self, lon, lat):
        if not self._pending_user_point_pick or self._plot_mode != "interactive":
            return
        self._stop_user_point_modes()
        self._open_user_point_editor(
            {
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "name": "",
                "color": "#ff0000",
                "shape": "circle",
                "label_pos": "右上",
                "font_size": 8,
            }
        )

    def _handle_user_line_clicked(self, lon, lat):
        if not self._pending_user_line_pick or self._plot_mode != "interactive":
            return
        self._pending_line_points.append((round(lon, 6), round(lat, 6)))
        self.route_preview.set_temporary_line_points(self._pending_line_points)
        print(f"✔ 已添加线点 {len(self._pending_line_points)} 个，按回车结束")

    def _finish_pending_user_line(self):
        if not self._pending_user_line_pick or self._plot_mode != "interactive":
            return
        if len(self._pending_line_points) < 2:
            QMessageBox.information(self, "线功能", "至少需要 2 个点才能结束画线。")
            return
        line_points = [[lon, lat] for lon, lat in self._pending_line_points]
        self._stop_user_point_modes()
        self._open_user_line_editor(
            {
                "name": "",
                "color": DEFAULT_LINE_COLOR,
                "line_style": "实线",
                "font_size": 8,
                "points": line_points,
            }
        )

    def _handle_user_point_edit_clicked(self, lon, lat):
        if not self._pending_user_point_edit or self._plot_mode != "interactive":
            return
        self.sync_user_points_from_file(fallback_current=True)
        target_type, idx = self._find_nearest_overlay_target(lon, lat)
        if target_type is None or idx is None:
            print("⚠️ 未找到足够接近的点，未执行编辑")
            return
        if target_type != "user":
            QMessageBox.information(self, "点功能", "当前只能编辑点功能添加的标注点。")
            return
        point = dict(self.user_points[idx])
        self._stop_user_point_modes()
        self._open_user_point_editor(point=point, replace_index=idx)

    def _handle_user_point_delete_clicked(self, lon, lat):
        if not self._pending_user_point_delete or self._plot_mode != "interactive":
            return
        self.sync_user_points_from_file(fallback_current=True)
        target_type, idx = self._find_nearest_overlay_target(lon, lat)
        if target_type is None or idx is None:
            print("⚠️ 未找到足够接近的点，未执行删除")
            return

        if target_type == "plan":
            rows = self._get_plan_rows()
            removed = rows.pop(idx)
            self._set_plan_rows(rows)
            print(f"✔ 已删除规划点: ({removed[0]:.4f}, {removed[1]:.4f})")
        else:
            self.sync_user_points_from_file()
            removed = self.user_points.pop(idx)
            write_addpoint_txt(self.user_points)
            self.sync_user_points_from_file()
            self.reload_route_overlay_from_text()
            print(
                f"✔ 已删除标注点: {removed.get('name', '')} "
                f"({removed.get('lon'):.4f}, {removed.get('lat'):.4f})"
            )

        self._stop_user_point_modes()
        self.save_state()

    def _handle_user_line_delete_clicked(self, lon, lat):
        if not self._pending_user_line_delete or self._plot_mode != "interactive":
            return
        idx = self._find_nearest_user_line(lon, lat)
        if idx is None:
            print("⚠️ 未找到足够接近的线，未执行删除")
            return
        self.sync_user_lines_from_file(fallback_current=True)
        removed = self.user_lines.pop(idx)
        write_lines_txt(self.user_lines)
        self.sync_user_lines_from_file(fallback_current=True)
        self.reload_route_overlay_from_text()
        self._stop_user_point_modes()
        self.save_state()
        print(f"✔ 已删除线: {removed.get('name', '')}")

    def _find_nearest_user_line(self, lon, lat, max_scene_distance=14.0):
        if self.route_preview._region is None:
            return None
        lon0, lon1, lat0, lat1 = self.route_preview._region
        w, h = self.route_preview._img_w, self.route_preview._img_h
        px, py = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
        best_idx = None
        best_dist = None
        for i, line in enumerate(self.user_lines):
            pts_line = line.get("points") or []
            if len(pts_line) < 2:
                continue
            try:
                scene_pts = [
                    lonlat_to_scene_xy(float(pt[0]), float(pt[1]), w, h, lon0, lon1, lat0, lat1)
                    for pt in pts_line
                ]
            except (TypeError, ValueError, IndexError):
                continue
            dist = None
            for (x0, y0), (x1, y1) in zip(scene_pts[:-1], scene_pts[1:]):
                seg_len2 = (x1 - x0) ** 2 + (y1 - y0) ** 2
                if seg_len2 <= 1e-9:
                    seg_dist = math.hypot(px - x0, py - y0)
                else:
                    t = ((px - x0) * (x1 - x0) + (py - y0) * (y1 - y0)) / seg_len2
                    t = max(0.0, min(1.0, t))
                    proj_x = x0 + t * (x1 - x0)
                    proj_y = y0 + t * (y1 - y0)
                    seg_dist = math.hypot(px - proj_x, py - proj_y)
                dist = seg_dist if dist is None else min(dist, seg_dist)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_idx = i
        if best_dist is not None and best_dist <= max_scene_distance:
            return best_idx
        return None

    def _find_nearest_overlay_target(self, lon, lat, max_scene_distance=16.0):
        if self.route_preview._region is None:
            return None, None
        lon0, lon1, lat0, lat1 = self.route_preview._region
        w, h = self.route_preview._img_w, self.route_preview._img_h
        click_sx, click_sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)

        plan_rows = self._get_plan_rows()
        best_plan_idx = None
        best_plan_dist = None
        for i, (pt_lon, pt_lat, _) in enumerate(plan_rows):
            sx, sy = lonlat_to_scene_xy(pt_lon, pt_lat, w, h, lon0, lon1, lat0, lat1)
            dist = math.hypot(sx - click_sx, sy - click_sy)
            if best_plan_dist is None or dist < best_plan_dist:
                best_plan_idx = i
                best_plan_dist = dist

        if best_plan_dist is not None and best_plan_dist <= max_scene_distance:
            return "plan", best_plan_idx

        best_user_idx = None
        best_user_dist = None
        for i, point in enumerate(self.user_points):
            try:
                pt_lon = float(point["lon"])
                pt_lat = float(point["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            sx, sy = lonlat_to_scene_xy(pt_lon, pt_lat, w, h, lon0, lon1, lat0, lat1)
            dist = math.hypot(sx - click_sx, sy - click_sy)
            if best_user_dist is None or dist < best_user_dist:
                best_user_idx = i
                best_user_dist = dist

        if best_user_dist is not None and best_user_dist <= max_scene_distance:
            return "user", best_user_idx
        return None, None

    def reload_route_overlay_from_text(self):
        self.sync_user_points_from_file()
        self.sync_user_lines_from_file(fallback_current=True)
        if self._plot_mode == "final":
            self.route_preview.update_route_overlay([])
            return
        if not self._show_digitize_decor_overlay:
            self.route_preview.update_route_overlay([], user_points=self.user_points, user_lines=self.user_lines)
            return
        pts, _ = self.parse_points_with_depth(
            self.points.toPlainText()
        )
        rows = self._resolve_rows_depths(self._get_plan_rows())
        self._sync_point_speeds(len(rows))
        metrics = build_points_metrics(
            [(lon, lat) for lon, lat, _ in rows],
            depths=[depth for _, _, depth in rows],
            speed_mps=POINTS_SPEED_MPS,
            speeds_mps=self._point_speed_values,
        )
        segment_labels = self._build_segment_labels(metrics)
        box = None
        if pts:
            try:
                box = self._compute_route_box(pts)
            except ValueError:
                pass
        self.route_preview.update_route_overlay(
            pts,
            box=box,
            user_points=self.user_points,
            user_lines=self.user_lines,
            segment_labels=segment_labels,
        )
    def parse_points_rows(self, text):
        rows = []
        raw_lines = [line.rstrip() for line in text.splitlines() if line.strip()]

        for line in raw_lines:
            try:
                parts = list(map(float, line.split()))
            except ValueError:
                return [], False

            if len(parts) < 2:
                return [], False

            depth = parts[2] if len(parts) >= 3 else np.nan
            rows.append((parts[0], parts[1], depth))

        return rows, True

    def _format_points_text_with_metrics(self, rows):
        coords = [(lon, lat) for lon, lat, _ in rows]
        metrics = build_points_metrics(coords, speed_mps=POINTS_SPEED_MPS)
        lines = [
            (
                f"{'lon':>10} {'lat':>10} {'depth':>10} "
                f"{'cum_km':>10} {'cum_h':>10} {'seg_km':>10} {'seg_h':>10}"
            )
        ]

        for (lon, lat, depth), metric in zip(rows, metrics):
            lines.append(
                (
                    f"{lon:>10.4f} "
                    f"{lat:>10.4f} "
                    f"{(f'{depth:.2f}' if np.isfinite(depth) else 'nan'):>10} "
                    f"{metric['cum_dist_km']:>10.2f} "
                    f"{metric['cum_time_h']:>10.2f} "
                    f"{metric['seg_dist_km']:>10.2f} "
                    f"{metric['seg_time_h']:>10.2f}"
                )
            )

        return "\n".join(lines)

    def _update_points_display(self, rows):
        rows = self._resolve_rows_depths(rows)
        self.sync_user_points_from_file(fallback_current=True)
        self.sync_user_lines_from_file(fallback_current=True)
        user_point_rows = self._resolve_user_points_depths(self.user_points)
        user_line_rows = self._resolve_user_lines_rows(self.user_lines)
        self._sync_point_speeds(len(rows))
        metrics = build_points_metrics(
            [(lon, lat) for lon, lat, _ in rows],
            depths=[depth for _, _, depth in rows],
            speed_mps=POINTS_SPEED_MPS,
            speeds_mps=self._point_speed_values,
        )
        table = self.point_info_dialog.table
        self._updating_points_table = True
        table.setRowCount(len(rows))
        for r, ((lon, lat, depth), metric) in enumerate(zip(rows, metrics)):
            values = [
                str(metric["seg_no"]),
                f"{lon:.4f}",
                f"{lat:.4f}",
                f"{metric['heading_deg']:.2f}" if np.isfinite(metric["heading_deg"]) else "nan",
                f"{depth:.2f}" if np.isfinite(depth) else "nan",
                f"{metric['cum_dist_km']:.2f}",
                f"{metric['cum_time_h']:.2f}",
                f"{metric['seg_dist_km']:.2f}",
                f"{metric['seg_time_h']:.2f}",
                f"{metric['avg_slope_deg']:.2f}" if np.isfinite(metric["avg_slope_deg"]) else "nan",
                f"{metric['speed_mps']:.3f}",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c not in (1, 2, 10):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()

        user_table = self.point_info_dialog.user_points_table
        self._updating_user_points_table = True
        user_table.setRowCount(max(100, len(user_point_rows)))
        for r, point in enumerate(user_point_rows):
            values = [
                point["name"],
                f"{point['lon']:.4f}",
                f"{point['lat']:.4f}",
                point.get("depth_text", f"{point['depth']:.2f}" if np.isfinite(point["depth"]) else "nan"),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                user_table.setItem(r, c, item)
        user_table.resizeColumnsToContents()
        self._updating_user_points_table = False

        line_table = self.point_info_dialog.user_lines_table
        self._updating_user_lines_table = True
        line_table.setRowCount(max(100, len(user_line_rows)))
        for r, line_row in enumerate(user_line_rows):
            values = [
                line_row["name"],
                f"{line_row['lon']:.4f}",
                f"{line_row['lat']:.4f}",
                f"{line_row['length_km']:.3f}",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                line_table.setItem(r, c, item)
        line_table.resizeColumnsToContents()
        self._updating_user_lines_table = False
        self._updating_points_table = False
        if rows:
            self.point_info_dialog.info_label.setText(self._build_point_info_text(len(rows) - 1, rows, metrics))
            if not self.point_info_dialog.isVisible():
                self.point_info_dialog.show()
        else:
            self.point_info_dialog.info_label.setText("暂无规划点。")
            if user_point_rows:
                if not self.point_info_dialog.isVisible():
                    self.point_info_dialog.show()
            else:
                self.point_info_dialog.hide()

    def _line_length_km(self, points):
        if len(points) < 2:
            return 0.0
        total_m = 0.0
        for (lon0, lat0), (lon1, lat1) in zip(points[:-1], points[1:]):
            total_m += haversine_distance_m(lon0, lat0, lon1, lat1)
        return total_m / 1000.0

    def _resolve_user_lines_rows(self, user_lines):
        rows = []
        for line in normalize_user_lines(user_lines):
            name = str(line.get("name", "")).strip()
            points = [(float(lon), float(lat)) for lon, lat in line.get("points", [])]
            length_km = self._line_length_km(points)
            for lon, lat in points:
                rows.append(
                    {
                        "name": name,
                        "lon": lon,
                        "lat": lat,
                        "length_km": length_km,
                    }
                )
        return rows

    def _build_point_info_text(self, index, rows=None, metrics=None):
        if rows is None:
            rows = self._get_plan_rows()
        if metrics is None:
            metrics = build_points_metrics(
                [(lon, lat) for lon, lat, _ in rows],
                depths=[depth for _, _, depth in rows],
                speed_mps=POINTS_SPEED_MPS,
                speeds_mps=self._point_speed_values,
            )
        if index < 0 or index >= len(rows):
            return "无可用点信息。"
        lon, lat, depth = rows[index]
        metric = metrics[index]
        depth_text = f"{depth:.2f}" if np.isfinite(depth) else "nan"
        slope_text = (
            f"{metric['avg_slope_deg']:.2f}"
            if np.isfinite(metric["avg_slope_deg"])
            else "nan"
        )
        heading_text = (
            f"{metric['heading_deg']:.2f}"
            if np.isfinite(metric["heading_deg"])
            else "nan"
        )
        return (
            f"点序号: {index + 1}\n"
            f"seg_no: {metric['seg_no']}\n"
            f"经度: {lon:.4f}\n"
            f"纬度: {lat:.4f}\n"
            f"艏向角(deg): {heading_text}\n"
            f"深度: {depth_text}\n"
            f"累计距离(km): {metric['cum_dist_km']:.2f}\n"
            f"累计时间(h): {metric['cum_time_h']:.2f}\n"
            f"段距离(km): {metric['seg_dist_km']:.2f}\n"
            f"段时间(h): {metric['seg_time_h']:.2f}\n"
            f"平均地形坡度(deg): {slope_text}\n"
            f"航行速度(m/s): {metric['speed_mps']:.3f}"
        )

    def _show_point_info_popup(self, index):
        rows = self._resolve_rows_depths(self._get_plan_rows())
        metrics = build_points_metrics(
            [(lon, lat) for lon, lat, _ in rows],
            depths=[depth for _, _, depth in rows],
            speed_mps=POINTS_SPEED_MPS,
            speeds_mps=self._point_speed_values,
        )
        text = self._build_point_info_text(index, rows, metrics)
        self.point_info_dialog.info_label.setText(text)
        if not self.point_info_dialog.isVisible():
            self.point_info_dialog.show()
        QToolTip.showText(self.route_preview.mapToGlobal(self.route_preview.rect().center()), text, self.route_preview)

    def _handle_points_table_item_changed(self, item):
        if self._updating_points_table:
            return
        if item.column() in (1, 2, 10):
            self._sync_plan_rows_from_table()

    def _sync_plan_rows_from_table(self):
        rows = self._get_plan_rows()
        table = self.point_info_dialog.table
        if not rows or table.rowCount() == 0:
            return
        updated_rows = []
        new_speeds = []
        for row_idx in range(min(len(rows), table.rowCount())):
            _, _, depth = rows[row_idx]
            lon_item = table.item(row_idx, 1)
            lat_item = table.item(row_idx, 2)
            speed_item = table.item(row_idx, 10)
            try:
                lon = float(lon_item.text().strip()) if lon_item else rows[row_idx][0]
            except ValueError:
                lon = rows[row_idx][0]
            try:
                lat = float(lat_item.text().strip()) if lat_item else rows[row_idx][1]
            except ValueError:
                lat = rows[row_idx][1]
            try:
                speed = float(speed_item.text().strip()) if speed_item else POINTS_SPEED_MPS
            except ValueError:
                speed = POINTS_SPEED_MPS
            new_speeds.append(max(0.01, speed))
            updated_rows.append((lon, lat, depth))
        self._point_speed_values = new_speeds
        self._set_plan_rows(updated_rows)
        self.save_state()

    def _handle_user_points_table_item_changed(self, item):
        if self._updating_user_points_table:
            return
        if item.column() not in (0, 1, 2):
            return
        self._sync_user_points_from_table()

    def _handle_user_lines_table_item_changed(self, item):
        if self._updating_user_lines_table:
            return
        if item.column() not in (0, 1, 2):
            return
        self._sync_user_lines_from_table()

    def _sync_user_points_from_table(self):
        self.user_points = self._collect_user_points_from_table()
        write_addpoint_txt(self.user_points)
        self.sync_user_points_from_file(fallback_current=True)
        region = self._user_point_region()
        for point in self.user_points:
            if not self._point_in_region(point["lon"], point["lat"], region):
                continue
            key = self._point_cache_key(point["lon"], point["lat"])
            if key not in self._point_depth_cache and self.file:
                queried = -self.query_depth_at_point(self.file, point["lon"], point["lat"])
                queried = -grid_z_to_depth_m([queried])[0]
                if np.isfinite(queried):
                    self._point_depth_cache[key] = queried
        self.save_state()
        self.refresh_points_text_and_overlay()

    def _sync_user_lines_from_table(self):
        self.user_lines = self._collect_user_lines_from_table()
        write_lines_txt(self.user_lines)
        self.sync_user_lines_from_file(fallback_current=True)
        self.save_state()
        self.refresh_points_text_and_overlay()

    def refresh_points_text_and_overlay(self):
        rows, ok = self.parse_points_rows(self.points.toPlainText())
        self._update_points_display(rows if ok else [])
        self.reload_route_overlay_from_text()

    def parse_points_with_depth(self, text):
        pts = []
        depths = []

        rows, ok = self.parse_points_rows(text)
        if not ok:
            return pts, depths

        for lon, lat, depth in rows:
            pts.append((lon, lat))
            depths.append(depth)

        return pts, depths

    def _get_plan_rows(self):
        rows, ok = self.parse_points_rows(self.points.toPlainText())
        if not ok:
            return []
        return rows

    def _collect_user_points_from_table(self):
        table = self.point_info_dialog.user_points_table
        existing = normalize_user_points(self.user_points)
        collected = []
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            lon_item = table.item(row, 1)
            lat_item = table.item(row, 2)
            name = name_item.text().strip() if name_item else ""
            lon_text = lon_item.text().strip() if lon_item else ""
            lat_text = lat_item.text().strip() if lat_item else ""
            if not name and not lon_text and not lat_text:
                continue
            try:
                lon = float(lon_text)
                lat = float(lat_text)
            except ValueError:
                continue
            base = existing[row] if row < len(existing) else {
                "color": "#ff0000",
                "shape": "circle",
                "label_pos": "右上",
                "font_size": 8,
            }
            collected.append(
                {
                    "lon": lon,
                    "lat": lat,
                    "name": name,
                    "color": base.get("color", "#ff0000"),
                    "shape": base.get("shape", "circle"),
                    "label_pos": base.get("label_pos", "右上"),
                    "font_size": base.get("font_size", 8),
                }
            )
        return normalize_user_points(collected)

    def _collect_user_lines_from_table(self):
        table = self.point_info_dialog.user_lines_table
        lines_by_name = {}
        ordered_names = []
        existing = normalize_user_lines(self.user_lines)
        style_by_name = {}
        for line in existing:
            line_name = line.get("name", "").strip()
            style_by_name[line_name] = {
                "color": line.get("color", DEFAULT_LINE_COLOR),
                "line_style": line.get("line_style", "实线"),
                "font_size": line.get("font_size", 8),
            }
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            lon_item = table.item(row, 1)
            lat_item = table.item(row, 2)
            name = name_item.text().strip() if name_item else ""
            lon_text = lon_item.text().strip() if lon_item else ""
            lat_text = lat_item.text().strip() if lat_item else ""
            if not name and not lon_text and not lat_text:
                continue
            if not name:
                continue
            try:
                lon = float(lon_text)
                lat = float(lat_text)
            except ValueError:
                continue
            if name not in lines_by_name:
                ordered_names.append(name)
                lines_by_name[name] = {
                    "name": name,
                    "color": style_by_name.get(name, {}).get("color", DEFAULT_LINE_COLOR),
                    "line_style": style_by_name.get(name, {}).get("line_style", "实线"),
                    "font_size": style_by_name.get(name, {}).get("font_size", 8),
                    "points": [],
                }
            lines_by_name[name]["points"].append([lon, lat])
        return normalize_user_lines([lines_by_name[name] for name in ordered_names])

    def _point_cache_key(self, lon, lat):
        return (round(float(lon), 6), round(float(lat), 6))

    def _user_point_region(self):
        if self._planning_base_region is not None:
            return self._planning_base_region
        try:
            return self.parse_plan_region()
        except Exception:
            return None

    def _point_in_region(self, lon, lat, region):
        if region is None:
            return True
        lon0, lon1, lat0, lat1 = region
        return lon0 <= lon <= lon1 and lat0 <= lat <= lat1

    def _resolve_rows_depths(self, rows):
        resolved = []
        for lon, lat, depth in rows:
            resolved_depth = depth
            key = self._point_cache_key(lon, lat)
            if np.isfinite(resolved_depth):
                self._point_depth_cache[key] = resolved_depth
            else:
                cached = self._point_depth_cache.get(key, np.nan)
                if np.isfinite(cached):
                    resolved_depth = cached
                elif self.file:
                    queried = -self.query_depth_at_point(self.file, lon, lat)
                    queried = -grid_z_to_depth_m([queried])[0]
                    if np.isfinite(queried):
                        resolved_depth = queried
                        self._point_depth_cache[key] = queried
            resolved.append((lon, lat, resolved_depth))
        return resolved

    def _resolve_user_points_depths(self, user_points):
        resolved = []
        region = self._user_point_region()
        for point in normalize_user_points(user_points):
            lon = float(point["lon"])
            lat = float(point["lat"])
            depth = np.nan
            depth_text = "nan"
            key = self._point_cache_key(lon, lat)
            if not self._point_in_region(lon, lat, region):
                depth_text = "超出底图"
            else:
                cached = self._point_depth_cache.get(key, np.nan)
                if np.isfinite(cached):
                    depth = cached
                elif self.file:
                    queried = -self.query_depth_at_point(self.file, lon, lat)
                    queried = -grid_z_to_depth_m([queried])[0]
                    if np.isfinite(queried):
                        depth = queried
                        self._point_depth_cache[key] = queried
                depth_text = f"{depth:.2f}" if np.isfinite(depth) else "nan"
            resolved.append(
                {
                    "name": str(point.get("name", "")).strip(),
                    "lon": lon,
                    "lat": lat,
                    "depth": depth,
                    "depth_text": depth_text,
                }
            )
        return resolved

    def _sync_point_speeds(self, count):
        default_speed = float(POINTS_SPEED_MPS)
        if len(self._point_speed_values) < count:
            self._point_speed_values.extend([default_speed] * (count - len(self._point_speed_values)))
        elif len(self._point_speed_values) > count:
            self._point_speed_values = self._point_speed_values[:count]

    def sync_user_points_from_file(self, fallback_current=False):
        file_points = load_addpoint_txt()
        if file_points or not fallback_current:
            self.user_points = file_points
        elif not self.user_points:
            self.user_points = []

    def sync_user_lines_from_file(self, fallback_current=False):
        file_lines = load_lines_txt()
        if file_lines or not fallback_current:
            self.user_lines = file_lines
        elif not self.user_lines:
            self.user_lines = []

    def _set_plan_rows(self, rows):
        self.points.blockSignals(True)
        self.points.setPlainText(
            "\n".join(
                f"{lon:.4f} {lat:.4f}"
                for lon, lat, depth in rows
            )
        )
        self.points.blockSignals(False)
        self.refresh_points_text_and_overlay()

    def _compute_route_box(self, pts):
        if not pts:
            return None
        cx, cy = compute_center(pts)
        dx = float(self.dx.text())
        dy = float(self.dy.text())
        return [
            [cx - dx, cy - dy],
            [cx + dx, cy - dy],
            [cx + dx, cy + dy],
            [cx - dx, cy + dy],
            [cx - dx, cy - dy],
        ]

    def _build_segment_labels(self, metrics):
        labels = []
        for metric in metrics[1:]:
            seg_no = int(metric.get("seg_no", len(labels) + 1))
            seg_time_h = metric.get("seg_time_h", np.nan)
            seg_time_text = f"{seg_time_h:.1f}h" if np.isfinite(seg_time_h) else "nanh"
            labels.append(f"S{seg_no}_{seg_time_text}")
        return labels

    def _get_frame_settings(self):
        try:
            lon_tick = float(self.lon_tick.text())
            lat_tick = float(self.lat_tick.text())
        except ValueError:
            raise ValueError("经纬度刻度间隔必须是有效数字")
        if lon_tick <= 0 or lat_tick <= 0:
            raise ValueError("经纬度刻度间隔必须大于 0")
        style = self.frame_style.currentText().strip().lower()
        if style not in {"plain", "fancy"}:
            style = "plain"
        return style, lon_tick, lat_tick

    def _paint_route_overlay_on_image(self, image, pts, region, box=None, segment_labels=None):
        if image.isNull() or region is None:
            return
        lon0, lon1, lat0, lat1 = region
        w = image.width()
        h = image.height()

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        route_pen = QPen(QColor(255, 0, 0))
        route_pen.setWidthF(2.0)
        painter.setPen(route_pen)

        if len(pts) >= 2:
            path = QPainterPath()
            scene_pts = []
            for i, (lon, lat) in enumerate(pts):
                sx, sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
                scene_pts.append((sx, sy))
                if i == 0:
                    path.moveTo(sx, sy)
                else:
                    path.lineTo(sx, sy)
            painter.drawPath(path)

            seg_font = QFont("Helvetica", 8)
            seg_font.setBold(True)
            painter.setFont(seg_font)
            fm = painter.fontMetrics()
            for i in range(1, len(scene_pts)):
                x0, y0 = scene_pts[i - 1]
                x1, y1 = scene_pts[i]
                mx = (x0 + x1) / 2.0
                my = (y0 + y1) / 2.0
                angle_deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
                if angle_deg > 90:
                    angle_deg -= 180
                elif angle_deg < -90:
                    angle_deg += 180
                label = (
                    segment_labels[i - 1]
                    if segment_labels and i - 1 < len(segment_labels)
                    else f"S{i}"
                )
                text_w = fm.horizontalAdvance(label)
                text_h = fm.height()
                painter.save()
                painter.translate(mx, my)
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
            painter.setPen(route_pen)

        if box and len(box) >= 2:
            box_path = QPainterPath()
            for i, (lon, lat) in enumerate(box):
                sx, sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
                if i == 0:
                    box_path.moveTo(sx, sy)
                else:
                    box_path.lineTo(sx, sy)
            painter.drawPath(box_path)

        if pts:
            start_lon, start_lat = pts[0]
            start_sx, start_sy = lonlat_to_scene_xy(start_lon, start_lat, w, h, lon0, lon1, lat0, lat1)
            painter.setPen(QPen(QColor(180, 0, 0)))
            painter.setBrush(QColor(255, 0, 0, 220))
            painter.drawPath(five_point_star_path(start_sx, start_sy))

            painter.setPen(QPen(QColor(200, 0, 0)))
            painter.setBrush(QColor(255, 80, 80, 200))
            for lon, lat in pts[1:]:
                sx, sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
                painter.drawEllipse(QPointF(sx, sy), 4.0, 4.0)

        painter.end()

    def _paint_user_points_on_image(self, image, region, user_points):
        if image.isNull() or region is None or not user_points:
            return
        lon0, lon1, lat0, lat1 = region
        w = image.width()
        h = image.height()

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font_size = max(9, min(16, int(min(w, h) / 70)))
        for point in user_points:
            try:
                lon = float(point["lon"])
                lat = float(point["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (lon0 <= lon <= lon1 and lat0 <= lat <= lat1):
                continue

            sx, sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
            color = QColor(str(point.get("color", "#ff0000")))
            if not color.isValid():
                color = QColor("#ff0000")
            shape = str(point.get("shape", "circle")).lower()

            painter.setPen(QPen(color.darker(150), 1))
            painter.setBrush(QBrush(color))
            if shape == "square":
                painter.drawRect(int(sx - 5), int(sy - 5), 10, 10)
            elif shape == "triangle":
                path = QPainterPath()
                path.moveTo(sx, sy - 6)
                path.lineTo(sx - 5.5, sy + 4.5)
                path.lineTo(sx + 5.5, sy + 4.5)
                path.closeSubpath()
                painter.drawPath(path)
            elif shape == "star":
                painter.drawPath(five_point_star_path(sx, sy, outer_r=7.0, inner_r=3.0))
            else:
                painter.drawEllipse(QPointF(sx, sy), 5.0, 5.0)

            name = str(point.get("name", "")).strip()
            if name:
                point_font_size = max(8, min(24, int(point.get("font_size", 8))))
                painter.setFont(QFont("Helvetica", point_font_size))
                fm = painter.fontMetrics()
                label_pos = str(point.get("label_pos", "右上"))
                text_w = fm.horizontalAdvance(name)
                text_h = fm.height()
                br = fm.boundingRect(name)
                text_x, text_y = self.route_preview._label_anchor_xy(label_pos, sx, sy, br)
                text_x = int(text_x)
                text_y = int(text_y)
                painter.fillRect(text_x - 3, text_y - 2, text_w + 6, text_h + 4, QColor(255, 255, 255, 128))
                painter.setPen(QPen(QColor("black")))
                painter.drawText(text_x, text_y + fm.ascent(), name)

        painter.end()

    def _paint_user_lines_on_image(self, image, region, user_lines):
        if image.isNull() or region is None or not user_lines:
            return
        lon0, lon1, lat0, lat1 = region
        w = image.width()
        h = image.height()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for line in normalize_user_lines(user_lines):
            pts = []
            for lon, lat in line.get("points", []):
                lon = float(lon)
                lat = float(lat)
                if not (lon0 <= lon <= lon1 and lat0 <= lat <= lat1):
                    continue
                pts.append((lon, lat))
            if len(pts) < 2:
                continue
            color = QColor(str(line.get("color", DEFAULT_LINE_COLOR)))
            if not color.isValid():
                color = QColor(DEFAULT_LINE_COLOR)
            pen = QPen(color)
            pen.setWidthF(2.0)
            pen.setStyle(user_line_pen_style(str(line.get("line_style", "实线"))))
            painter.setPen(pen)
            path = QPainterPath()
            for i, (lon, lat) in enumerate(pts):
                sx, sy = lonlat_to_scene_xy(lon, lat, w, h, lon0, lon1, lat0, lat1)
                if i == 0:
                    path.moveTo(sx, sy)
                else:
                    path.lineTo(sx, sy)
            painter.drawPath(path)

            name = str(line.get("name", "")).strip()
            if name:
                start_sx, start_sy = lonlat_to_scene_xy(pts[0][0], pts[0][1], w, h, lon0, lon1, lat0, lat1)
                next_sx, next_sy = lonlat_to_scene_xy(pts[1][0], pts[1][1], w, h, lon0, lon1, lat0, lat1)
                angle_deg = math.degrees(math.atan2(next_sy - start_sy, next_sx - start_sx))
                if angle_deg > 90:
                    angle_deg -= 180
                elif angle_deg < -90:
                    angle_deg += 180
                painter.setFont(QFont("Helvetica", max(8, min(24, int(line.get("font_size", 8))))))
                fm = painter.fontMetrics()
                text_w = fm.horizontalAdvance(name)
                text_h = fm.height()
                label_x = start_sx + 8
                label_y = start_sy - text_h - 6
                center_x = label_x + text_w / 2
                center_y = label_y + text_h / 2
                painter.save()
                painter.translate(center_x, center_y)
                painter.rotate(angle_deg)
                painter.fillRect(
                    int(-text_w / 2 - 3),
                    int(-text_h / 2 - 2),
                    text_w + 6,
                    text_h + 4,
                    QColor(255, 255, 255, 128),
                )
                painter.setPen(QPen(QColor("black")))
                painter.drawText(int(-text_w / 2), int(-text_h / 2 + fm.ascent()), name)
                painter.restore()
        painter.end()

    def _render_export_basemap_with_qt_scalebar(self):
        if not self.file or self._planning_base_region is None:
            return None
        region = list(self._planning_base_region)
        fig = pygmt.Figure()
        fig.grdimage(
            grid=self.file,
            region=region,
            projection="M7i",
            cmap="haxby",
            shading=True,
            frame=False,
        )
        if self.cb_contour.isChecked():
            try:
                cint = float(self.contour.text())
            except ValueError:
                cint = None
            if cint is not None:
                fig.grdcontour(
                    grid=self.file,
                    interval=cint,
                    annotation=cint,
                    pen="0.6p,black",
                )
        tmp_path = "_tmp_export_basemap.png"
        fig.savefig(tmp_path, dpi=200)
        self._decorate_export_scalebar_and_colorbar(tmp_path, region)
        return tmp_path

    def _decorate_export_scalebar_and_colorbar(self, image_path, region):
        image = QImage(image_path)
        if image.isNull():
            return
        lon0, lon1, lat0, lat1 = region
        mid_lat = (lat0 + lat1) / 2.0
        width_m = haversine_distance_m(lon0, mid_lat, lon1, mid_lat)
        depth_min, depth_max = self._grid_depth_range(region)
        tmp_cbar_path = "_tmp_export_colorbar.png"
        render_haxby_colorbar(
            tmp_cbar_path,
            width=560,
            height=92,
            depth_min=depth_min,
            depth_max=depth_max,
            horizontal=True,
            transparent_background=False,
            font_pt=24,
        )
        cbar = QPixmap(tmp_cbar_path)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        target_px = 180
        target_distance_m = width_m * (target_px / max(1.0, image.width()))
        self.route_preview._paint_scalebar(
            painter,
            20,
            image.height() - 22,
            target_distance_m,
            target_px,
            close_painter=False,
        )

        cbar_scaled = cbar.scaledToWidth(
            max(420, int(image.width() * 0.36)),
            Qt.TransformationMode.SmoothTransformation,
        ) if not cbar.isNull() else QPixmap()
        if not cbar_scaled.isNull():
            cbar_x = 230
            cbar_y = image.height() - cbar_scaled.height() + 18
            painter.drawPixmap(cbar_x, cbar_y, cbar_scaled)
        if painter.isActive():
            painter.end()
        image.save(image_path)

    def _render_frame_image(self, image, region, frame_style, lon_step, lat_step):
        if image.isNull() or region is None:
            return image
        lon0, lon1, lat0, lat1 = region
        w = image.width()
        h = image.height()

        font_size = max(14, min(24, int(min(w, h) / 42)))
        font = QFont("Helvetica", font_size)
        fm = QFontMetrics(font)
        lon_ticks = generate_axis_ticks(lon0, lon1, lon_step)
        lat_ticks = generate_axis_ticks(lat0, lat1, lat_step)

        left_margin = max(72, max((fm.horizontalAdvance(format_lat_label(v)) for v in lat_ticks), default=28) + 18)
        right_margin = 42
        top_margin = 18
        bottom_margin = max(72, fm.height() * 2 + 18)
        frame_w = w + left_margin + right_margin
        frame_h = h + top_margin + bottom_margin
        self._last_frame_margins = (left_margin, top_margin, right_margin, bottom_margin)

        framed = QImage(frame_w, frame_h, QImage.Format.Format_ARGB32)
        framed.fill(QColor("white"))
        painter = QPainter(framed)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(font)

        image_x = left_margin
        image_y = top_margin
        painter.drawImage(image_x, image_y, image)

        outer_rect_pen = QPen(QColor("black"))
        outer_rect_pen.setWidth(1)
        painter.setPen(outer_rect_pen)
        painter.drawRect(image_x, image_y, w, h)

        if frame_style == "fancy":
            self._draw_fancy_frame(
                painter, image_x, image_y, w, h, region, lon_ticks, lat_ticks
            )

        tick_len = 8
        painter.setPen(QPen(QColor("black")))
        for lon in lon_ticks:
            sx, _ = lonlat_to_scene_xy(lon, lat0, w, h, lon0, lon1, lat0, lat1)
            x = image_x + sx
            painter.drawLine(QPointF(x, image_y + h), QPointF(x, image_y + h + tick_len))
            painter.drawLine(QPointF(x, image_y), QPointF(x, image_y - tick_len))
            label = format_lon_label(lon)
            text_w = fm.horizontalAdvance(label)
            painter.drawText(int(x - text_w / 2), image_y + h + tick_len + fm.ascent() + 6, label)

        for lat in lat_ticks:
            _, sy = lonlat_to_scene_xy(lon0, lat, w, h, lon0, lon1, lat0, lat1)
            y = image_y + sy
            painter.drawLine(QPointF(image_x - tick_len, y), QPointF(image_x, y))
            painter.drawLine(QPointF(image_x + w, y), QPointF(image_x + w + tick_len, y))
            label = format_lat_label(lat)
            text_w = fm.horizontalAdvance(label)
            painter.drawText(image_x - tick_len - text_w - 6, int(y + fm.ascent() / 2), label)

        painter.end()
        return framed

    def _draw_fancy_frame(self, painter, image_x, image_y, w, h, region, lon_ticks, lat_ticks):
        lon0, lon1, lat0, lat1 = region
        band = 10
        x_positions = [0.0]
        for lon in lon_ticks:
            sx, _ = lonlat_to_scene_xy(lon, lat0, w, h, lon0, lon1, lat0, lat1)
            x_positions.append(float(sx))
        x_positions.append(float(w))
        x_positions = sorted(set(round(v, 6) for v in x_positions))
        for i in range(len(x_positions) - 1):
            x0 = x_positions[i]
            x1 = x_positions[i + 1]
            color = QColor("black") if i % 2 == 0 else QColor("white")
            painter.fillRect(int(image_x + x0), image_y - band, max(1, int(x1 - x0)), band, color)
            painter.fillRect(int(image_x + x0), image_y + h, max(1, int(x1 - x0)), band, color)
            painter.setPen(QPen(QColor("black")))
            painter.drawRect(int(image_x + x0), image_y - band, max(1, int(x1 - x0)), band)
            painter.drawRect(int(image_x + x0), image_y + h, max(1, int(x1 - x0)), band)

        y_positions = [0.0]
        for lat in lat_ticks:
            _, sy = lonlat_to_scene_xy(lon0, lat, w, h, lon0, lon1, lat0, lat1)
            y_positions.append(float(sy))
        y_positions.append(float(h))
        y_positions = sorted(set(round(v, 6) for v in y_positions))
        for i in range(len(y_positions) - 1):
            y0 = y_positions[i]
            y1 = y_positions[i + 1]
            y_top = min(y0, y1)
            height = max(1, int(abs(y1 - y0)))
            color = QColor("black") if i % 2 == 0 else QColor("white")
            painter.fillRect(image_x - band, int(image_y + y_top), band, height, color)
            painter.fillRect(image_x + w, int(image_y + y_top), band, height, color)
            painter.setPen(QPen(QColor("black")))
            painter.drawRect(image_x - band, int(image_y + y_top), band, height)
            painter.drawRect(image_x + w, int(image_y + y_top), band, height)

        corner_colors = [
            (image_x - band, image_y - band, QColor("black")),
            (image_x + w, image_y - band, QColor("white") if (len(x_positions) - 2) % 2 else QColor("black")),
            (image_x - band, image_y + h, QColor("white") if (len(y_positions) - 2) % 2 else QColor("black")),
            (
                image_x + w,
                image_y + h,
                QColor("black") if ((len(x_positions) - 2) + (len(y_positions) - 2)) % 2 == 0 else QColor("white"),
            ),
        ]
        painter.setPen(QPen(QColor("black")))
        for cx, cy, color in corner_colors:
            painter.fillRect(cx, cy, band, band, color)
            painter.drawRect(cx, cy, band, band)

    def _export_route_map_from_basemap(self, pts, box, frame_style, lon_step, lat_step):
        if not self._planning_base_path or self._planning_base_region is None:
            print("❌ 请先生成墨卡托无刻度底图，再导出下潜计划大图")
            return False
        export_base = self._render_export_basemap_with_qt_scalebar() or self._planning_base_path
        image = QImage(export_base)
        if image.isNull():
            print(f"❌ 无法加载底图：{export_base}")
            return False
        rows = self._resolve_rows_depths(self._get_plan_rows())
        self._sync_point_speeds(len(rows))
        segment_labels = None
        if rows:
            metrics = build_points_metrics(
                [(lon, lat) for lon, lat, _ in rows],
                depths=[depth for _, _, depth in rows],
                speed_mps=POINTS_SPEED_MPS,
                speeds_mps=self._point_speed_values,
            )
            segment_labels = self._build_segment_labels(metrics)
        self._paint_route_overlay_on_image(
            image,
            pts,
            self._planning_base_region,
            box=box,
            segment_labels=segment_labels,
        )
        self._paint_user_lines_on_image(image, self._planning_base_region, self.user_lines)
        self._paint_user_points_on_image(image, self._planning_base_region, self.user_points)
        framed = self._render_frame_image(
            image, self._planning_base_region, frame_style, lon_step, lat_step
        )
        if not framed.save(ROUTE_MAP_PNG):
            print(f"❌ 无法保存：{ROUTE_MAP_PNG}")
            return False
        self._last_export_map_rect = (
            self._last_frame_margins[0],
            self._last_frame_margins[1],
            image.width(),
            image.height(),
        )
        return True

    def undo_last_point(self):
        lines = [ln for ln in self.points.toPlainText().splitlines() if ln.strip()]
        if not lines:
            return
        lines.pop()
        self.points.blockSignals(True)
        self.points.setPlainText("\n".join(lines))
        self.points.blockSignals(False)
        self.refresh_points_text_and_overlay()

    def clear_points_track(self):
        self.points.blockSignals(True)
        self.points.setPlainText("")
        self.points.blockSignals(False)
        self.refresh_points_text_and_overlay()

    def show_depth_profile(self):
        """grdtrack 沿航线采样网格，累积大圆距离为横轴，深度为纵轴；导出 PNG 并弹窗。"""
        if not self.file:
            print("❌ 请选择TIF")
            return
        self.refresh_points_text_and_overlay()
        pts, depths_from_text = self.parse_points_with_depth(
            self.points.toPlainText()
        )
        if len(pts) < 2:
            print("❌ 至少需要 2 个航点才能生成深度—距离剖面")
            return
        force_dense = True    
        write_points(pts)
        if all(np.isfinite(depths_from_text)) and not force_dense:
            print("✔ 使用 points 中已有深度")

            lons = np.array([p[0] for p in pts])
            lats = np.array([p[1] for p in pts])
            depth = np.array(depths_from_text)

        else:
            print("✔ 使用 project + grdtrack 生成高密度剖面")

              # ⭐ 1. 加密航线（200m）
            lons, lats = densify_track_with_project(pts, spacing_m=100)

            if len(lons) < 2:
                print("❌ 加密后的点不足")
                return

              # 写入加密点
            with open("dense_points.txt", "w") as f:
                for lon, lat in zip(lons, lats):
                    f.write(f"{lon} {lat}\n")

              # ⭐ 2. grdtrack 取深度
            track = pygmt.grdtrack(points="dense_points.txt", grid=self.file)

            arr = np.asarray(track.to_numpy(), dtype=float)

            if arr.shape[1] < 3:
                print("❌ grdtrack 输出异常")
                return

            lons, lats, zs = arr[:, 0], arr[:, 1], arr[:, 2]

            depth = -grid_z_to_depth_m(zs)  
            # ⭐⭐⭐ 新增：原始点用于红点
            orig_lons = np.array([p[0] for p in pts])
            orig_lats = np.array([p[1] for p in pts])

            orig_track = pygmt.grdtrack(
                points=np.column_stack([orig_lons, orig_lats]),
                grid=self.file
            )

            orig_arr = np.asarray(orig_track.to_numpy(), dtype=float)
            orig_depth = -grid_z_to_depth_m(orig_arr[:, 2])                                    
            # print("✔ 使用 grdtrack 计算深度")

            # write_points(pts)
#             track = pygmt.grdtrack(points="points.txt", grid=self.file)
# 
#             arr = np.asarray(track.to_numpy(), dtype=float)
#             lons, lats, zs = arr[:, 0], arr[:, 1], arr[:, 2]
#             depth = grid_z_to_depth_m(zs)


        # ⭐ dense distance（黑线）
        dense_dist_km = np.zeros(len(lons))
        for i in range(1, len(lons)):
            dense_dist_km[i] = dense_dist_km[i-1] + haversine_distance_m(
                lons[i-1], lats[i-1],
                lons[i], lats[i]
            ) / 1000.0

        # ⭐ 原始点 distance（红点）
        orig_dist_km = np.zeros(len(orig_lons))
        for i in range(1, len(orig_lons)):
            orig_dist_km[i] = orig_dist_km[i-1] + haversine_distance_m(
                orig_lons[i-1], orig_lats[i-1],
                orig_lons[i], orig_lats[i]
            ) / 1000.0
        # ✅ ⭐关键：统一计算距离（必须放在 if/else 外面）
        
        # dist_km = np.zeros(len(lons))
#         for i in range(1, len(lons)):
#             dist_km[i] = dist_km[i-1] + haversine_distance_m(
#                 lons[i-1], lats[i-1], lons[i], lats[i]
#             )/1000.0
#         valid = np.isfinite(dist_km) & np.isfinite(depth)
#         dist_km = dist_km[valid]
#         depth = depth[valid]
        if dense_dist_km.size < 2:
            print("❌ 有效 grdtrack 采样点不足")
            return
        x0, x1 = float(np.min(dense_dist_km)), float(np.max(dense_dist_km))
        dmin, dmax = float(np.min(depth)), float(np.max(depth))
        xr = x1 - x0
        dr = dmax - dmin
        pad_x = max(xr * 0.04, 0.02)
        pad_y = max(dr * 0.08, 1.0)
        if dr < 1e-6:
            dmid = dmin
            dmin, dmax = dmid - 5.0, dmid + 5.0
            dr = dmax - dmin
            pad_y = max(dr * 0.08, 1.0)
        # 横轴不得为负：避免 -R-1.2/... 被 GMT 误解析；须 ymin<ymax（部分版本不接受反转 -R）
        xmin_r = max(0.0, x0 - pad_x)
        xmax_r = x1 + pad_x
        if xmax_r <= xmin_r:
            xmax_r = xmin_r + 0.1
        ymin_r = dmin - pad_y
        ymax_r = dmax + pad_y
        if ymax_r <= ymin_r:
            ymax_r = ymin_r + 1.0
        region = [xmin_r, xmax_r, ymin_r, ymax_r]
        fig = pygmt.Figure()
        pygmt.config(
            FORMAT_FLOAT_OUT="%.3g",
            FONT_LABEL="12p,Helvetica,black",
            FONT_ANNOT_PRIMARY="10p,Helvetica,black",
        )
        fig.basemap(
                region=region,
                projection="X14c/7c",
                frame=[
                        "xafg",
                        'xa+l"Distance(km)"',
                        'yafg+l"Depth(m)"',
                        # "+tWater depth profile",
                ],
        )
#         fig.plot(x=dist_km, y=depth, pen="1.8p,15/70/130")
        fig.plot(
            x=dense_dist_km,
            y=depth,
            pen="2p,black,solid",
        )
        fig.plot(
            x=orig_dist_km,
            y=orig_depth,
            style="c0.12c",
            fill="red",
        )
        fig.savefig(DEPTH_PROFILE_PNG, dpi=220)
        print(f"✔ {DEPTH_PROFILE_PNG} 已生成（grdtrack + 航线累积距离）")
        DepthProfileDialog(DEPTH_PROFILE_PNG, self).exec()

    def select_file(self):
        f, _ = QFileDialog.getOpenFileName(self)
        self.file = f
        self.file_label.setText(f)

    def open_roi(self):
        self.roi = ROIApp(tif_file=self.file)
        self.roi.show()

    def export_current_preview_image(self):
        scene = self.route_preview.scene()
        if scene is None or self.route_preview._pixmap_item is None:
            QMessageBox.information(self, "导出图片", "当前没有可导出的地图预览。")
            return

        filters = "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;BMP 图片 (*.bmp);;TIFF 图片 (*.tif *.tiff)"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出当前图片",
            "route_preview.png",
            filters,
        )
        if not path:
            return

        selected_filter = selected_filter or "PNG 图片 (*.png)"
        suffix_map = {
            "PNG 图片 (*.png)": ".png",
            "JPEG 图片 (*.jpg *.jpeg)": ".jpg",
            "BMP 图片 (*.bmp)": ".bmp",
            "TIFF 图片 (*.tif *.tiff)": ".tif",
        }
        suffix = suffix_map.get(selected_filter, ".png")
        if "." not in path.rsplit("/", 1)[-1]:
            path += suffix

        rect = scene.sceneRect()
        image = QImage(
            int(math.ceil(rect.width())),
            int(math.ceil(rect.height())),
            QImage.Format.Format_ARGB32,
        )
        image.fill(QColor("white"))
        painter = QPainter(image)
        scene.render(painter)
        painter.end()

        if image.save(path):
            print(f"✔ 当前图片已导出：{path}")
        else:
            QMessageBox.warning(self, "导出图片", f"导出失败：{path}")

    def save_state(self):
        self.sync_user_points_from_file(fallback_current=True)
        cfg = {
            "file": self.file_label.text(),
            "xmin": self.xmin.text(),
            "xmax": self.xmax.text(),
            "ymin": self.ymin.text(),
            "ymax": self.ymax.text(),
            "dx": self.dx.text(),
            "dy": self.dy.text(),
            "contour": self.contour.text(),
            "points": self.points.toPlainText(),
            "user_points": self.user_points,
            "user_lines": self.user_lines,
            "point_speeds": self._point_speed_values,
            "frame_style": self.frame_style.currentText(),
            "lon_tick": self.lon_tick.text(),
            "lat_tick": self.lat_tick.text(),
            "show_contour": self.cb_contour.isChecked(),
            "projection_name": self._selected_projection,
        }
        save_config(cfg)

    def run(self):

        if not self.file:
            print("❌ 请选择TIF")
            return

        if self._planning_base_path is None or self._planning_base_region is None:
            print("❌ 请先生成墨卡托无刻度底图，再导出下潜计划大图")
            return

        self._set_plot_mode("final")

        file_user_points = load_addpoint_txt()
        if file_user_points:
            self.user_points = file_user_points

        self.refresh_points_text_and_overlay()

        pts, depths_from_text = self.parse_points_with_depth(
            self.points.toPlainText()
        )

        try:
            frame_style, lon_step, lat_step = self._get_frame_settings()
        except ValueError as e:
            print(f"❌ {e}")
            return

        xmin, xmax, ymin, ymax = self._planning_base_region
        box = self._compute_route_box(pts) if pts else None

        if pts:
            write_points(pts)
        if box:
            write_box(box)
        if not self._export_route_map_from_basemap(pts, box, frame_style, lon_step, lat_step):
            return
        print(f"✔ {ROUTE_MAP_PNG} 已生成")
        if box:
            print("✔ rov_box_points.txt 已生成")
        else:
            print("✔ 当前无航点，已按规划底图直接导出")

        self._show_digitize_decor_overlay = False
        self._show_route_map_preview(ROUTE_MAP_PNG, (xmin, xmax, ymin, ymax))
        self._set_route_planning_available(False)
        self._set_plot_mode("final")
        self.save_state()

    def _show_route_map_preview(self, path, region_tuple=None):
        pix = QPixmap(path)
        if pix.isNull():
            self.route_preview.show_load_error(path)
            return False
        if region_tuple is None:
            try:
                region_tuple = self.parse_plan_region()
            except ValueError:
                region_tuple = None
        map_rect = self._last_export_map_rect if self._plot_mode == "final" else None
        self.route_preview.set_route_pixmap(pix, region_tuple, map_rect=map_rect)
        if self._plot_mode == "interactive" and os.path.isfile(PREVIEW_COLORBAR_PNG):
            self.route_preview.set_colorbar_pixmap(QPixmap(PREVIEW_COLORBAR_PNG))
        else:
            self.route_preview.set_colorbar_pixmap(None)
        self.reload_route_overlay_from_text()
        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec())



# import sys
# import json
# import numpy as np
# import pygmt
# 
# from PySide6.QtWidgets import (
#     QApplication, QWidget, QVBoxLayout,
#     QPushButton, QFileDialog,
#     QLineEdit, QLabel, QTextEdit,
#     QComboBox
# )
# 
# # =========================
# # 配置文件
# # =========================
# CONFIG_FILE = "gmt_last_config.json"
# 
# 
# def load_config():
#     try:
#         with open(CONFIG_FILE, "r") as f:
#             return json.load(f)
#     except:
#         return {}
# 
# 
# def save_config(cfg):
#     with open(CONFIG_FILE, "w") as f:
#         json.dump(cfg, f)
# 
# 
# # =========================
# # 写航点
# # =========================
# def write_points(points):
#     with open("points.txt", "w") as f:
#         for x, y in points:
#             f.write(f"{x} {y}\n")
# 
# 
# # =========================
# # ⭐ 新增：写ROV box四点
# # =========================
# def write_box(box):
#     with open("rov_box_points.txt", "w") as f:
#         for x, y in box:
#             f.write(f"{x} {y}\n")
# 
# 
# # =========================
# # center
# # =========================
# def compute_center(points):
#     arr = np.array(points)
#     return np.mean(arr[:, 0]), np.mean(arr[:, 1])
# 
# 
# # =========================
# # ⭐ 自动刻度函数（核心）
# # =========================
# def nice_tick(span, n=4):
#     raw = span / n
#     if raw == 0:
#         return 1
# 
#     magnitude = 10 ** np.floor(np.log10(raw))
#     residual = raw / magnitude
# 
#     if residual <= 1:
#         tick = 1
#     elif residual <= 2:
#         tick = 2
#     elif residual <= 5:
#         tick = 5
#     else:
#         tick = 10
# 
#     return tick * magnitude
# 
# 
# # =========================
# # GUI
# # =========================
# class App(QWidget):
# 
#     def __init__(self):
#         super().__init__()
# 
#         self.setWindowTitle("ROV GMT 双尺度制图系统")
# 
#         self.cfg = load_config()
#         layout = QVBoxLayout()
# 
#         # ---------------- file ----------------
#         self.file_label = QLabel(self.cfg.get("file", "未选择TIF"))
#         btn_file = QPushButton("选择TIF")
#         btn_file.clicked.connect(self.select_file)
# 
#         # ---------------- region ----------------
#         self.xmin = QLineEdit(str(self.cfg.get("xmin", 40)))
#         self.xmax = QLineEdit(str(self.cfg.get("xmax", 140)))
#         self.ymin = QLineEdit(str(self.cfg.get("ymin", 80)))
#         self.ymax = QLineEdit(str(self.cfg.get("ymax", 88)))
# 
#         # ---------------- dx dy ----------------
#         self.dx = QLineEdit(str(self.cfg.get("dx", 0.01)))
#         self.dy = QLineEdit(str(self.cfg.get("dy", 0.01)))
# 
#         # ---------------- contour ----------------
#         self.contour = QLineEdit(str(self.cfg.get("contour", 100)))
# 
#         # ---------------- points ----------------
#         self.points = QTextEdit()
#         self.points.setPlaceholderText("经度 纬度（每行一个）")
# 
#         if "points" in self.cfg:
#             self.points.setText(self.cfg["points"])
# 
#         # ---------------- run ----------------
#         btn = QPushButton("生成地图")
#         btn.clicked.connect(self.run)
# 
#         # ---------------- layout ----------------
#         layout.addWidget(self.file_label)
#         layout.addWidget(btn_file)
# 
#         layout.addWidget(QLabel("xmin"))
#         layout.addWidget(self.xmin)
#         layout.addWidget(QLabel("xmax"))
#         layout.addWidget(self.xmax)
#         layout.addWidget(QLabel("ymin"))
#         layout.addWidget(self.ymin)
#         layout.addWidget(QLabel("ymax"))
#         layout.addWidget(self.ymax)
# 
#         layout.addWidget(QLabel("ROV dx / dy"))
#         layout.addWidget(self.dx)
#         layout.addWidget(self.dy)
# 
#         layout.addWidget(QLabel("等值线间距"))
#         layout.addWidget(self.contour)
# 
#         layout.addWidget(QLabel("航点"))
#         layout.addWidget(self.points)
# 
#         layout.addWidget(btn)
# 
#         self.setLayout(layout)
# 
#         self.file = self.cfg.get("file", None)
# 
#     # ================= file =================
#     def select_file(self):
#         f, _ = QFileDialog.getOpenFileName(self)
#         self.file = f
#         self.file_label.setText(f)
# 
#     # ================= save =================
#     def save_state(self, pts):
#         cfg = {
#             "file": self.file_label.text(),
#             "xmin": self.xmin.text(),
#             "xmax": self.xmax.text(),
#             "ymin": self.ymin.text(),
#             "ymax": self.ymax.text(),
#             "dx": self.dx.text(),
#             "dy": self.dy.text(),
#             "contour": self.contour.text(),
#             "points": self.points.toPlainText()
#         }
#         save_config(cfg)
# 
#     # ================= run =================
#     def run(self):
# 
#         if not self.file:
#             print("❌ 请选择TIF")
#             return
# 
#         # =========================
#         # 航点解析
#         # =========================
#         pts = []
#         for line in self.points.toPlainText().split("\n"):
#             try:
#                 x, y = map(float, line.split())
#                 pts.append((x, y))
#             except:
#                 pass
# 
#         if len(pts) == 0:
#             print("❌ 无航点")
#             return
# 
#         write_points(pts)
# 
#         # =========================
#         # region
#         # =========================
#         xmin = float(self.xmin.text())
#         xmax = float(self.xmax.text())
#         ymin = float(self.ymin.text())
#         ymax = float(self.ymax.text())
# 
#         region = [xmin, xmax, ymin, ymax]
# 
#         # =========================
#         # ⭐ 自动刻度（核心）
#         # =========================
#         x_tick = nice_tick(xmax - xmin)
#         y_tick = nice_tick(ymax - ymin)
# 
#         # =========================
#         # figure
#         # =========================
#         fig = pygmt.Figure()
# 
#         pygmt.config(
#             MAP_FRAME_PEN="1p,black",
#             FORMAT_GEO_MAP="ddd.xxxxF"
#         )
# 
#         # =========================
#         # 地形
#         # =========================
#         fig.grdimage(
#             grid=self.file,
#             region=region,
#             projection="M7i",
#             cmap="haxby",
#             shading=True
#         )
# 
#         # =========================
#         # ⭐ 坐标轴
#         # =========================
#         fig.basemap(
#             frame=[
#                 f"xafg{x_tick}",
#                 f"yafg{y_tick}",
#                 "WSen"
#             ]
#         )
# 
#         # =========================
#         # 等值线
#         # =========================
#         fig.grdcontour(
#             grid=self.file,
#             interval=float(self.contour.text()),
#             annotation=float(self.contour.text()),
#             pen="0.6p,black"
#         )
# 
#         # =========================
#         # 航迹
#         # =========================
#         fig.plot("points.txt", pen="2p,red")
# 
#         # =========================
#         # ⭐ 下潜点
#         # =========================
#         sx, sy = pts[0]
#         fig.plot(
#             x=[sx],
#             y=[sy],
#             style="a0.45c",
#             fill="red",
#             pen="1p,red"
#         )
# 
#         # =========================
#         # ROV box
#         # =========================
#         cx, cy = compute_center(pts)
# 
#         dx = float(self.dx.text())
#         dy = float(self.dy.text())
# 
#         box = [
#             [cx - dx, cy - dy],
#             [cx + dx, cy - dy],
#             [cx + dx, cy + dy],
#             [cx - dx, cy + dy],
#             [cx - dx, cy - dy]
#         ]
# 
#         fig.plot(data=box, pen="2p,red")
# 
#         # =========================
#         # ⭐ 新增：输出ROV四点坐标
#         # =========================
#         write_box(box)
# 
#         # =========================
#         # 输出
#         # =========================
#         fig.savefig("route_map.png", dpi=300)
#         print("✔ route_map.png 已生成")
#         print("✔ rov_box_points.txt 已生成")
# 
#         self.save_state(pts)
# 
# 
# # =========================
# # main
# # =========================
# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     w = App()
#     w.show()
#     sys.exit(app.exec())

# import sys
# import json
# import numpy as np
# import pygmt
# 
# from PySide6.QtWidgets import (
#     QApplication, QWidget, QVBoxLayout,
#     QPushButton, QFileDialog,
#     QLineEdit, QLabel, QTextEdit,
#     QComboBox
# )
# 
# # =========================
# # 配置文件
# # =========================
# CONFIG_FILE = "gmt_last_config.json"
# 
# 
# def load_config():
#     try:
#         with open(CONFIG_FILE, "r") as f:
#             return json.load(f)
#     except:
#         return {}
# 
# 
# def save_config(cfg):
#     with open(CONFIG_FILE, "w") as f:
#         json.dump(cfg, f)
# 
# 
# # =========================
# # 写航点
# # =========================
# def write_points(points):
#     with open("points.txt", "w") as f:
#         for x, y in points:
#             f.write(f"{x} {y}\n")
# 
# 
# # =========================
# # center
# # =========================
# def compute_center(points):
#     arr = np.array(points)
#     return np.mean(arr[:, 0]), np.mean(arr[:, 1])
# 
# 
# # =========================
# # ⭐ 自动刻度函数（核心）
# # =========================
# def nice_tick(span, n=4):
#     raw = span / n
#     if raw == 0:
#         return 1
# 
#     magnitude = 10 ** np.floor(np.log10(raw))
#     residual = raw / magnitude
# 
#     if residual <= 1:
#         tick = 1
#     elif residual <= 2:
#         tick = 2
#     elif residual <= 5:
#         tick = 5
#     else:
#         tick = 10
# 
#     return tick * magnitude
# 
# 
# # =========================
# # GUI
# # =========================
# class App(QWidget):
# 
#     def __init__(self):
#         super().__init__()
# 
#         self.setWindowTitle("ROV GMT 双尺度制图系统")
# 
#         self.cfg = load_config()
#         layout = QVBoxLayout()
# 
#         # ---------------- file ----------------
#         self.file_label = QLabel(self.cfg.get("file", "未选择TIF"))
#         btn_file = QPushButton("选择TIF")
#         btn_file.clicked.connect(self.select_file)
# 
#         # ---------------- region ----------------
#         self.xmin = QLineEdit(str(self.cfg.get("xmin", 40)))
#         self.xmax = QLineEdit(str(self.cfg.get("xmax", 140)))
#         self.ymin = QLineEdit(str(self.cfg.get("ymin", 80)))
#         self.ymax = QLineEdit(str(self.cfg.get("ymax", 88)))
# 
#         # ---------------- dx dy ----------------
#         self.dx = QLineEdit(str(self.cfg.get("dx", 0.01)))
#         self.dy = QLineEdit(str(self.cfg.get("dy", 0.01)))
# 
#         # ---------------- contour ----------------
#         self.contour = QLineEdit(str(self.cfg.get("contour", 100)))
# 
#         # ---------------- points ----------------
#         self.points = QTextEdit()
#         self.points.setPlaceholderText("经度 纬度（每行一个）")
# 
#         if "points" in self.cfg:
#             self.points.setText(self.cfg["points"])
# 
#         # ---------------- run ----------------
#         btn = QPushButton("生成地图")
#         btn.clicked.connect(self.run)
# 
#         # ---------------- layout ----------------
#         layout.addWidget(self.file_label)
#         layout.addWidget(btn_file)
# 
#         layout.addWidget(QLabel("xmin"))
#         layout.addWidget(self.xmin)
#         layout.addWidget(QLabel("xmax"))
#         layout.addWidget(self.xmax)
#         layout.addWidget(QLabel("ymin"))
#         layout.addWidget(self.ymin)
#         layout.addWidget(QLabel("ymax"))
#         layout.addWidget(self.ymax)
# 
#         layout.addWidget(QLabel("ROV dx / dy"))
#         layout.addWidget(self.dx)
#         layout.addWidget(self.dy)
# 
#         layout.addWidget(QLabel("等值线间距"))
#         layout.addWidget(self.contour)
# 
#         layout.addWidget(QLabel("航点"))
#         layout.addWidget(self.points)
# 
#         layout.addWidget(btn)
# 
#         self.setLayout(layout)
# 
#         self.file = self.cfg.get("file", None)
# 
#     # ================= file =================
#     def select_file(self):
#         f, _ = QFileDialog.getOpenFileName(self)
#         self.file = f
#         self.file_label.setText(f)
# 
#     # ================= save =================
#     def save_state(self, pts):
#         cfg = {
#             "file": self.file_label.text(),
#             "xmin": self.xmin.text(),
#             "xmax": self.xmax.text(),
#             "ymin": self.ymin.text(),
#             "ymax": self.ymax.text(),
#             "dx": self.dx.text(),
#             "dy": self.dy.text(),
#             "contour": self.contour.text(),
#             "points": self.points.toPlainText()
#         }
#         save_config(cfg)
# 
#     # ================= run =================
#     def run(self):
# 
#         if not self.file:
#             print("❌ 请选择TIF")
#             return
# 
#         # =========================
#         # 航点解析
#         # =========================
#         pts = []
#         for line in self.points.toPlainText().split("\n"):
#             try:
#                 x, y = map(float, line.split())
#                 pts.append((x, y))
#             except:
#                 pass
# 
#         if len(pts) == 0:
#             print("❌ 无航点")
#             return
# 
#         write_points(pts)
# 
#         # =========================
#         # region
#         # =========================
#         xmin = float(self.xmin.text())
#         xmax = float(self.xmax.text())
#         ymin = float(self.ymin.text())
#         ymax = float(self.ymax.text())
# 
#         region = [xmin, xmax, ymin, ymax]
# 
#         # =========================
#         # ⭐ 自动刻度（核心）
#         # =========================
#         x_tick = nice_tick(xmax - xmin)
#         y_tick = nice_tick(ymax - ymin)
# 
#         # =========================
#         # figure
#         # =========================
#         fig = pygmt.Figure()
# 
#         pygmt.config(
#             MAP_FRAME_PEN="1p,black",
#             FORMAT_GEO_MAP="ddd.xxxxF"
#         )
# 
#         # =========================
#         # 地形
#         # =========================
#         fig.grdimage(
#             grid=self.file,
#             region=region,
#             projection="M7i",
#             cmap="haxby",
#             shading=True
#         )
# 
#         # =========================
#         # ⭐ 坐标轴（自动对齐刻度）
#         # =========================
#         fig.basemap(
#             frame=[
#                 f"xafg{x_tick}",
#                 f"yafg{y_tick}",
#                 "WSen"
#             ]
#         )
# 
#         # =========================
#         # 等值线
#         # =========================
#         fig.grdcontour(
#             grid=self.file,
#             interval=float(self.contour.text()),
#             annotation=float(self.contour.text()),
#             pen="0.6p,black"
#         )
# 
#         # =========================
#         # 航迹
#         # =========================
#         fig.plot("points.txt", pen="2p,red")
# 
#         # =========================
#         # ⭐ 下潜点（第一个点）
#         # =========================
#         sx, sy = pts[0]
#         fig.plot(
#             x=[sx],
#             y=[sy],
#             style="a0.45c",
#             fill="red",
#             pen="1p,red"
#         )
# 
#         # =========================
#         # ROV box
#         # =========================
#         cx, cy = compute_center(pts)
# 
#         dx = float(self.dx.text())
#         dy = float(self.dy.text())
# 
#         box = [
#             [cx - dx, cy - dy],
#             [cx + dx, cy - dy],
#             [cx + dx, cy + dy],
#             [cx - dx, cy + dy],
#             [cx - dx, cy - dy]
#         ]
# 
#         fig.plot(data=box, pen="2p,red")
# 
#         # =========================
#         # 输出
#         # =========================
#         fig.savefig("route_map.png", dpi=300)
#         print("✔ route_map.png 已生成")
# 
#         self.save_state(pts)
# 
# 
# # =========================
# # main
# # =========================
# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     w = App()
#     w.show()
#     sys.exit(app.exec())





# import streamlit as st
# import pygmt
# import tempfile
# import os
# 
# # =========================
# # GMT绘图函数
# # =========================
# def make_map(tif_file, region, points, out_png):
# 
#     fig = pygmt.Figure()
# 
#     pygmt.config(
#         FONT_LABEL="13p,Times-Roman,black",
#         MAP_FRAME_PEN="1p,black",
#         COLOR_NAN="255"
#     )
# 
#     # 底图（haxby）
#     fig.grdimage(
#         grid=tif_file,
#         region=region,
#         projection="M12c",
#         cmap="haxby",
#         shading=True
#     )
# 
#     # 海岸线（可选）
#     fig.coast(
#         resolution="i",
#         borders="1/0.5p,black",
#         area_thresh=200
#     )
# 
#     # 写航点文件
#     tmp_file = "points.txt"
#     with open(tmp_file, "w") as f:
#         for lon, lat in points:
#             f.write(f"{lon} {lat}\n")
# 
#     # =========================
#     # 五角星点（你指定）
#     # =========================
#     fig.plot(
#         data=tmp_file,
#         style="a0.15c",
#         color="red",
#         pen="thinnest,white"
#     )
# 
#     # 灰色小圆点
#     fig.plot(
#         data=tmp_file,
#         style="c0.10c",
#         color="grey",
#         pen="thinnest,white"
#     )
# 
#     # 黑色小点（备用样式）
#     fig.plot(
#         data=tmp_file,
#         style="c0.09c",
#         color="black",
#         pen="thinnest,white"
#     )
# 
#     # 航线
#     fig.plot(
#         data=tmp_file,
#         pen="2p,black"
#     )
# 
#     fig.savefig(out_png, dpi=300)
# 
# 
# # =========================
# # Streamlit UI
# # =========================
# st.title("ROV 路径规划系统（GMT版）")
# 
# # ===== 文件 =====
# uploaded_file = st.file_uploader("上传 TIF/GRD 文件")
# 
# # ===== 范围输入 =====
# st.subheader("地图范围")
# 
# col1, col2, col3, col4 = st.columns(4)
# 
# xmin = col1.number_input("xmin", value=40.0)
# xmax = col2.number_input("xmax", value=140.0)
# ymin = col3.number_input("ymin", value=80.5)
# ymax = col4.number_input("ymax", value=88.5)
# 
# # ===== 航点输入 =====
# st.subheader("航点输入（每行：经度 纬度）")
# 
# points_text = st.text_area(
#     "points",
#     value="120.1 85.3\n120.2 85.4\n120.3 85.5",
#     height=150
# )
# 
# # ===== 按钮 =====
# if st.button("生成地图"):
# 
#     if uploaded_file is None:
#         st.error("请先上传TIF/GRD文件")
#         st.stop()
# 
#     # 保存临时文件
#     tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".tif")
#     tfile.write(uploaded_file.read())
#     tfile.close()
# 
#     region = [xmin, xmax, ymin, ymax]
# 
#     # 解析航点
#     points = []
#     for line in points_text.split("\n"):
#         try:
#             lon, lat = map(float, line.split())
#             points.append((lon, lat))
#         except:
#             continue
# 
#     out_png = "rov_map.png"
# 
#     make_map(tfile.name, region, points, out_png)
# 
#     st.success("生成完成")
# 
#     st.image(out_png)



# import pygmt
# 
# # =========================
# # 1. 画底图 + 点 + 线
# # =========================
# def make_map(tif_file, region, points, out_png):
# 
#     fig = pygmt.Figure()
# 
#     pygmt.config(
#         FONT_LABEL="13p,Times-Roman,black",
#         MAP_FRAME_PEN="1p,black",
#         COLOR_NAN="255"
#     )
# 
#     # ===== 底图 =====
#     fig.basemap(
#         region=region,
#         projection="M12c",
#         frame=["WSen", "xa20f20", "ya2f2"]
#     )
# 
#     fig.grdimage(
#         grid=tif_file,
#         cmap="haxby",
#         shading=True
#     )
# 
#     fig.coast(
#         resolution="i",
#         area_thresh=200,
#         borders="1/0.5p,black"
#     )
# 
#     # =========================
#     # 2. 写入航点文件
#     # =========================
#     with open("points.txt", "w") as f:
#         for p in points:
#             f.write(f"{p[0]} {p[1]}\n")
# 
#     # =========================
#     # 3. 画航点（五角星/圆点）
#     # =========================
# 
#     # 五角星（你指定）
#     fig.plot(
#         data="points.txt",
#         style="a0.15c",     # 五角星
#         color="red",
#         pen="thin,white"
#     )
# 
#     # 备用：灰点（可选）
#     fig.plot(
#         data="points.txt",
#         style="c0.10c",
#         color="grey",
#         pen="thin,white"
#     )
# 
#     # =========================
#     # 4. 连线（航线）
#     # =========================
#     fig.plot(
#         data="points.txt",
#         pen="2p,black"
#     )
# 
#     fig.savefig(out_png, dpi=300)
#     print("地图生成完成:", out_png)
# 
# 
# # =========================
# # 2. 主程序（手动输入）
# # =========================
# if __name__ == "__main__":
# 
#     tif_file = "temp.tif"   # 你裁剪后的数据
# 
#     # 范围（墨卡托）
#     region = [40, 140, 80.5, 88.5]
# 
#     print("\n请输入航点（经度 纬度），输入 done 结束\n")
# 
#     points = []
#     while True:
#         s = input("point: ")
#         if s.strip() == "done":
#             break
# 
#         try:
#             lon, lat = map(float, s.split())
#             points.append((lon, lat))
#         except:
#             print("格式错误，应为：lon lat")
# 
#     # 生成图
#     make_map(tif_file, region, points, "rov_map.png")
