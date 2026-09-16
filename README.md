# quickly draw 本地免费版

作者：Kkeep

这是 `quickly draw` 的本地后端版本：默认使用本机本地矢量服务进行图片到 SVG 的矢量化，不需要外部 API Key 或额度。

## 安装

将压缩包内的 `quickly-draw` 文件夹复制到 Codex skills 目录：

```text
%USERPROFILE%\.codex\skills\quickly-draw
```

如果已有同名 skill，请先备份后覆盖。

## 使用

首次使用时，quickly-draw 会在绘图前自动检查并后台启动本地矢量化服务；如果本机缺少 `vtracer`，也会尝试自动安装。无需手动启动服务。

如需手动检查或启动，可运行：

```powershell
& "$env:USERPROFILE\.codex\skills\quickly-draw\scripts\ensure-local-vector-service.ps1"
```

然后正常使用 `quickly draw`。默认服务地址为 `http://127.0.0.1:8787`，图片不会上传到外部服务器。

## 可编辑文字规则

参考图中所有可读的英文、数字、单位、图例、坐标轴、面板字母和化学符号，都必须在最终 Illustrator 文件中作为原生可编辑文本框（`TextFrame`）存在。不得把文字描成路径、栅格化，或在实时文字下保留重复的描字轮廓。

图形矢量化前可使用 `scripts/build_live_text_redraw.py` 生成去文字的图形输入和文本 manifest，再用 `scripts/validate_live_text_manifest.py` 校验、`scripts/merge_live_text.py` 合并原生文字。使用前请人工校对 OCR，尤其是数字、小数、上下标、单位和科学符号。

该 OCR 辅助脚本依赖 `scripts/requirements-live-text.txt` 中的 `opencv-python`、`numpy` 和 `rapidocr_onnxruntime`；如果环境已经安装，可直接运行。

本地后端使用 VTracer 生成多色 SVG 路径，扁平色块和示意图效果较好；复杂照片、纹理和渐变可能需要在 Illustrator 中继续调整。
