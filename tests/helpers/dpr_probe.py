import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout

from desktop_intelligence.visualization.charts import ThemedChartCanvas, create_top_apps_chart


def make_fig():
    df = pd.DataFrame({'process_name': ['a.exe', 'b.exe', 'c.exe'], 'active_hours': [0.7, 0.3, 0.1]})
    return create_top_apps_chart(df, theme_mode='dark')


app = QApplication(sys.argv)
card = QFrame()
card.setObjectName('card')
card.setAttribute(Qt.WA_StyledBackground, True)
card.setStyleSheet('QFrame#card { background-color: rgba(24, 31, 48, 0.72); border-radius: 12px; }')
lay = QVBoxLayout(card)
lay.setContentsMargins(12, 12, 12, 12)
canvas = ThemedChartCanvas(make_fig())
lay.addWidget(canvas)
card.resize(1075, 405)
card.show()
app.processEvents()


def probe(tag):
    canvas.draw()
    app.processEvents()
    dpr = canvas.device_pixel_ratio
    fig = canvas.figure
    fw, fh = fig.get_size_inches() * fig.dpi
    img = card.grab().toImage()
    r = img.width() / card.width()
    pad = QColor(img.pixel(int(6 * r), int(card.height() * r / 2))).name()
    cx = int((canvas.x() + canvas.width() - 4) * r)
    cy = int((canvas.y() + canvas.height() - 4) * r)
    return {'tag': tag, 'fill': [fw / (canvas.width() * dpr), fh / (canvas.height() * dpr)],
            'pad': pad, 'corner': QColor(img.pixel(cx, cy)).name()}


steps = [probe('initial')]
canvas.update_figure(make_fig())
steps.append(probe('swap'))
card.resize(1200, 500)
app.processEvents()
steps.append(probe('grow'))
card.resize(700, 300)
app.processEvents()
steps.append(probe('shrink'))
print(json.dumps(steps))
