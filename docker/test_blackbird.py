#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--version-prefix", required=True)
    args = parser.parse_args()
    name = f"blackbird-smoke-{uuid.uuid4().hex[:12]}"

    def docker(*command):
        return subprocess.run(
            ["docker", *command], capture_output=True, text=True, check=True, timeout=30
        )

    def expect_failed_start():
        code = int(docker("wait", name).stdout.strip())
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name).stdout)
        if code == 0 or state.get("Health", {}).get("Status") == "healthy":
            raise AssertionError("An incomplete tileset was accepted as ready")

    def request(endpoint, payload=None):
        command = ["exec", name, "curl", "-fsS", "--max-time", "10"]
        if payload is not None:
            command += ["-H", "Content-Type: application/json", "--data", json.dumps(payload)]
        return json.loads(docker(*command, f"http://127.0.0.1:8002/{endpoint}").stdout)

    def wait_for_service():
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                return request("status")
            except (subprocess.CalledProcessError, ValueError):
                time.sleep(1)
        raise RuntimeError("Blackbird service did not become ready")

    with tempfile.TemporaryDirectory(prefix="blackbird-smoke-") as workdir:
        data = Path(workdir)
        fixture = Path(__file__).resolve().parents[1] / "test/data/utrecht_netherlands.osm.pbf"
        empty_tile = data / "tiles/2/000/000.gph"
        empty_tile.parent.mkdir(parents=True)
        empty_tile.touch()
        marker = data / ".blackbird-building"
        created = False
        try:
            docker(
                "run",
                "--detach",
                "--name",
                name,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--ulimit",
                "core=0",
                "--mount",
                f"type=bind,src={data},dst=/custom_files",
                "--env",
                "TILE_BUILD_CONCURRENCY=2",
                "--env",
                "VALHALLA_CONCURRENCY=2",
                "--health-interval=1s",
                "--health-start-period=1s",
                args.image,
            )
            created = True
            expect_failed_start()
            pbf = data / "utrecht.osm.pbf"
            pbf.write_bytes(b"invalid OSM PBF")
            docker("start", name)
            expect_failed_start()
            if not marker.exists():
                raise AssertionError("Failed build did not retain its recovery marker")
            shutil.copyfile(fixture, pbf)
            docker("start", name)
            wait_for_service()
            if marker.exists():
                raise AssertionError("Successful build retained its recovery marker")
            version = docker("exec", name, "valhalla_service", "--version").stdout.strip()
            if not version.startswith(args.version_prefix):
                raise AssertionError(f"Unexpected engine version: {version}")
            locations = [
                {"lat": 52.11530314, "lon": 5.08815505},
                {"lat": 52.11932621, "lon": 5.10742859},
            ]
            for language in ("zh", "zh-CN"):
                for costing in ("auto", "pedestrian"):
                    route = request(
                        "route", {"locations": locations, "costing": costing, "language": language}
                    )
                    trip = route["trip"]
                    if trip["language"] not in ("zh", "zh-CN"):
                        raise AssertionError(f"Chinese locale fell back to {trip['language']}")
                    for maneuver in trip["legs"][0]["maneuvers"]:
                        for key, text in maneuver.items():
                            if "instruction" not in key or not text:
                                continue
                            if not re.search(r"[\u4e00-\u9fff]", text):
                                raise AssertionError(f"Chinese instruction is missing: {text}")
                            if re.search(r"[。！？][，。！？]", text):
                                raise AssertionError(f"Duplicate narrative punctuation: {text}")
                            if costing == "pedestrian" and "行驶" in text:
                                raise AssertionError(f"Driving wording in pedestrian route: {text}")
                    if re.search(r"<[A-Z][A-Z_0-9]*>", json.dumps(route, ensure_ascii=False)):
                        raise AssertionError("Narrative contains an unresolved placeholder")
            matrix = request(
                "sources_to_targets",
                {"sources": locations[:1], "targets": locations[1:], "costing": "auto"},
            )
            if matrix["sources_to_targets"][0][0]["time"] <= 0:
                raise AssertionError("Matrix did not return a travel time")
            isochrone = request(
                "isochrone", {"locations": locations[:1], "costing": "auto", "contours": [{"time": 1}]}
            )
            if not isochrone.get("features"):
                raise AssertionError("Isochrone did not return any features")
            config = data / "valhalla.json"
            config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
            tiles = {
                str(p.relative_to(data)): p.stat().st_mtime_ns for p in (data / "tiles").rglob("*.gph")
            }
            if not tiles:
                raise AssertionError("PBF scan did not produce graph tiles")
            docker("restart", name)
            wait_for_service()
            if config_hash != hashlib.sha256(config.read_bytes()).hexdigest():
                raise AssertionError("Restart changed the existing configuration")
            if tiles != {
                str(p.relative_to(data)): p.stat().st_mtime_ns for p in (data / "tiles").rglob("*.gph")
            }:
                raise AssertionError("Restart rebuilt existing graph tiles")
            docker("stop", name)
            marker.touch()
            docker("start", name)
            wait_for_service()
            if marker.exists():
                raise AssertionError("Interrupted build was not recovered")
            logs = docker("logs", name)
            if (logs.stdout + logs.stderr).count("building tiles from ") != 3:
                raise AssertionError("Interrupted build reused a potentially partial tileset")
            docker("stop", name)
            custom_tiles = data / "routing-tiles"
            (data / "tiles").rename(custom_tiles)
            configuration = json.loads(config.read_text())
            configuration["mjolnir"]["tile_dir"] = "/custom_files/routing-tiles"
            config.write_text(json.dumps(configuration))
            docker("start", name)
            wait_for_service()
            request("route", {"locations": locations, "costing": "auto", "language": "zh-CN"})
            logs = docker("logs", name)
            if (logs.stdout + logs.stderr).count("building tiles from ") != 3:
                raise AssertionError("Custom tile directory was not reused")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                health = docker("inspect", "--format", "{{.State.Health.Status}}", name).stdout.strip()
                if health == "healthy":
                    break
                time.sleep(1)
            else:
                raise AssertionError("Completed tileset did not become healthy")
            print(f"{version}: Chinese routes, voice, recovery, matrix, isochrone and restart passed")
        except Exception:
            if created:
                logs = docker("logs", "--tail", "100", name)
                print(logs.stdout + logs.stderr, flush=True)
            raise
        finally:
            if created:
                docker("rm", "--force", name)


if __name__ == "__main__":
    main()
