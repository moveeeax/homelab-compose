"""Validation tests for the homelab-compose stack.

These run without bringing containers up: they parse every YAML/JSON file,
cross-check that the compose files only reference variables documented in
.env.example, run backup.sh against a stub restic to check the metrics it
writes, and (when Docker is available) render the merged compose model with
`docker compose config`.
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
        "prometheus/rules/backup.yml",
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


BACKUP_METRICS = [
    "homelab_backup_last_success_timestamp",
    "homelab_backup_duration_seconds",
    "homelab_backup_bytes_added",
    "homelab_backup_snapshot_count",
    "homelab_backup_last_run_timestamp",
    "homelab_backup_last_run_success",
    "homelab_backup_stale_after_seconds",
]


def _volume_target(volumes, source):
    for v in volumes:
        parts = v.split(":")
        if parts[0] == source:
            return parts[1]
    return None


def test_backup_metrics_volume_shared_with_node_exporter():
    backup = _load_yaml("compose/backup.yml")
    mon = _load_yaml("compose/monitoring.yml")
    svc = backup["services"]["backup"]
    assert "backup-metrics" in backup["volumes"]
    env = dict(e.split("=", 1) for e in svc["environment"])
    assert _volume_target(svc["volumes"], "backup-metrics") == env["BACKUP_METRICS_DIR"]

    ne = mon["services"]["node-exporter"]
    textfile = [
        a.split("=", 1)[1]
        for a in ne["command"]
        if a.startswith("--collector.textfile.directory=")
    ]
    assert textfile, "node-exporter must run with --collector.textfile.directory"
    mounted = [v for v in ne["volumes"] if v.startswith("backup-metrics:")]
    assert mounted == [f"backup-metrics:{textfile[0]}:ro"]


def test_prometheus_loads_backup_alert_rules():
    prom = _load_yaml("prometheus/prometheus.yml")
    mon = _load_yaml("compose/monitoring.yml")
    target = _volume_target(mon["services"]["prometheus"]["volumes"], "../prometheus/rules")
    assert target, "prometheus/rules is not mounted into prometheus"
    assert f"{target}/*.yml" in prom["rule_files"]

    rules = _load_yaml("prometheus/rules/backup.yml")
    alerts = {r["alert"]: r for g in rules["groups"] for r in g["rules"]}
    assert {"BackupStale", "BackupFailed", "BackupMetricsMissing"} <= set(alerts)
    stale = alerts["BackupStale"]["expr"]
    assert "homelab_backup_last_success_timestamp" in stale
    assert "homelab_backup_stale_after_seconds" in stale


def test_backup_metrics_used_by_rules_and_dashboard_are_written():
    with open(_path("backup", "metrics.sh")) as fh:
        written = set(re.findall(r"\b(homelab_backup_[a-z_]+)", fh.read()))
    assert set(BACKUP_METRICS) <= written

    with open(_path("grafana/provisioning/dashboards/homelab-overview.json")) as fh:
        dash = json.load(fh)
    exprs = [t["expr"] for p in dash["panels"] for t in p["targets"]]
    rules = _load_yaml("prometheus/rules/backup.yml")
    exprs += [r["expr"] for g in rules["groups"] for r in g["rules"]]
    used = {m for e in exprs for m in re.findall(r"\b(homelab_backup_[a-z_]+)", e)}
    assert used, "no dashboard panel or alert reads the backup metrics"
    assert used <= written, f"queried but never written: {sorted(used - written)}"
    assert any("homelab_backup_last_success_timestamp" in e for e in exprs)


def test_backup_image_ships_metrics_helper():
    with open(_path("backup", "Dockerfile")) as fh:
        dockerfile = fh.read()
    assert "COPY metrics.sh /usr/local/bin/metrics.sh" in dockerfile
    apk = next(l for l in dockerfile.splitlines() if "apk add" in l).split()
    assert {"jq", "curl"} <= set(apk)


STUB_RESTIC = """#!/usr/bin/env bash
# Fake restic: fails the subcommand named in STUB_RESTIC_FAIL with exit 3.
echo "$*" >> "$STUB_LOG"
[ "$1" = "${STUB_RESTIC_FAIL:-}" ] && exit 3
case "$1" in
  backup)
    echo '{"message_type":"status","percent_done":0.5}'
    echo '{"message_type":"summary","files_new":2,"files_changed":1,"data_added":4096,"snapshot_id":"abc123"}'
    ;;
  snapshots)
    if [ "${2:-}" = "--compact" ]; then echo "abc123  homelab"; else echo '[{},{},{}]'; fi
    ;;
