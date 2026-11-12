#!/bin/bash
# blackbird 路网 sidecar 入口：
#   1. /custom_files/valhalla.json 缺失时用 valhalla_build_config 生成——全部数据
#      路径（瓦片与可选数据）统一收口到 /custom_files，宿主只需挂载这一个卷
#   2. 缺少瓦片或上次构建未完成时重建：
#      BUILD_PBF 显式指定优先；否则自动扫描 /custom_files 下最新修改的 *.osm.pbf
#   3. 启动 valhalla_service（默认全核并发，监听 :8002）
# 可选增强数据（放入挂载目录 dist/valhalla/ 即生效，缺失仅对应功能降级）：
#   elevation/*.hgt（DEM 高程）、admin.sqlite、timezone.sqlite、
#   transit/（公交瓦片）、traffic.tar（实时交通）
set -e -o pipefail

CUSTOM=/custom_files
CONF="$CUSTOM/valhalla.json"
TILES="$CUSTOM/tiles"
BUILDING="$CUSTOM/.blackbird-building"
READY=/tmp/blackbird-ready
mkdir -p "$CUSTOM"
rm -f "$READY"

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
    > "$CONF.tmp"
  mv "$CONF.tmp" "$CONF"
fi

tiles_available() {
  python3 - "$CONF" <<'PY'
import json
import sys
from pathlib import Path

with open(sys.argv[1]) as config_file:
    config = json.load(config_file)["mjolnir"]
extract = config.get("tile_extract")
if extract and Path(extract).is_file() and Path(extract).stat().st_size:
    sys.exit(0)
directory = config.get("tile_dir")
if directory:
    for tile in Path(directory).rglob("*.gph"):
        if tile.is_file() and tile.stat().st_size:
            sys.exit(0)
sys.exit(1)
PY
}

# An interrupted build can leave nonempty graph tiles.
if [ -f "$BUILDING" ] || ! tiles_available; then
  PBF="${BUILD_PBF:-}"
  if [ -z "$PBF" ]; then
    PBF=$(ls -1t "$CUSTOM"/*.osm.pbf 2>/dev/null | head -1 || true)
  fi
  if [ -n "$PBF" ] && [ -f "$PBF" ]; then
    echo "building tiles from $PBF ..."
    touch "$BUILDING"
    valhalla_build_tiles -c "$CONF" "$PBF"
    if ! tiles_available; then
      echo "ERROR: tile build completed without usable tiles." >&2
      exit 1
    fi
    rm -f "$BUILDING"
  else
    echo "ERROR: no completed tileset; provide an OSM PBF in $CUSTOM or set BUILD_PBF." >&2
    exit 1
  fi
fi

touch "$READY"
exec valhalla_service "$CONF" "${VALHALLA_CONCURRENCY:-$(nproc)}"
