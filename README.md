# rot_polygon

生成**旋转正多边形 / 矩形**的 Rizline 谱面引导线：每个顶点一个画布，边用跨画布的线相连，
图形绕固定圆心匀速旋转。

> 本仓库只含源码与文档：不含第三方库、不含美术/音乐素材、不含构建产物。

## 用法

```powershell
python rot_polygon.py --sides 4 --radius 2 --flow 3.5 --out 正方形.json
python rot_polygon.py --sides 6 --radius 1.5 --flow 3.5 --rev 21 --out 六边形.json
python rot_polygon.py --interactive      # 问答式
```

生成的是标准谱面 JSON，顶点默认从 1 号画布开始（0 号补位），节点错开到不同拍方便在编辑器里选中。

## 依赖：rizChartFunction_Library（不在本仓库）

谱面读写依赖 **[rizChartFunction_Library](https://github.com/xp00000002/rizChartFunction_Library)**
（第三方项目，按它自己的许可使用，不随本仓库分发）：

```powershell
# 克隆到本工具旁边，程序会自动找到
git clone --depth 1 https://github.com/xp00000002/rizChartFunction_Library.git ..\rizChartFunction_Library
# 或放任意位置，用环境变量指定
$env:RIZCHARTFUNCTION_SRC = 'D:\libs\rizChartFunction_Library\src'
```

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--sides` / `--radius` | 边数（≥3）/ 外接圆半径（世界单位，一屏高 = 6.9） |
| `--width` `--height` | 矩形宽高（仅 `--sides 4`） |
| `--flow` | **必须**等于编辑器里的播放流速，否则形状会被压扁/拉长 |
| `--start` / `--end` | 旋转起止拍（默认 8 / 92） |
| `--rev` | 转一圈几拍（0 = 整段一圈） |
| `--center-y` | 圆心高度（世界单位，默认 3.2 ≈ 半屏） |
| `--colors` / `--color` | 顶点调色板 / 统一色 |
| `--into` / `--canvas-start` | 追加到已有谱面，从指定画布开始 |

其余参数见 `python rot_polygon.py --help`。

## 许可

代码与文档采用 [MIT License](LICENSE)。`rizChartFunction_Library` 不属于本仓库。
