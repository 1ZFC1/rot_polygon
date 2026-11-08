"""rot_polygon 的单元测试：几何、结构、追加不破坏原谱面。"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
TOOLS = TOOL.parent
LIB = TOOLS / "rizChartFunction_Library" / "src"
sys.path.insert(0, str(TOOL))
if LIB.exists():
    sys.path.insert(0, str(LIB))

import rot_polygon as rp  # noqa: E402

try:
    import rizChartFunction as rcf  # noqa: E402
    from rizChartFunction import query  # noqa: E402

    HAVE_LIB = True
except Exception:  # pragma: no cover
    HAVE_LIB = False


class ShapeTest(unittest.TestCase):
    def test_regular_polygon_side(self):
        shape = rp.build_shape(6, 2.0, None, None, None)
        self.assertAlmostEqual(shape.side_length, 2.0)
        self.assertAlmostEqual(shape.radius, 2.0)   # 正六边形 R == 边长

    def test_rectangle_angles_not_even(self):
        shape = rp.build_shape(4, None, 3.0, 2.0, None)
        self.assertAlmostEqual(shape.radius, math.hypot(1.5, 1.0))
        self.assertEqual(shape.edge_lengths, [3.0, 2.0, 3.0, 2.0])
        step = shape.angles[1] - shape.angles[0]
        self.assertAlmostEqual(math.degrees(step), 180.0 - math.degrees(2 * math.atan2(1.0, 1.5)))
        self.assertNotAlmostEqual(math.degrees(step), 90.0, places=3)

    def test_parse_colors(self):
        self.assertEqual(rp.parse_color("#f00"), (255, 0, 0))
        self.assertEqual(rp.parse_color("#FF0000"), (255, 0, 0))
        self.assertEqual(rp.parse_color("10, 20, 30"), (10, 20, 30))
        self.assertEqual(rp.parse_palette("#ff0000,#00ff00"),
                         [(255, 0, 0), (0, 255, 0)])
        self.assertEqual(rp.parse_palette("255,0,0; 0,255,0"),
                         [(255, 0, 0), (0, 255, 0)])
        with self.assertRaises(ValueError):
            rp.parse_color("#12345")

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            rp.build_shape(2, 1.0, None, None, None)
        with self.assertRaises(ValueError):
            rp.build_shape(4, None, 0.0, 2.0, None)


class TickTest(unittest.TestCase):
    def test_tick_samples_inclusive(self):
        options = rp.Options(shape=rp.build_shape(4, 3.0, None, None, None),
                             start=8.0, end=92.0, step=0.5)
        ticks = rp.tick_samples(options)
        self.assertEqual((ticks[0], ticks[-1]), (8.0, 92.0))
        self.assertEqual(len(ticks), 169)


@unittest.skipUnless(HAVE_LIB, "需要 rizChartFunction_Library")
class StepTest(unittest.TestCase):
    def test_step_controls_density(self):
        coarse = rp.Options(shape=rp.build_shape(4, 2.0, None, None, None),
                            start=8.0, end=92.0, step=1.0)
        fine = rp.Options(shape=rp.build_shape(4, 2.0, None, None, None),
                          start=8.0, end=92.0, step=0.1)
        self.assertGreater(rp.effective_step(coarse), rp.effective_step(fine))
        self.assertGreater(len(rp.tick_samples(fine)), len(rp.tick_samples(coarse)))


class GeneratedChartTest(unittest.TestCase):
    def _build(self, **kwargs):
        kwargs.setdefault("step", 0.5)
        options = rp.Options(shape=kwargs.pop("shape", rp.build_shape(4, 3.0, None, None, None)),
                             **kwargs)
        chart, base, _ = rp.make_chart(options)
        return chart, options, base

    def _save(self, chart):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "out.json"
        self.assertTrue(rcf.export(chart, str(path)))
        return path, json.loads(path.read_text(encoding="utf-8"))

    def _anchors(self, chart, base):
        anchors = {}
        for line in chart["lines"]:
            nodes = line["linePoints"]
            if len(nodes) == 2 and nodes[0]["canvasIndex"] == nodes[1]["canvasIndex"]:
                anchors.setdefault(nodes[0]["canvasIndex"], nodes[0]["time"])
        return anchors

    def _points(self, chart, tick, options, base):
        """按编辑器模型：y = S1 × (fp(锚点拍) − fp(t))。"""
        s1 = rp.speed_const(options.flow)
        anchors = self._anchors(chart, base)
        pts = []
        for k in range(options.shape.sides):
            canvas = base + k
            x = query.getCanvasPositionAt(chart, tick, index=canvas)
            fp = query.getFloorPosition(chart, tick, canvas)
            fp_anchor = query.getFloorPosition(chart, anchors[canvas], canvas)
            pts.append((x * rp.X_PER_UNIT, (fp_anchor - fp) * s1))
        return pts

    def test_canvases_are_continuous_from_zero(self):
        chart, _, base = self._build()
        self.assertEqual([c["index"] for c in chart["canvasMoves"]],
                         list(range(base + 4)))

    def test_square_geometry_is_exact(self):
        chart, options, base = self._build(start=8.0, end=92.0, step=0.5)
        for tick in (20.0, 40.0, 60.0, 80.0):
            pts = self._points(chart, tick, options, base)
            for k in range(4):
                self.assertAlmostEqual(math.dist(pts[k], pts[(k + 1) % 4]), 3.0, delta=1e-4)
            self.assertAlmostEqual(math.dist(pts[0], pts[2]), 3.0 * math.sqrt(2), delta=1e-4)

    def test_vertical_range(self):
        """y 的振幅应恒等于半径（圆心由 1 流速段决定，所以只校验跨度）。"""
        chart, options, base = self._build(start=8.0, end=92.0, step=0.5)
        ys = [p[1] for tick in rp.tick_samples(options)[1:-1]
              for p in self._points(chart, tick, options, base)]
        self.assertAlmostEqual((max(ys) - min(ys)) / 2.0, options.shape.radius, places=6)

    def test_line_count_and_pinned_points(self):
        chart, options, base = self._build(start=8.0, end=92.0)
        self.assertEqual(len(chart["lines"]), 8)          # 4 顶点 + 4 边
        for line in chart["lines"]:
            for point in line["linePoints"]:
                expected = query.getFloorPosition(chart, point["time"], point["canvasIndex"])
                self.assertAlmostEqual(point["floorPosition"], expected, places=9)
                self.assertEqual(point["xPosition"], 0.0)

    def test_edge_endpoints_carry_vertex_colors(self):
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        chart, options, base = self._build(colors=palette)
        edges = [line for line in chart["lines"]
                 if line["linePoints"][0]["canvasIndex"] != line["linePoints"][1]["canvasIndex"]]
        self.assertEqual(len(edges), 4)
        first = edges[0]["linePoints"]
        self.assertEqual((first[0]["color"]["r"], first[0]["color"]["g"]), (255, 0))
        self.assertEqual((first[1]["color"]["r"], first[1]["color"]["g"]), (0, 255))

    def test_uniform_color(self):
        chart, options, base = self._build(color=(255, 255, 255))
        for line in chart["lines"]:
            for point in line["linePoints"]:
                self.assertEqual(point["color"], {"r": 255, "g": 255, "b": 255, "a": 255})

    def test_export_structure_matches_editor(self):
        chart, _, _ = self._build()
        _, raw = self._save(chart)
        # 与编辑器保存的谱面同构：主题是 colorsList、线节点带 color、无多余派生字段
        self.assertEqual(sorted(raw), sorted(
            ["fileVersion", "chartDelayMs", "themes", "challengeTimes", "bPM", "bpmShifts",
             "lines", "canvasMoves", "cameraMove"]))
        self.assertIn("colorsList", raw["themes"][0])
        self.assertIn("color", raw["lines"][0]["linePoints"][0])

    def test_append_keeps_existing_content(self):
        base_chart = rcf.new(320.0)
        rcf.addLine(base_chart,
                    [{"time": 1.0, "xPosition": 0.0, "canvasIndex": 0, "easeType": 0,
                      "color": {"r": 255, "g": 0, "b": 0, "a": 255}},
                     {"time": 2.0, "xPosition": 0.0, "canvasIndex": 0, "easeType": 0,
                      "color": {"r": 255, "g": 0, "b": 0, "a": 255}}],
                    {"time": 0.0,
                     "startColor": {"r": 255, "g": 0, "b": 0, "a": 255},
                     "endColor": {"r": 255, "g": 0, "b": 0, "a": 255}})
        options = rp.Options(shape=rp.build_shape(4, 2.0, None, None, None))
        merged, base, _ = rp.make_chart(options, existing=base_chart)
        self.assertEqual(base, 1)                       # 原有 1 个画布
        self.assertIn("colorsList", merged["themes"][0])
        self.assertEqual(len(merged["lines"]), 1 + 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
