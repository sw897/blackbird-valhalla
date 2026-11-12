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
        return subprocess.run(["docker", *command], capture_output=True, text=True, check=True)

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
        shutil.copyfile(fixture, data / "utrecht.osm.pbf")
        created = False
        try:
            docker(
                "run",
                "--detach",
                "--name",
                name,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={data},dst=/custom_files",
                "--env",
                "TILE_BUILD_CONCURRENCY=2",
                "--env",
                "VALHALLA_CONCURRENCY=2",
                args.image,
            )
            created = True
            wait_for_service()
            version = docker("exec", name, "valhalla_service", "--version").stdout.strip()
            if not version.startswith(args.version_prefix):
                raise AssertionError(f"Unexpected engine version: {version}")
            locations = [
                {"lat": 52.11530314, "lon": 5.08815505},
                {"lat": 52.11932621, "lon": 5.10742859},
            ]
            for language in ("zh", "zh-CN"):
                route = request(
                    "route", {"locations": locations, "costing": "auto", "language": language}
                )
                trip = route["trip"]
                if trip["language"] not in ("zh", "zh-CN"):
                    raise AssertionError(f"Chinese locale fell back to {trip['language']}")
                maneuvers = trip["legs"][0]["maneuvers"]
                text = " ".join(m["instruction"] for m in maneuvers)
                verbal = " ".join(m.get("verbal_pre_transition_instruction", "") for m in maneuvers)
                if not re.search(r"[\u4e00-\u9fff]", text) or not re.search(r"[\u4e00-\u9fff]", verbal):
                    raise AssertionError("Chinese text or voice instructions are missing")
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
            print(f"{version}: Chinese routes, voice, matrix, isochrone and restart passed")
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
