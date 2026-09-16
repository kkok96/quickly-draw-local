# quickly draw 本地兼容 API

这是一个不依赖外部账号和额度的本地矢量服务。它保留 quickly draw 所需的接口：

- `GET /api/health`
- `POST /api/images`
- `GET /api/images/{image_id}`
- `GET /api/images/{image_id}/file`
- `GET /api/images/{image_id}/result`

当前后端使用已安装的本地 `vtracer`，把 PNG、JPEG 或 WebP 转成多色 SVG 路径。图片不会离开本机。

## 启动

quickly-draw 会在绘图前通过 `scripts/ensure-local-vector-service.ps1` 自动检查并后台启动本服务。

如需手动启动，在 PowerShell 中运行：

```powershell
Set-Location "C:\Users\hszn\.codex\skills\quickly-draw\local-api"
.\start-local-vector-service.ps1
```

服务默认监听 `http://127.0.0.1:8787`。保持这个窗口运行，再执行 quickly draw。

## 说明

这个服务是本地接口和流程实现。纯色、扁平化科研图的效果更合适；复杂照片、纹理和渐变可能需要在 Illustrator 中继续清理。
