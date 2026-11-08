#!/usr/bin/env python3
"""生成「旋转多边形」引导线谱面：n 个顶点各占一个画布，边用跨画布线。

全部通过 rizChartFunction_Library 的公开 API 构建并导出（不手写 JSON），
因此输出的结构一定和编辑器保存的谱面一致。

原理
----
顶点钉在画布上：画布自己沿圆运动（x 用 xPositionKeyPoint，y 用流速积分），
顶点只是画布原点上的一个点，边是跨两个画布的一条线段。播放时画布带着点和边走。

    x_k(t) = cx + R·cos(θ(t) + φ_k)
    y_k(t) = cy + R·sin(θ(t) + φ_k)
    θ(t)  = θ0 + 2π·(t − start) / rev            rev = 旋转一圈的拍数

所有顶点共用一个外接圆、相位相差 360°/n，所以任何时刻都是标准正 n 边形；
矩形（宽≠高）的四角在圆上并不等距（相邻圆心角 = 180° − 2·atan(H/W)）。

用法
----
    python rot_polygon.py                       # 交互式
    python rot_polygon.py --sides 6 --side 2.4
    python rot_polygon.py --sides 4 --width 3 --height 2
    python rot_polygon.py --sides 4 --side 3 --into chart.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- 常量

X_PER_UNIT = 5.625
DEFAULT_FLOW = 7.5
DEFAULT_BPM = 320.0
COLORS = [
    (255, 60, 60), (60, 220, 90), (70, 130, 255), (230, 80, 230),
    (255, 200, 60), (60, 220, 220), (255, 140, 60), (170, 120, 255),
]


def speed_const(flow: float) -> float:
    """播放流速 → 真实流速（世界 y = 真实流速 × floorPosition）。"""
    return 7.0 * (float(flow) - 1.0) / 9.0 + 6.0


def _quiet_import(name: str):
    """导入模块，并把导入期间的 stdout/stderr 吞掉。

    谱面库的 advanced_font 依赖 numpy/skimage，本工具用不到、打包时排除了；
    库导入时会打印一条 ModuleNotFoundError，属于噪音，这里屏蔽掉。
    """
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        module = __import__(name)
    return module


def ensure_library() -> None:
    """把 rizChartFunction_Library 加进 sys.path（环境变量优先，其次相邻目录）。

    打包成 exe 时库已经编译进去了，直接 import 即可。
    """
    import os

    if getattr(sys, "frozen", False):
        _quiet_import("rizChartFunction")   # 已随 exe 打包；库会尝试导入 numpy 并打印告警，这里吞掉
        return

    candidates = []
    env = os.environ.get("RIZCHARTFUNCTION_SRC")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent
    candidates += [
        here.parent / "rizChartFunction_Library" / "src",
        here.parent.parent / "rizChartFunction_Library" / "src",
    ]
    for candidate in candidates:
        if (candidate / "rizChartFunction" / "__init__.py").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            _quiet_import("rizChartFunction")
            return
    raise SystemExit(
        "找不到谱面库 rizChartFunction_Library。\n"
        "把它克隆到 tools/ 旁边，或用环境变量指定：\n"
        "  set RIZCHARTFUNCTION_SRC=D:\\path\\rizChartFunction_Library\\src"
    )


# --------------------------------------------------------------------------- 形状

@dataclass
class Shape:
    sides: int
    radius: float
    angles: list[float]
    edge_lengths: list[float]
    label: str = ""

    def angles_shifted(self, phase: float) -> list[float]:
        return [angle + phase for angle in self.angles]

    @property
    def side_length(self) -> float:
        return self.edge_lengths[0]


def build_shape(sides: int, side: float | None, width: float | None,
                height: float | None, radius: float | None) -> Shape:
    if sides < 3:
        raise ValueError("边数至少为 3")
    if sides == 4 and width is not None and height is not None:
        if width <= 0 or height <= 0:
            raise ValueError("宽高必须大于 0")
        half_w, half_h = width / 2.0, height / 2.0
        circ = math.hypot(half_w, half_h)
        base = math.atan2(half_h, half_w)
        angles = [base, math.pi - base, math.pi + base, 2.0 * math.pi - base]
        return Shape(4, circ, angles, [width, height, width, height],
                     f"矩形 {width:g} × {height:g}")
    if radius is not None:
        if radius <= 0:
            raise ValueError("半径必须大于 0")
        angles = [math.pi / 2.0 + i * 2.0 * math.pi / sides for i in range(sides)]
        length = 2.0 * radius * math.sin(math.pi / sides)
        return Shape(sides, float(radius), angles, [length] * sides,
                     f"正 {sides} 边形（外接圆半径 {radius:g}）")
    if side is None:
        side = 2.0 * 2.0 * math.sin(math.pi / sides)   # 默认外接圆半径 2.0
    length = float(side)
    if length <= 0:
        raise ValueError("边长必须大于 0")
    circ = length / (2.0 * math.sin(math.pi / sides))
    angles = [math.pi / 2.0 + i * 2.0 * math.pi / sides for i in range(sides)]
    return Shape(sides, circ, angles, [length] * sides, f"正 {sides} 边形（边长 {length:g}）")


# --------------------------------------------------------------------------- 参数

@dataclass
class Options:
    shape: Shape
    flow: float = DEFAULT_FLOW
    bpm: float = DEFAULT_BPM
    start: float = 8.0
    end: float = 92.0
    rev: float = 0.0            # 转一圈要几拍；0 = 整段转一圈（end − start）
    step: float = 0.5               # 采样间隔（拍）：越小越顺滑，关键点越多
    phase_deg: float = 0.0
    center_x: float = 0.0
    center_y: float = 3.2      # 圆心高度（世界单位；一屏 6.9，默认取约半屏）
    canvas_base: int = 1
    canvas_start: int | None = None  # 追加时从第几个画布开始（None = 接在末尾）
    stagger: float = 0.25           # 相邻顶点错开的拍数（0 = 同一拍，编辑器里不好选）
    hold: float = 0.0              # 画线拍之后再静止几拍（默认 0：错开点本来就在静止段里）
    park: float = 0.0            # 正弦段之后、1 流速段之前的 0 流速长度（tick）
    lift_ticks: float | None = None  # 1 流速段长度；None = 由 center_y 反算
    post_speed: float = 0.0
    post_ticks: float = 0.0
    edges: bool = True
    colors: list | None = None      # 顶点调色板（循环使用）
    color: tuple | None = None      # 统一颜色（覆盖调色板）
    dots: bool = True
    out: Path = Path("rot_polygon_chart.json")
    into: Path | None = None
    extras: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- 生成（全部走库 API）

def effective_step(options: Options) -> float:
    """实际采样间隔（拍）。"""
    return max(1e-4, float(options.step))


def tick_samples(options: Options) -> list[float]:
    span = options.end - options.start
    if span <= 0:
        raise ValueError("end 必须大于 start")
    step = effective_step(options)
    count = int(round(span / step))
    ticks = [options.start + index * step for index in range(count + 1)]
    if abs(ticks[-1] - options.end) > 1e-9:
        ticks.append(options.end)
    return ticks


def parse_color(text: str) -> tuple[int, int, int]:
    """把 ``#rrggbb`` / ``#rgb`` / ``r,g,b`` 解析成 (r, g, b)。"""
    value = str(text).strip()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", digits):
            raise ValueError(f"颜色格式不对：{text}")
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    parts = [part for part in re.split(r"[,，\s]+", value) if part]
    if len(parts) == 3:
        channels = [int(part) for part in parts]
        if all(0 <= c <= 255 for c in channels):
            return tuple(channels)
    raise ValueError(f"颜色格式不对：{text}")


