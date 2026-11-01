"""Validation tests for the homelab-compose stack.

These run without bringing containers up: they parse every YAML/JSON file,
cross-check that the compose files only reference variables documented in
.env.example, and (when Docker is available) render the merged compose model
with `docker compose config`.
"""
import json
import os
import re
import shutil
import subprocess
import stat

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMPOSE_FILES = [
    "docker-compose.yml",
    "compose/monitoring.yml",
    "compose/backup.yml",
]

# ${VAR} / ${VAR:-default} / ${VAR-default}. A default means the value is
# optional, so only bare ${VAR} references must be documented in .env.example.
VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)(:?-[^}]*)?\}")


def _path(*parts):
    return os.path.join(ROOT, *parts)


def _load_yaml(rel):
    with open(_path(rel)) as fh:
        return yaml.safe_load(fh)


def _env_example_keys():
    keys = set()
    with open(_path(".env.example")) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.add(line.split("=", 1)[0])
    return keys


def test_yaml_files_parse():
    for rel in COMPOSE_FILES + [
        "prometheus/prometheus.yml",
        "traefik/dynamic/tls.yml",
        "grafana/provisioning/datasources/datasource.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
    ]:
        assert _load_yaml(rel) is not None, f"{rel} parsed empty"


def test_env_example_is_complete():
    documented = _env_example_keys()
    referenced = set()
    for rel in COMPOSE_FILES:
        with open(_path(rel)) as fh:
            for m in VAR_RE.finditer(fh.read()):
                if not m.group(2):  # no inline default -> must be documented
                    referenced.add(m.group(1))
    missing = referenced - documented
    assert not missing, f"variables used but missing from .env.example: {sorted(missing)}"


def test_expected_services_present():
    services = {}
    for rel in COMPOSE_FILES:
        data = _load_yaml(rel) or {}
        services.update(data.get("services", {}))
    for name in ["traefik", "prometheus", "grafana", "node-exporter", "cadvisor", "backup"]:
        assert name in services, f"service '{name}' missing from compose files"


def test_traefik_publishes_via_labels():
    base = _load_yaml("docker-compose.yml")
    labels = base["services"]["traefik"]["labels"]
    joined = "\n".join(labels)
    assert "traefik.enable=true" in joined
    assert "api@internal" in joined  # dashboard wired to the internal API
    assert "basicauth" in joined     # dashboard is protected


def test_grafana_routed_and_datasource_points_to_prometheus():
    mon = _load_yaml("compose/monitoring.yml")
    glabels = "\n".join(mon["services"]["grafana"]["labels"])
    assert "Host(`grafana." in glabels
    assert "certresolver=le" in glabels

    ds = _load_yaml("grafana/provisioning/datasources/datasource.yml")
    prom = ds["datasources"][0]
    assert prom["type"] == "prometheus"
    assert prom["url"] == "http://prometheus:9090"


def test_dashboard_panels_reference_provisioned_datasource_uid():
    ds = _load_yaml("grafana/provisioning/datasources/datasource.yml")
    uids = {d.get("uid") for d in ds["datasources"]}
    with open(_path("grafana/provisioning/dashboards/homelab-overview.json")) as fh:
        dash = json.load(fh)
    for panel in dash["panels"]:
        refs = [panel.get("datasource")] + [t.get("datasource") for t in panel["targets"]]
        for ref in refs:
            if isinstance(ref, dict) and "uid" in ref:
                assert ref["uid"] in uids, (
                    f"panel {panel['title']!r} uses datasource uid {ref['uid']!r}, "
                    f"provisioned uids are {sorted(u for u in uids if u)}"
                )


def test_dashboard_filesystem_query_matches_node_exporter_mountpoint():
    # node-exporter strips --path.rootfs from mountpoint labels, so with
    # --path.rootfs=/host the host root filesystem is reported as "/".
    mon = _load_yaml("compose/monitoring.yml")
    rootfs = [
        a.split("=", 1)[1]
        for a in mon["services"]["node-exporter"]["command"]
        if a.startswith("--path.rootfs=")
    ]
    assert rootfs, "node-exporter must run with --path.rootfs"
    with open(_path("grafana/provisioning/dashboards/homelab-overview.json")) as fh:
        dash = json.load(fh)
    exprs = [t["expr"] for p in dash["panels"] for t in p["targets"]]
    assert any('mountpoint="/"' in e for e in exprs), (
        'no panel queries the host root filesystem as mountpoint="/"'
    )
    for expr in exprs:
        for mp in re.findall(r'mountpoint="([^"]*)"', expr):
            assert not mp.startswith(rootfs[0]), (
                f"query filters on mountpoint={mp!r}, but node-exporter strips "
                f"the {rootfs[0]!r} prefix: {expr}"
            )


def test_prometheus_scrapes_all_exporters():
    prom = _load_yaml("prometheus/prometheus.yml")
    jobs = {c["job_name"] for c in prom["scrape_configs"]}
    assert {"node-exporter", "cadvisor", "traefik"} <= jobs


def test_dashboard_json_is_valid_with_panels():
    with open(_path("grafana/provisioning/dashboards/homelab-overview.json")) as fh:
        dash = json.load(fh)
    assert dash["title"]
    assert len(dash["panels"]) >= 3
    for panel in dash["panels"]:
        assert panel["targets"], f"panel {panel['title']} has no query"


def test_backup_scripts_executable_and_use_restic():
    for name in ["backup.sh", "entrypoint.sh", "restore.sh"]:
        p = _path("backup", name)
        assert os.path.exists(p), f"{name} missing"
        mode = os.stat(p).st_mode
        assert mode & stat.S_IXUSR, f"{name} is not executable"
    with open(_path("backup", "backup.sh")) as fh:
        body = fh.read()
    assert "restic backup" in body
    assert "restic forget" in body


def test_backup_runs_on_a_schedule():
    backup = _load_yaml("compose/backup.yml")
    env = backup["services"]["backup"]["environment"]
    assert any(e.startswith("BACKUP_CRON=") for e in env)


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_docker_compose_config_renders():
    if subprocess.run(
        ["docker", "compose", "version"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode != 0:
        pytest.skip("docker compose plugin unavailable")
    res = subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "config", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
