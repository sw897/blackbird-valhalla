#!/bin/bash
# blackbird 路网 sidecar 入口：
#   1. /custom_files/valhalla.json 缺失时用 valhalla_build_config 生成
#      （tile 目录固定 /custom_files/tiles.tar）
#   2. 设置 BUILD_PBF=/custom_files/xxx.osm.pbf 且 tiles.tar 不存在时先建瓦片
#   3. 启动 valhalla_service（默认全核并发，监听 :8002）
# 数据（tiles.tar / PBF / 预置 valhalla.json）经卷挂载到 /custom_files 注入。
set -e -o pipefail

CUSTOM=/custom_files
CONF="$CUSTOM/valhalla.json"
TILES="$CUSTOM/tiles.tar"
mkdir -p "$CUSTOM"

if [ ! -f "$CONF" ]; then
  echo "generating $CONF ..."
  valhalla_build_config \
    --mjolnir-tile-dir "$TILES" \
    --mjolnir-concurrency "${TILE_BUILD_CONCURRENCY:-$(nproc)}" \
    > "$CONF"
fi

if [ -n "$BUILD_PBF" ] && [ ! -f "$TILES" ]; then
  echo "building tiles from $BUILD_PBF (first run) ..."
  valhalla_build_tiles -c "$CONF" "$BUILD_PBF"
fi

exec valhalla_service "$CONF" "${VALHALLA_CONCURRENCY:-$(nproc)}"