def parse_palette(text: str) -> list:
    """``#a,#b,#c`` 或 ``r,g,b; r,g,b`` → 颜色列表。"""
    if "#" in text:
        items = [item for item in re.split(r"[,，]", text) if item.strip()]
    else:
        items = [item for item in re.split(r"[;；]", text) if item.strip()]
    colors = [parse_color(item) for item in items]
    if not colors:
        raise ValueError("调色板为空")
    return colors


def resolve_colors(options, sides: int) -> list[dict]:
    """按参数给出每个顶点的颜色（统一色 / 调色板循环 / 默认调色板）。"""
    if getattr(options, "color", None):
        return [_rgba(options.color)] * sides
    palette = getattr(options, "colors", None) or COLORS
    return [_rgba(palette[index % len(palette)]) for index in range(sides)]


def _rgba(color) -> dict:
    if isinstance(color, dict):
        return {"r": int(color["r"]), "g": int(color["g"]), "b": int(color["b"]),
                "a": int(color.get("a", 255))}
    return {"r": int(color[0]), "g": int(color[1]), "b": int(color[2]), "a": 255}


def make_chart(options: Options, existing: dict | None = None) -> tuple[dict, int, int]:
    """建谱面：画布曲线 + 顶点 + 边。返回 (chart, base, line_start)。"""
    ensure_library()
    import rizChartFunction as rcf

    if existing is not None:
        chart = existing
        options.bpm = float(chart.get("bPM") or options.bpm)
        current = len(chart.get("canvasMoves", []))
        base = current if options.canvas_start is None else int(options.canvas_start)
        if base < current:
            raise SystemExit(
                f"起始画布 {base} 小于现有画布数 {current}：画布索引必须连续，"
                f"只能接在 {current} 之后（或与其相等）")
        while len(chart["canvasMoves"]) < base:
            rcf.addCanvas(chart)
    else:
        chart = rcf.new(float(options.bpm))
        base = options.canvas_base
        while len(chart["canvasMoves"]) < base:
            rcf.addCanvas(chart)

    shape = options.shape
    s1 = speed_const(options.flow)
    bpm = options.bpm
    ticks = tick_samples(options)
    span = options.end - options.start
    period = options.rev if options.rev and options.rev > 0 else span   # 转一圈的拍数
    omega = 2.0 * math.pi / period
    angles = shape.angles_shifted(math.radians(options.phase_deg))
    seconds_per_tick = 60.0 / bpm
    line_start = len(chart["lines"])

    for k, phi in enumerate(angles):
        while len(chart["canvasMoves"]) <= base + k:
            rcf.addCanvas(chart)
        index = base + k
        # addCanvas 会带一个 t=0 的默认关键点（速度 1 / x 0），先清掉，
        # 否则同一时刻会有两个值不同的关键点，编辑器插值可能取到错的那个。
        chart["canvasMoves"][index]["xPositionKeyPoints"] = []
        chart["canvasMoves"][index]["speedKeyPoints"] = []

        def angle_at(t: float, phi: float = phi) -> float:
            return phi + omega * (t - options.start)

        # ---- 按用户的段落结构铺速度：0 → 正弦一个周期（净 0）→ 0 → 1（抬到画线拍）----
        # 段落边界（tick）
        rot_start = options.start                      # 正弦段开始
        rot_end = options.end                           # 旋转一直持续到结束拍
        park_end = rot_end + options.park              # 第二段 0 结束
        # 可见范围：一屏高 6.9 世界单位，世界 y = S1 × fp；1 流速每秒抬 1 fp，
        # 所以「1 流速段长度」= 想要的圆心高度 / (S1 × 每 tick 秒数)。
        lift_ticks = options.lift_ticks
        if lift_ticks is None:
            lift_ticks = (options.center_y / s1) / seconds_per_tick if options.center_y > 0 else 0.0
        draw_tick = park_end + lift_ticks                # 画线拍

        def fp_of(t: float) -> float:
            """画布的 floorPosition 目标曲线（速度 = 它的导数）。"""
            if t <= rot_start + 1e-9:
                return 0.0
            if t < rot_end - 1e-9:
                return (shape.radius / s1) * math.sin(angle_at(t))
            if t <= park_end + 1e-9:
                return 0.0
            return (min(t, draw_tick) - park_end) * seconds_per_tick

        def x_of(t: float) -> float:
            if t <= rot_start + 1e-9 or t >= rot_end - 1e-9:
                return options.center_x + shape.radius * math.cos(angle_at(
                    rot_start if t <= rot_start else rot_end))
            return options.center_x + shape.radius * math.cos(angle_at(t))



        # ---- x 关键点：统一密集线性（ease 0）----
        # 曾试过「四分点 + ease 17/18」，正方形能精确拟合，但 n≠4 时顶点相位不是 90° 的
        # 整数倍、四分点对不齐窗口边界，各形状会不统一 —— 统一退回线性密集采样。
        def cos_value(theta: float) -> float:
            return options.center_x + shape.radius * math.cos(theta)

        theta_at_start = angle_at(rot_start)
        xs: list[tuple[float, float, int]] = [(0.0, cos_value(theta_at_start), 0),
                                                 (round(rot_start, 6), cos_value(theta_at_start), 0)]
        step_ticks = effective_step(options)
        cursor = rot_start
        while cursor < rot_end - 1e-9:
            cursor = min(rot_end, cursor + step_ticks)
            xs.append((round(cursor, 6), cos_value(angle_at(cursor)), 0))
        xs.append((round(rot_end, 6), cos_value(angle_at(rot_end)), 0))
        xs.append((round(draw_tick, 6), cos_value(angle_at(rot_end)), 0))

        # 采样（速度用）：0、各段边界、正弦段内每 step 一次
        samples = [0.0, rot_start, rot_end, park_end, draw_tick, draw_tick + options.hold]
        step_ticks = effective_step(options)
        cursor = rot_start
        while cursor < rot_end - 1e-9:
            cursor = min(rot_end, cursor + step_ticks)
            samples.append(cursor)
        samples = sorted({round(t, 6) for t in samples if t >= 0})

        written: set[float] = set()
        for t, value, ease in sorted(xs):
            if t in written:
                continue
            written.add(t)
            rcf.addCanvasPosition(chart, index, t, value / X_PER_UNIT, ease)
        # 速度关键点：段内速度恒定，所以取「到下一个采样点的平均速度」保证落点准确；
        # 但旋转起始那一拍直接用「该时刻的旋转流速」，这样第 8 拍一上来就是标准多边形，
        # 不会出现从一条线展开的过程（用户要求）。
        rotation_speed = lambda t: (shape.radius * omega * math.cos(angle_at(t)) / s1) * bpm / 60.0
        for pos, t in enumerate(samples[:-1]):
            nxt = samples[pos + 1]
            gap = (nxt - t) * seconds_per_tick
            speed = (fp_of(nxt) - fp_of(t)) / gap if gap > 1e-12 else 0.0
            if abs(t - rot_start) < 1e-9:
                speed = rotation_speed(t)
            rcf.addCanvasSpeed(chart, index, t, speed, isChangeZeroSpeed=False)
        rcf.addCanvasSpeed(chart, index, samples[-1], 0.0, isChangeZeroSpeed=False)

    # 顶点与边：都用 rcf.addLine，节点 floorPosition 由库按画布地板计算
    colors = resolve_colors(options, shape.sides)
    omega = 2.0 * math.pi / (options.rev if options.rev and options.rev > 0
                             else (options.end - options.start))

    def anchor_tick(k: int) -> float:
        """顶点 k 的挂靠拍 = 画线拍 + k·stagger。

        错开是为了在编辑器里能分别选中每个节点；因为相邻只差 0.25 拍，
        对形状的影响约 1°（三角形/六边形同理）。
        """
        return draw_tick + k * max(0.0, float(options.stagger))   # 落在抬升后的静止段

    def point(canvas: int, color: dict, tick: float) -> dict:
        return {"time": tick, "xPosition": 0.0, "canvasIndex": canvas,
                "easeType": 0, "color": color}

    # 判定环一律透明（线不需要判定环）；线的颜色由每个节点自己的 color 决定
    transparent = {"r": 0, "g": 0, "b": 0, "a": 0}

    for k in range(shape.sides):
        color = colors[k]
        tick = anchor_tick(k)
        rcf.addLine(chart, [point(base + k, color, tick), point(base + k, color, tick)],
                    {"time": 0.0, "startColor": transparent, "endColor": transparent})

    if options.edges:
        for k in range(shape.sides):
            nxt = (k + 1) % shape.sides
            # 边的两端各用自己顶点的颜色 + 各自的挂靠拍（错开后编辑器里可分别选中）
            rcf.addLine(chart, [point(base + k, colors[k], anchor_tick(k)),
                                point(base + nxt, colors[nxt], anchor_tick(nxt))],
                        {"time": 0.0, "startColor": transparent, "endColor": transparent})

    return chart, base, line_start


