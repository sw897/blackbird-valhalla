#!/bin/bash
# blackbird 路网 sidecar 入口：
#   1. /custom_files/valhalla.json 缺失时用 valhalla_build_config 生成——全部数据
#      路径（瓦片与可选数据）统一收口到 /custom_files，宿主只需挂载这一个卷
#   2. 首启建瓦片（幂等，仅 tiles 目录不存在时）：
#      BUILD_PBF 显式指定优先；否则自动扫描 /custom_files 下最新修改的 *.osm.pbf
#   3. 启动 valhalla_service（默认全核并发，监听 :8002）
# 可选增强数据（放入挂载目录 dist/valhalla/ 即生效，缺失仅对应功能降级）：
#   elevation/*.hgt（DEM 高程）、admin.sqlite、timezone.sqlite、
#   transit/（公交瓦片）、traffic.tar（实时交通）
set -e -o pipefail

CUSTOM=/custom_files
CONF="$CUSTOM/valhalla.json"
TILES="$CUSTOM/tiles"
mkdir -p "$CUSTOM"

if [ ! -f "$CONF" ]; then
  echo "generating $CONF ..."
  valhalla_build_config \
    --mjolnir-tile-dir "$TILES" \
    --mjolnir-tile-extract "" \
    --mjolnir-traffic-extract "$CUSTOM/traffic.tar" \
    --mjolnir-admin "$CUSTOM/admin.sqlite" \
    --mjolnir-timezone "$CUSTOM/timezone.sqlite" \
    --mjolnir-transit-dir "$CUSTOM/transit" \
    --additional-data-elevation "$CUSTOM/elevation" \
    --mjolnir-concurrency "${TILE_BUILD_CONCURRENCY:-$(nproc)}" \
    > "$CONF"
fi

if [ ! -d "$TILES" ]; then
  PBF="$BUILD_PBF"
  if [ -z "$PBF" ]; then
    PBF=$(ls -1t "$CUSTOM"/*.osm.pbf 2>/dev/null | head -1 || true)
  fi
  if [ -n "$PBF" ] && [ -f "$PBF" ]; then
    echo "building tiles from $PBF (first run) ..."
    valhalla_build_tiles -c "$CONF" "$PBF"
  else
    echo "WARNING: $TILES 不存在，且 $CUSTOM 下未找到 *.osm.pbf；"
    echo "         服务仍将启动，但路径/等时圈等分析请求会失败，请先构建瓦片。"
  fi
fi

exec valhalla_service "$CONF" "${VALHALLA_CONCURRENCY:-$(nproc)}"
