# Blackbird 中文路由镜像

镜像地址：`ghcr.io/sw897/blackbird-valhalla`。

推送到 `zh-CN` 会触发 `Publish Blackbird image`。也可在 Actions 中手动运行，分支选择 `zh-CN`。
amd64 和 arm64 分别在原生 runner 上构建；每个架构通过中文接口、矩阵、等时圈和重启复用测试后，才发布对应架构镜像。两个架构都成功后，发布统一的多架构标签。

## 版本标签

版本号从 `valhalla/valhalla.h` 读取，中文发布序号使用该工作流的 `github.run_number`。
例如首次发布 Valhalla 3.9.1 时：

| 标签 | 含义 |
|---|---|
| `3.9.1-zh.1` | 同时包含 amd64 和 arm64 的发布版本 |
| `3.9.1-zh.1-sha-<12位提交号>` | 同一发布版本，附源代码提交号 |
| `3.9.1-zh.1-amd64` | amd64 架构镜像 |
| `3.9.1-zh.1-arm64` | arm64 架构镜像 |

失败的运行也会占用发布序号。部署时使用具体版本；需固定到完全相同的镜像内容时使用发布摘要中的 digest。
镜像 OCI 标签记录源代码仓库、完整提交号和发布版本。工作流通过 `GITHUB_TOKEN` 的 `packages: write` 权限发布，无需保存 PAT。

## 使用

将下例版本替换为 Actions 发布摘要中的实际版本：

```bash
docker pull ghcr.io/sw897/blackbird-valhalla:3.9.1-zh.1
docker run -d --name blackbird-valhalla -p 8002:8002 \
  -v "$PWD/custom_files:/custom_files" \
  ghcr.io/sw897/blackbird-valhalla:3.9.1-zh.1
```

首次启动时，将 `.osm.pbf` 放入 `custom_files`，入口会自动生成配置并构建瓦片；也可用 `BUILD_PBF` 显式指定容器内的 PBF 路径。已有 `tiles` 目录会直接复用。
导航请求传入 `"language": "zh-CN"` 或 `"language": "zh"`。

## GitLab 备份

`origin` 指向 GitHub fork，`upstream` 指向官方仓库，`highmap` 保留现有 GitLab 仓库。
发布相关提交同步至 `zh-CN` 后，更新 GitLab 备份：

```bash
git push highmap zh-CN
```