# --------------------------------------------------------------------------- 校验

def verify(path: Path, options: Options, base: int) -> int:
    import math as _math

    ensure_library()
    import rizChartFunction as rcf
    from rizChartFunction import query

    chart = json.loads(path.read_text(encoding="utf-8"))
    reloaded = rcf.load(str(path))
    shape = options.shape
    s1 = speed_const(options.flow)
    ticks = tick_samples(options)

    # 编辑器的渲染模型：点在 t 时刻的 y = S1 × (fp(锚点拍) − fp(t))，
    # 锚点拍就是该顶点点线所在的那一拍（此时正好在判定线上）。
    anchors: dict[int, float] = {}
    for line in chart["lines"]:
        pts = line["linePoints"]
        if len(pts) == 2 and pts[0]["canvasIndex"] == pts[1]["canvasIndex"]:
            anchors.setdefault(pts[0]["canvasIndex"], pts[0]["time"])

    worst_side = worst_radius = worst_angle = 0.0
    ys: list[float] = []
    for tick in [t for t in ticks if t < options.end - 1e-6]:   # 只看旋转窗口内
        pts = []
        for k in range(shape.sides):
            canvas = base + k
            x = query.getCanvasPositionAt(chart, tick, index=canvas)
            fp = query.getFloorPosition(chart, tick, canvas)
            fp_anchor = query.getFloorPosition(chart, anchors.get(canvas, options.end), canvas)
            if x is None or fp is None or fp_anchor is None:
                raise RuntimeError(f"画布 {canvas} 在 tick {tick} 取不到位置")
            pts.append((x * X_PER_UNIT, (fp_anchor - fp) * s1))
            ys.append((fp_anchor - fp) * s1)
        sides = [_math.dist(pts[k], pts[(k + 1) % len(pts)]) for k in range(len(pts))]
        worst_side = max(worst_side, max(abs(s - shape.edge_lengths[k]) for k, s in enumerate(sides)))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        worst_radius = max(worst_radius, max(abs(_math.dist(p, (cx, cy)) - shape.radius) for p in pts))
        n = len(pts)
        expected = 180.0 - 360.0 / n
        for k in range(n):
            a, b, c = pts[k], pts[(k + 1) % n], pts[(k + 2) % n]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            len1, len2 = _math.hypot(*v1), _math.hypot(*v2)
            if len1 < 1e-9 or len2 < 1e-9:
                continue
            cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)
            interior = 180.0 - _math.degrees(_math.acos(max(-1.0, min(1.0, cosang))))
            worst_angle = max(worst_angle, abs(interior - expected))

    print(f"采样点     : {len(ticks)} 个（{ticks[0]:g} .. {ticks[-1]:g} tick）")
    print(f"形状       : {shape.label}    外接圆 R {shape.radius:.4f}")
    print(f"边长最大误差: {worst_side:.3e}")
    print(f"半径最大误差: {worst_radius:.3e}")
    print(f"内角最大误差: {worst_angle:.4f}°")
    print(f"y 范围      : {min(ys):.3f} .. {max(ys):.3f}  (期望 {options.center_y - shape.radius:.3f} .. "
          f"{options.center_y + shape.radius:.3f})")
    print(f"线数        : {len(chart['lines'])}    画布数 {len(chart['canvasMoves'])}")
    print(f"库读回      : {'ok' if reloaded else '失败'}")
    # 0.5 拍采样的弦误差约 1e-3 世界单位，容差按 2e-3 判
    ok = (worst_side < 2e-3 and worst_angle < 0.05 and reloaded is not None)
    print("结论        :", "通过" if ok else "有偏差")
    return 0 if ok else 1


