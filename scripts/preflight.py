#!/usr/bin/env python
"""Make the environment runnable, or explain precisely why it cannot be.

The original Phase-2 workflow aborted whenever the backend or frontend was down.
For an unattended loop that is the wrong behaviour: the loop should repair what
it can and only stop for things a human genuinely has to decide.

Checks, in order (each either self-heals or reports):
  1. venv + dependencies + chromium + ffmpeg
  2. .env present and pointing at the right ports
  3. backend reachable          → restarted via docker if it is a container
  4. frontend reachable         → reported (starting a dev server is the one
                                  thing worth asking about, since it holds a
                                  terminal and may need a build)
  5. SuperAdmin usable          → seeded via the backend container
  6. scenarios + feature queue valid
  7. app repos clean of commits — the guardrail

Exit codes: 0 = ready, 1 = blocked (see the JSON report), 2 = internal error.

    python scripts/preflight.py            # human-readable + JSON report
    python scripts/preflight.py --json     # JSON only (for workflow agents)
    python scripts/preflight.py --no-heal  # diagnose without changing anything
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ROOT, get_settings  # noqa: E402


REPORT_PATH = ROOT / "state" / "preflight.json"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    healed: bool = False
    blocking: bool = True


@dataclass
class Report:
    ready: bool = False
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.blocking]


def http_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return (res.status < 500, f"HTTP {res.status}")
    except urllib.error.HTTPError as e:
        # 3xx/4xx still means something is listening and serving.
        return (e.code < 500, f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        return (False, str(e))


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def check_tooling(report: Report, heal: bool) -> None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        if not heal:
            report.add(Check("venv", False, "missing .venv"))
            return
        proc = run([sys.executable, "-m", "venv", str(ROOT / ".venv")], timeout=180)
        if proc.returncode != 0:
            report.add(Check("venv", False, proc.stderr[-400:]))
            return
        run([str(ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-r",
             str(ROOT / "requirements.txt")], timeout=900)
        report.add(Check("venv", True, "created and populated", healed=True))
    else:
        report.add(Check("venv", True, str(venv_python)))

    probe = run([str(venv_python), "-c", "import playwright, pytest, PIL, yaml"])
    if probe.returncode != 0 and heal:
        run([str(ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-r",
             str(ROOT / "requirements.txt")], timeout=900)
        probe = run([str(venv_python), "-c", "import playwright, pytest, PIL, yaml"])
    report.add(Check("deps", probe.returncode == 0, probe.stderr[-300:],
                     healed=probe.returncode == 0 and heal))

    chromium = run([str(venv_python), "-c",
                    "from playwright.sync_api import sync_playwright\n"
                    "with sync_playwright() as p: print(p.chromium.executable_path)"])
    if chromium.returncode != 0 or not Path(chromium.stdout.strip() or "/nonexistent").exists():
        if heal:
            run([str(ROOT / ".venv" / "bin" / "playwright"), "install", "chromium"], timeout=900)
            chromium = run([str(venv_python), "-c",
                            "from playwright.sync_api import sync_playwright\n"
                            "with sync_playwright() as p: print(p.chromium.executable_path)"])
    ok = chromium.returncode == 0 and Path(chromium.stdout.strip() or "/nonexistent").exists()
    report.add(Check("chromium", ok, chromium.stdout.strip()[-200:] or chromium.stderr[-200:]))

    has_ffmpeg = shutil.which("ffmpeg") is not None
    report.add(Check(
        "ffmpeg", has_ffmpeg,
        "install with `brew install ffmpeg`" if not has_ffmpeg else shutil.which("ffmpeg"),
        blocking=False,  # tests still run; only video rendering stops
    ))


def check_env(report: Report) -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        report.add(Check(".env", False, "missing — copy .env.example to .env"))
        return
    settings = get_settings()
    report.add(Check(".env", True,
                     f"backend={settings.backend_api_url} frontend={settings.frontend_base_url}"))


def check_backend(report: Report, heal: bool) -> None:
    settings = get_settings()
    url = f"{settings.backend_api_url}/roles/"
    ok, detail = http_ok(url)
    if ok:
        report.add(Check("backend", True, detail))
        return

    container = settings.backend_container.strip()
    if not heal or not container or shutil.which("docker") is None:
        report.add(Check("backend", False,
                         f"unreachable at {url} ({detail}); "
                         f"start it or set BACKEND_CONTAINER"))
        return

    run(["docker", "start", container], timeout=90)
    for _ in range(20):
        time.sleep(3)
        ok, detail = http_ok(url)
        if ok:
            report.add(Check("backend", True, f"restarted container {container}", healed=True))
            return
    report.add(Check("backend", False,
                     f"container {container} did not become healthy: {detail}"))


def check_frontend(report: Report) -> None:
    settings = get_settings()
    url = f"{settings.frontend_base_url}/auth/login"
    ok, detail = http_ok(url, timeout=10)
    report.add(Check(
        "frontend", ok,
        detail if ok else
        f"unreachable at {url} ({detail}); run `{settings.frontend_start_cmd}` "
        f"in {settings.frontend_repo_path or 'the frontend repo'}",
    ))


def check_qa_mode(report: Report, heal: bool) -> None:
    """QA mode must be on, or no created user's password is ever knowable.

    Enabled by a flag file in the backend repo root rather than an env var: the
    container reads env_file only at creation, but the repo is bind-mounted, so
    the file can be flipped without recreating the container.
    """
    settings = get_settings()
    if not settings.backend_repo_path or not Path(settings.backend_repo_path).exists():
        report.add(Check("qa_mode", False,
                         "BACKEND_REPO_PATH is unset, so QA mode cannot be enabled"))
        return

    flag = Path(settings.backend_repo_path) / settings.backend_qa_flag_file
    if not flag.exists():
        if not heal:
            report.add(Check("qa_mode", False, f"flag file missing: {flag}"))
            return
        flag.touch()
        time.sleep(10)  # let uvicorn --reload pick it up

    # Trust the running app, not the file: prove the header actually comes back.
    url = f"{settings.backend_api_url}/users/forgot-password"
    probe = run(["curl", "-s", "-m", "25", "-D", "-", "-o", "/dev/null",
                 "-X", "POST", url, "-H", "Content-Type: application/json",
                 "-d", json.dumps({"email": settings.superadmin_email})], timeout=60)
    active = "x-test-mode" in probe.stdout.lower()
    report.add(Check(
        "qa_mode", active,
        "test_mode data confirmed on live responses" if active else
        f"flag file present at {flag} but responses carry no X-Test-Mode header; "
        f"has the backend reloaded? Try: docker restart schoolapp",
    ))


def check_superadmin(report: Report, heal: bool) -> None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        report.add(Check("superadmin", False, "no venv yet"))
        return
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from config.settings import get_settings\n"
        "from tests.fixtures.api_client import BackendAPI\n"
        "from tests.fixtures.bootstrap import ensure_superadmin\n"
        "s = get_settings()\n"
        "with BackendAPI(s) as api:\n"
        "    creds = ensure_superadmin(api, s)\n"
        "    print('SUPERADMIN_OK', creds.user_id)\n"
    ) % str(ROOT)
    proc = run([str(venv_python), "-c", script], timeout=180)
    ok = "SUPERADMIN_OK" in proc.stdout
    report.add(Check("superadmin", ok,
                     proc.stdout.strip()[-200:] if ok else
                     (proc.stderr.strip()[-500:] or proc.stdout.strip()[-500:])))


def check_queue(report: Report) -> None:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        report.add(Check("queue", False, "no venv yet"))
        return
    if not (ROOT / "config" / "features.yaml").exists():
        run([str(venv_python), str(ROOT / "scripts" / "build_feature_queue.py")])
    if not (ROOT / "state" / "feature_ledger.json").exists():
        run([str(venv_python), str(ROOT / "scripts" / "ledger.py"), "init"])
    proc = run([str(venv_python), str(ROOT / "scripts" / "ledger.py"), "stats"])
    ok = proc.returncode == 0
    detail = ""
    if ok:
        try:
            stats = json.loads(proc.stdout)
            detail = (f"{stats['done']}/{stats['total']} done, "
                      f"{stats['blocked']} blocked, {stats['remaining']} remaining")
        except json.JSONDecodeError:
            detail = proc.stdout[-200:]
    report.add(Check("queue", ok, detail or proc.stderr[-200:]))


BASELINE_PATH = ROOT / "state" / "repo_baseline.json"


TEST_DATA_CEILING = 60


def check_test_data(report: Report, heal: bool) -> None:
    """Keep leftover test schools well under the API's 100-row list cap.

    `/school_profile/` and `/feature-packs/` both return at most 100 rows, and
    teardown cannot delete anything (the ORM delete is broken — see
    scripts/cleanup_test_data.py). Once the leftovers reach that cap, a freshly
    created feature pack falls outside the page the assign-pack dialog renders
    and provisioning dies with a selector timeout that looks nothing like the
    real cause. Swept automatically so a long run cannot walk into it.
    """
    venv_python = ROOT / ".venv" / "bin" / "python"
    cleanup = ROOT / "scripts" / "cleanup_test_data.py"
    if not venv_python.exists() or not cleanup.exists():
        report.add(Check("test_data", True, "cleanup script unavailable", blocking=False))
        return

    proc = run([str(venv_python), str(cleanup)], timeout=180)
    if proc.returncode != 0:
        report.add(Check("test_data", True,
                         f"could not read counts: {proc.stderr.strip()[-200:]}",
                         blocking=False))
        return

    first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    try:
        schools = int(first.split("TEST schools:")[1].split()[0])
    except (IndexError, ValueError):
        report.add(Check("test_data", True, first[:160], blocking=False))
        return

    if schools <= TEST_DATA_CEILING:
        report.add(Check("test_data", True, f"{schools} leftover test school(s)",
                         blocking=False))
        return
    if not heal:
        report.add(Check("test_data", False,
                         f"{schools} leftover test schools — near the 100-row list "
                         f"cap; run scripts/cleanup_test_data.py --yes"))
        return

    swept = run([str(venv_python), str(cleanup), "--yes"], timeout=300)
    report.add(Check("test_data", swept.returncode == 0,
                     swept.stdout.strip().splitlines()[-1] if swept.stdout.strip()
                     else swept.stderr[-200:],
                     healed=True, blocking=False))


def check_workflow_scripts(report: Report) -> None:
    """Catch workflow syntax errors before a launch, not after.

    A workflow script only parses when it is actually launched — which happens
    after preflight passes and agents have started. A stray backtick in prose
    therefore surfaces at the most expensive possible moment.
    """
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        report.add(Check("workflows", True, "no venv yet", blocking=False))
        return
    proc = run([str(venv_python), str(ROOT / "scripts" / "check_workflows.py")])
    ok = proc.returncode == 0
    report.add(Check("workflows", ok,
                     "all workflow scripts parse" if ok
                     else proc.stdout.strip()[-600:]))


def check_repos_uncommitted(report: Report) -> None:
    """The guardrail: agents may edit the app repos, never commit to them.

    The first run records each repo's HEAD. Every later run compares against
    that baseline, so a stray `git commit` surfaces immediately instead of being
    discovered days later. Working-tree changes are expected and fine — they are
    the fixes. Only a moved HEAD is a violation.
    """
    settings = get_settings()
    baseline = (json.loads(BASELINE_PATH.read_text())
                if BASELINE_PATH.exists() else {})
    updated = dict(baseline)

    for label, path in (("backend_repo", settings.backend_repo_path),
                        ("frontend_repo", settings.frontend_repo_path)):
        if not path or not Path(path).exists():
            report.add(Check(label, True, "not configured — guardrail inactive",
                             blocking=False))
            continue

        head = run(["git", "-C", path, "rev-parse", "HEAD"]).stdout.strip()
        status = run(["git", "-C", path, "status", "--porcelain"]).stdout
        dirty = len([ln for ln in status.splitlines() if ln.strip()])

        recorded = baseline.get(label)
        if recorded is None:
            updated[label] = head
            report.add(Check(label, True,
                             f"baseline recorded at {head[:9]} "
                             f"({dirty} uncommitted files)", blocking=False))
        elif recorded != head:
            # A moved HEAD alone does not mean an agent committed — a teammate
            # pulling upstream looks identical. What distinguishes them is
            # whether any commit exists that no remote has: that is the actual
            # violation. Upstream movement is adopted with a loud note instead
            # of halting the run.
            local = run(["git", "-C", path, "log", f"{recorded}..HEAD",
                         "--not", "--remotes", "--pretty=%h %an %s"]).stdout.strip()
            if local:
                report.add(Check(
                    label, False,
                    f"GUARDRAIL VIOLATION: HEAD moved {recorded[:9]} → {head[:9]} "
                    f"and these commits exist on no remote — an agent committed "
                    f"to the app repo:\n{local[:600]}",
                ))
            else:
                incoming = run(["git", "-C", path, "log", f"{recorded}..HEAD",
                                "--pretty=%h %an %s"]).stdout.strip()
                count = len(incoming.splitlines())
                updated[label] = head
                report.add(Check(
                    label, True,
                    f"upstream moved {recorded[:9]} → {head[:9]} "
                    f"({count} commit(s) from a pull, none local) — baseline "
                    f"adopted. NOTE: the code under test changed mid-run:\n"
                    f"{incoming[:400]}",
                    blocking=False,
                ))
        else:
            report.add(Check(label, True,
                             f"HEAD unchanged at {head[:9]} "
                             f"({dirty} uncommitted files — expected)",
                             blocking=False))

    if updated != baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(updated, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--no-heal", action="store_true", help="diagnose without changing anything")
    args = parser.parse_args()
    heal = not args.no_heal

    report = Report()
    check_tooling(report, heal)
    check_env(report)
    check_backend(report, heal)
    check_frontend(report)
    if not report.blockers:
        check_qa_mode(report, heal)
        check_superadmin(report, heal)
        check_queue(report)
        check_test_data(report, heal)
        check_workflow_scripts(report)
    check_repos_uncommitted(report)
    report.ready = not report.blockers

    payload = {"ready": report.ready, "checks": [asdict(c) for c in report.checks]}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2))

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for c in report.checks:
            mark = "✓" if c.ok else ("!" if not c.blocking else "✗")
            healed = " (healed)" if c.healed else ""
            print(f"{mark} {c.name}{healed}: {c.detail}")
        print()
        print("READY" if report.ready else
              f"BLOCKED: {', '.join(c.name for c in report.blockers)}")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
