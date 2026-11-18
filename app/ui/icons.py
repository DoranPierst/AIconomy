"""Procedural vector icons (Lucide-style) rendered via QPainter for crisp HiDPI display without emojis."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _make_canvas(size: int = 16, dpr: float = 2.0) -> tuple[QPixmap, QPainter]:
    px = int(size * dpr)
    pix = QPixmap(px, px)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pix, p


def _stroke_pen(color: str, width: float = 1.6) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def icon_color(is_light: bool, muted: bool = False) -> str:
    if muted:
        return "#64748b" if is_light else "#94a3b8"
    return "#1e293b" if is_light else "#e2e8f0"


def make_icon(name: str, color: str = "#e2e8f0", size: int = 16) -> QIcon:
    """Return a crisp monochrome vector QIcon drawn on a 16x16 coordinate grid."""
    pix, p = _make_canvas(size)
    scale = size / 16.0
    p.scale(scale, scale)
    p.setPen(_stroke_pen(color, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "gear":
        cx, cy = 8.0, 8.0
        p.drawEllipse(QPointF(cx, cy), 2.3, 2.3)
        path = QPainterPath()
        teeth = 8
        r_out, r_in = 6.3, 4.7
        for i in range(teeth * 2):
            ang = math.radians(i * (360.0 / (teeth * 2)) - 90.0)
            r = r_out if i % 2 == 0 else r_in
            pt = QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "sliders":
        for y, knob_x in ((4.0, 5.5), (8.0, 10.5), (12.0, 6.5)):
            p.drawLine(QPointF(2.5, y), QPointF(knob_x - 1.5, y))
            p.drawLine(QPointF(knob_x + 1.5, y), QPointF(13.5, y))
            p.drawEllipse(QPointF(knob_x, y), 1.5, 1.5)

    elif name == "activity":
        path = QPainterPath()
        path.moveTo(1.8, 8.5)
        path.lineTo(4.5, 8.5)
        path.lineTo(6.3, 3.5)
        path.lineTo(9.5, 12.5)
        path.lineTo(11.4, 8.5)
        path.lineTo(14.2, 8.5)
        p.drawPath(path)

    elif name == "more":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        for x in (3.5, 8.0, 12.5):
            p.drawEllipse(QPointF(x, 8.0), 1.25, 1.25)

    elif name == "refresh":
        p.drawArc(QRectF(2.8, 2.8, 10.4, 10.4), 35 * 16, 290 * 16)
        p.drawLine(QPointF(11.8, 2.6), QPointF(13.3, 5.2))
        p.drawLine(QPointF(13.3, 5.2), QPointF(10.4, 5.5))

    elif name == "plus":
        p.drawLine(QPointF(8.0, 3.0), QPointF(8.0, 13.0))
        p.drawLine(QPointF(3.0, 8.0), QPointF(13.0, 8.0))

    elif name == "info":
        p.drawEllipse(QRectF(2.2, 2.2, 11.6, 11.6))
        p.drawLine(QPointF(8.0, 7.2), QPointF(8.0, 11.2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(8.0, 5.0), 0.9, 0.9)

    elif name == "key":
        p.drawEllipse(QRectF(2.2, 5.2, 5.2, 5.2))
        p.drawLine(QPointF(7.4, 7.8), QPointF(13.8, 7.8))
        p.drawLine(QPointF(11.5, 7.8), QPointF(11.5, 10.2))
        p.drawLine(QPointF(13.6, 7.8), QPointF(13.6, 10.0))

    elif name == "folder":
        path = QPainterPath()
        path.moveTo(2.2, 4.2)
        path.lineTo(6.2, 4.2)
        path.lineTo(7.6, 5.8)
        path.lineTo(13.8, 5.8)
        path.lineTo(13.8, 12.6)
        path.lineTo(2.2, 12.6)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "download":
        p.drawLine(QPointF(8.0, 2.5), QPointF(8.0, 10.2))
        p.drawLine(QPointF(5.2, 7.6), QPointF(8.0, 10.5))
        p.drawLine(QPointF(10.8, 7.6), QPointF(8.0, 10.5))
        p.drawLine(QPointF(2.8, 12.8), QPointF(13.2, 12.8))

    elif name == "trash":
        p.drawLine(QPointF(3.0, 4.5), QPointF(13.0, 4.5))
        p.drawLine(QPointF(6.2, 2.8), QPointF(9.8, 2.8))
        p.drawRect(QRectF(4.4, 4.5, 7.2, 8.6))

    elif name == "copy":
        p.drawRoundedRect(QRectF(5.2, 5.2, 8.2, 8.6), 1.4, 1.4)
        path = QPainterPath()
        path.moveTo(5.0, 10.6)
        path.lineTo(3.4, 10.6)
        path.lineTo(3.4, 2.8)
        path.lineTo(10.6, 2.8)
        path.lineTo(10.6, 4.6)
        p.drawPath(path)

    elif name == "search":
        p.drawEllipse(QRectF(2.5, 2.5, 8.2, 8.2))
        p.drawLine(QPointF(9.6, 9.6), QPointF(13.6, 13.6))

    elif name == "external":
        p.drawLine(QPointF(7.5, 8.5), QPointF(13.2, 2.8))
        p.drawLine(QPointF(9.4, 2.8), QPointF(13.2, 2.8))
        p.drawLine(QPointF(13.2, 2.8), QPointF(13.2, 6.6))
        path = QPainterPath()
        path.moveTo(11.5, 9.0)
        path.lineTo(11.5, 13.2)
        path.lineTo(2.8, 13.2)
        path.lineTo(2.8, 4.5)
        path.lineTo(7.0, 4.5)
        p.drawPath(path)

    elif name == "check":
        p.drawLine(QPointF(3.0, 8.2), QPointF(6.5, 11.8))
        p.drawLine(QPointF(6.5, 11.8), QPointF(13.2, 4.4))

    elif name == "play":
        path = QPainterPath()
        path.moveTo(4.4, 3.0)
        path.lineTo(13.0, 8.0)
        path.lineTo(4.4, 13.0)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "x":
        p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
        p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))

    p.end()
    return QIcon(pix)


def make_status_dot_pixmap(color: str, size: int = 8) -> QPixmap:
    """Render a crisp anti-aliased status dot pixmap."""
    pix, p = _make_canvas(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1.0, 1.0, size - 2.0, size - 2.0))
    p.end()
    return pix