# --------------------------------------------------------------------------- CLI

def ask(prompt: str, default: str) -> str:
    try:
        value = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return value or default


def interactive() -> Options:
    print("== 旋转多边形生成器 ==")
    print("单位说明：")
    print("  · 长度/高度：世界单位（一屏高 = 6.9 世界单位；1 个 xPosition 单位 = 5.625 世界单位）")
    print("  · 时间：拍（tick，320 BPM 时 1 拍 = 0.1875 秒）")
    print("  · 中心高度：世界单位；半径 2.0 时圆心放在 3.2 ≈ 半屏，形状正好在可视区")
    sides = int(ask("边数（≥3，4=矩形/正方形）", "4"))
    if sides == 4:
        square = ask("正方形？(y/n)", "y").lower().startswith("y")
        if square:
            shape = build_shape(4, None, None, None, float(ask("外接圆半径（世界单位）", "2")))
        else:
            shape = build_shape(4, None, float(ask("宽度（世界单位，一屏宽 = 5.625）", "3")),
                                float(ask("高度（世界单位，一屏高 = 6.9）", "2")), None)
    else:
        shape = build_shape(sides, None, None, None, float(ask("外接圆半径（世界单位）", "2")))
    colors_text = ask("顶点颜色（逗号分隔 #rrggbb，回车=默认调色板）", "").strip()
    colors = parse_palette(colors_text) if colors_text else None

    print("—— 追加（可选）——")
    into_text = ask("追加到已有谱面（填路径，回车=新建）", "").strip()
    into = Path(into_text) if into_text else None
    start_text = ask("从第几个画布开始（回车=接在末尾）", "").strip() if into else ""
    canvas_start = int(start_text) if start_text else None
    if into:
        print(f"   => 将追加到 {into.name}，起始画布：{canvas_start if canvas_start is not None else '末尾'}")

    return Options(
        shape=shape,
        flow=float(ask("播放流速", str(DEFAULT_FLOW))),
        bpm=float(ask("BPM", str(DEFAULT_BPM))),
        start=float(ask("起始拍（入场）", "8")),
        end=float(ask("结束拍", "92")),
        rev=float(ask("旋转一圈要几拍（0 = 整段转一圈）", "0")),
        step=float(ask("采样间隔（拍；越小越顺滑、关键点越多，0.1~1 常用）", "0.5")),
        center_y=float(ask("中心高度（世界单位）", "2")),
        out=Path(ask("输出文件", "rot_polygon_chart.json")),
        colors=colors,
        into=into,
        canvas_start=canvas_start,
    )