esac
"""

STUB_CURL = """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_CURL_LOG"
"""


def _parse_prom(path):
    values = {}
    with open(path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            name, value = line.split()
            values[name] = float(value)
    return values


@pytest.fixture
def backup_env(tmp_path):
    if shutil.which("bash") is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are needed to run backup.sh")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in [("restic", STUB_RESTIC), ("curl", STUB_CURL)]:
        stub = bindir / name
        stub.write_text(body)
        stub.chmod(0o755)
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "HOSTNAME": "homelab",
        "BACKUP_METRICS_DIR": str(tmp_path / "metrics"),
        "BACKUP_STALE_AFTER_SECONDS": "3600",
        "STUB_LOG": str(tmp_path / "restic.log"),
        "STUB_CURL_LOG": str(tmp_path / "curl.log"),
    }

    def run(**extra):
        return subprocess.run(
            ["bash", _path("backup", "backup.sh")],
            env={**env, **extra}, capture_output=True, text=True,
        )

    return tmp_path, run


def test_backup_success_writes_metrics(backup_env):
    tmp, run = backup_env
    res = run()
    assert res.returncode == 0, res.stderr
    m = _parse_prom(tmp / "metrics" / "backup.prom")
    assert set(m) == set(BACKUP_METRICS)
    assert m["homelab_backup_last_run_success"] == 1
    assert m["homelab_backup_bytes_added"] == 4096
    assert m["homelab_backup_snapshot_count"] == 3
    assert m["homelab_backup_stale_after_seconds"] == 3600
    assert m["homelab_backup_last_success_timestamp"] == m["homelab_backup_last_run_timestamp"]
    assert m["homelab_backup_duration_seconds"] >= 0
    assert not list((tmp / "metrics").glob("*.tmp")), "temp file left behind"
    assert not (tmp / "curl.log").exists(), "pinged without BACKUP_NOTIFY_URL"


def test_backup_failure_keeps_last_success_and_pings_fail(backup_env):
    tmp, run = backup_env
    url = "https://hc-ping.com/uuid"
    assert run(BACKUP_NOTIFY_URL=url).returncode == 0
    good = _parse_prom(tmp / "metrics" / "backup.prom")

    res = run(BACKUP_NOTIFY_URL=url, STUB_RESTIC_FAIL="backup")
    assert res.returncode == 3
    m = _parse_prom(tmp / "metrics" / "backup.prom")
    assert m["homelab_backup_last_run_success"] == 0
    for name in ["last_success_timestamp", "duration_seconds", "bytes_added", "snapshot_count"]:
        key = f"homelab_backup_{name}"
        assert m[key] == good[key], f"{key} changed on a failed run"
    assert m["homelab_backup_last_run_timestamp"] >= good["homelab_backup_last_run_timestamp"]

    pings = (tmp / "curl.log").read_text().splitlines()
    assert len(pings) == 2
    assert pings[0].endswith(f" {url}")
    assert pings[1].endswith(f" {url}/fail")
    assert "exit code 3" in pings[1]


def test_backup_rejects_non_numeric_stale_threshold(backup_env):
    tmp, run = backup_env
    res = run(BACKUP_STALE_AFTER_SECONDS="26h")
    assert res.returncode == 0, res.stderr
    assert "BACKUP_STALE_AFTER_SECONDS" in res.stderr
    m = _parse_prom(tmp / "metrics" / "backup.prom")
    assert m["homelab_backup_stale_after_seconds"] == 93600


def test_backup_failure_uses_explicit_fail_url(backup_env):
    tmp, run = backup_env
    res = run(
        BACKUP_NOTIFY_URL="https://ntfy.sh/topic",
        BACKUP_NOTIFY_FAIL_URL="https://ntfy.sh/topic",
        STUB_RESTIC_FAIL="forget",
    )
    assert res.returncode == 3
    m = _parse_prom(tmp / "metrics" / "backup.prom")
    assert m["homelab_backup_last_run_success"] == 0
    assert "homelab_backup_last_success_timestamp" not in m
    pings = (tmp / "curl.log").read_text().splitlines()
    assert len(pings) == 1 and pings[0].endswith(" https://ntfy.sh/topic")


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