def parse_args(argv: list[str] | None = None) -> Options:
    parser = argparse.ArgumentParser(
        description="生成旋转正多边形/矩形的引导线谱面（顶点钉在画布上，边用跨画布线）")
    parser.add_argument("--sides", type=int, default=4, help="边数（默认 4）")
    parser.add_argument("--side", type=float, help="边长（世界单位，正多边形；与 --radius 二选一）")
    parser.add_argument("--width", type=float, help="矩形宽（世界单位，仅 --sides 4）")
    parser.add_argument("--height", type=float, help="矩形高（世界单位，仅 --sides 4）")
    parser.add_argument("--radius", type=float, default=None,
                        help="外接圆半径（世界单位，默认 2.0；一屏高 = 6.9）")
    parser.add_argument("--flow", type=float, default=DEFAULT_FLOW, help="播放流速（默认 7.5）")
    parser.add_argument("--bpm", type=float, default=DEFAULT_BPM, help="BPM（默认 320）")
    parser.add_argument("--start", type=float, default=8.0, help="起始拍")
    parser.add_argument("--end", type=float, default=92.0, help="结束拍")
    parser.add_argument("--rev", type=float, default=0.0,
                        help="旋转一圈要几拍（默认 0 = 整段正好转一圈）")
    parser.add_argument("--step", type=float, default=0.5,
                        help="采样间隔（拍）：越小越顺滑，关键点越多（320 BPM 下 0.5 拍 = 0.094 秒）")
    parser.add_argument("--phase", type=float, default=0.0, help="初始角度（度）")
    parser.add_argument("--center-x", type=float, default=0.0, help="中心 x（xPosition 单位）")
    parser.add_argument("--center-y", type=float, default=3.2, help="圆心高度（世界单位；一屏=6.9，默认 3.2）")
    parser.add_argument("--canvas-base", type=int, default=1, help="起始画布编号")
    parser.add_argument("--park", type=float, default=0.0, help="正弦段后、1流速段前的静止长度（tick）")
    parser.add_argument("--lift-ticks", type=float, default=None, help="1 流速段长度（tick）；默认由 --center-y 反算")
    parser.add_argument("--post-speed", type=float, default=0.0, help="结束拍之后的流速")
    parser.add_argument("--post-ticks", type=float, default=0.0, help="结束拍之后延续多少拍")
    parser.add_argument("--colors", type=str, default=None,
                        help='顶点调色板，如 "#ff3c3c,#3cdc5a,#4682ff,#e650e6"（相邻不同色，边会自动渐变）')
    parser.add_argument("--color", type=str, default=None,
                        help='所有顶点/边统一用这个颜色，如 "#ffffff"')
    parser.add_argument("--no-edges", action="store_true", help="不画边")
    parser.add_argument("--no-dots", action="store_true", help="不画顶点")
    parser.add_argument("--into", type=Path, default=None, help="追加到已有谱面（原内容不动）")
    parser.add_argument("--hold", type=float, default=0.0,
                        help="抬升后静止的拍数（默认 2.0；挂靠点错开发生在这段里）")
    parser.add_argument("--stagger", type=float, default=0.25,
                        help="相邻顶点错开的拍数（默认 0.25；0 = 全部同一拍）")
    parser.add_argument("--canvas-start", type=int, default=None,
                        help="追加时从第几个画布开始（默认接在末尾；不能小于现有画布数）")
    parser.add_argument("--out", type=Path, default=Path("rot_polygon_chart.json"), help="输出文件")
    parser.add_argument("--interactive", action="store_true", help="交互式输入")
    parser.add_argument("--verify", action="store_true", help="生成后校验几何")
    args = parser.parse_args(argv)

    if args.interactive or (argv is None and len(sys.argv) == 1):
        options = interactive()
        options.verify = args.verify
        return options

    options = Options(
        shape=build_shape(args.sides, args.side, args.width, args.height, args.radius),
        flow=args.flow, bpm=args.bpm, start=args.start, end=args.end, rev=args.rev,
        step=args.step, phase_deg=args.phase, center_x=args.center_x, center_y=args.center_y,
        canvas_base=args.canvas_base, park=args.park, lift_ticks=args.lift_ticks, post_speed=args.post_speed,
        post_ticks=args.post_ticks, edges=not args.no_edges, dots=not args.no_dots,
        colors=parse_palette(args.colors) if args.colors else None,
        color=parse_color(args.color) if args.color else None,
        out=args.out, into=args.into, canvas_start=args.canvas_start,
        stagger=args.stagger, hold=args.hold,
    )
    options.verify = args.verify
    return options


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    ensure_library()
    import rizChartFunction as rcf

    existing = None
    if options.into is not None:
        existing = rcf.load(str(options.into))
        if existing is None:
            raise SystemExit(f"读不了 {options.into}")

    chart, base, _ = make_chart(options, existing)

    options.out.parent.mkdir(parents=True, exist_ok=True)
    if not rcf.export(chart, str(options.out)):
        raise SystemExit("导出失败（rcf.export 返回 False）")

    target = f"（追加到 {options.into.name}）" if options.into else ""
    print(f"已生成 {options.out}{target}：{len(chart['lines'])} 条线 / "
          f"{len(chart['canvasMoves'])} 个画布 / 顶点画布 {base}..{base + options.shape.sides - 1}")
    print(f"按播放流速 {options.flow:g} 生成（世界 y 系数 {speed_const(options.flow):.3f}），"
          f"编辑器里请用同一流速播放，否则形状会被压扁/拉长")
    shape = options.shape
    span = options.center_y + shape.radius - (options.center_y - shape.radius)
    print(f"尺寸：半径 {shape.radius:.3f} 世界单位"
          f"（= {shape.radius / X_PER_UNIT:.3f} xPosition 单位）"
          f"；边长 {shape.side_length:.3f} 世界单位")
    step_ticks = effective_step(options)
    print(f"采样：每 {step_ticks:g} 拍（= {step_ticks * 60 / options.bpm:.4f} 秒）")
    print(f"高度：圆心 {options.center_y:.2f} 世界单位，y 范围 "
          f"{options.center_y - shape.radius:.2f} .. {options.center_y + shape.radius:.2f}"
          f"（占一屏 {span / 6.9 * 100:.0f}%，一屏 = 6.9）")
    if getattr(options, "verify", False):
        return verify(options.out, options, base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
