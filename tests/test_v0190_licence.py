"""0.19.0: licence governance (REQ-012; R-79 – R-82): the requester's Verify scenarios 1 – 7 and the parts around them."""

import datetime as dt
import json

import pytest

from conftest import codes, results
from test_v0120_features import gsh, xproj  # noqa: F401

MIT = "Permission is hereby granted, free of charge, to any person obtaining a copy of this software\n"


def _pkg(x, name, version, expr=None, classifiers=(), free=None):
    d = x / f".venv/lib/python3.11/site-packages/{name}-{version}.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if expr:
        lines.append(f"License-Expression: {expr}")
    if free:
        lines.append(f"License: {free}")
    lines += [f"Classifier: License :: OSI Approved :: {c}" for c in classifiers]
    (d / "METADATA").write_text("\n".join(lines) + "\n")


def _lock(x, pkgs):
    (x / "uv.lock").write_text("version = 1\n" + "".join(
        f'\n[[package]]\nname = "{n}"\nversion = "{v}"\n' for n, v in pkgs))


def _setup(x, distribution="public", policy="weak-copyleft-ok", extra=""):
    (x / "LICENSE").write_text(MIT)
    (x / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "1.0.0"\nlicense = "MIT"\n')
    with open(x / "steward.toml", "a") as f:
        f.write(f'\n[licence]\ndeclared = "MIT"\ndistribution = "{distribution}"\npolicy = "{policy}"\n'
                f'lockfile = "uv.lock"\n{extra}')
    _pkg(x, "goodlib", "1.0", "MIT")
    _lock(x, [("goodlib", "1.0")])


def _r(rep, rule):
    return results(rep, rule)[0]


def test_V1_a_gpl_package_in_the_lockfile_fails_and_is_named(cli, xproj):
    _setup(xproj)
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    assert _r(rep, "R-80")["status"] == "PASS"
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "base")
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-or-later")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    _, rep = cli.check(xproj, "licence")
    r = _r(rep, "R-80")
    assert r["status"] == "FAIL" and "R-80.incompatible" in codes(r)
    assert any("copyleft" in str(d.get("value")) for d in r["details"] if d["code"] == "R-80.incompatible")
    assert any(d["code"] == "R-80.changed" and "copyleft (new)" in d["value"] for d in r["details"])  # the commit view


def test_V2_a_package_without_licence_metadata_is_unknown_and_blocks(cli, xproj):
    _setup(xproj)
    _pkg(xproj, "mystery", "0.1")
    _lock(xproj, [("goodlib", "1.0"), ("mystery", "0.1")])
    cli("licence", "notices", "--write")
    code, rep = cli.check(xproj)
    assert _r(rep, "R-80")["status"] == "UNKNOWN" and code != 0


def test_V3_a_declared_gpl_port_fails_and_an_undeclared_one_is_a_hint(cli, xproj):
    _setup(xproj)
    (xproj / "src").mkdir()
    (xproj / "src/smooth.py").write_text("# Derived-from: R lowess.c (GPL-2.0-or-later)\ndef lowess(): ...\n")
    marker = "port" + "ed from"  # built, so this test file carries no marker of its own (R-82 on this repository)
    (xproj / "src/smooth2.py").write_text(f"def clowess():\n    # {marker} R's clowess\n    ...\n")
    gsh(xproj, "git", "add", "-A")
    _, rep = cli.check(xproj, "licence")
    r81 = _r(rep, "R-81")
    assert r81["status"] == "FAIL" and any(d.get("path") == "src/smooth.py" for d in r81["details"])
    r82 = _r(rep, "R-82")
    assert r82["status"] == "INCOMPLETE" and any(d.get("path") == "src/smooth2.py" for d in r82["details"])
    from steward.models import ADVISORY
    assert "R-82" in ADVISORY


def test_V4_internal_use_reports_obligations_then_public_fails_again(cli, xproj):
    _setup(xproj, distribution="internal")
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-only")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    _, rep = cli.check(xproj, "licence")
    r = _r(rep, "R-80")
    assert r["status"] == "PASS" and "R-80.obligation" in codes(r)
    t = (xproj / "steward.toml").read_text().replace('distribution = "internal"', 'distribution = "public"')
    (xproj / "steward.toml").write_text(t)
    _, rep = cli.check(xproj, "licence")
    assert _r(rep, "R-80")["status"] == "FAIL"


def test_V5_license_and_package_metadata_must_agree(cli, xproj):
    _setup(xproj)
    (xproj / "pyproject.toml").write_text('[project]\nname = "fixture"\nlicense = "Apache-2.0"\n')
    _, rep = cli.check(xproj, "licence")
    r = _r(rep, "R-79")
    assert r["status"] == "FAIL" and "R-79.mismatch" in codes(r)


def test_V6_a_valid_exception_passes_listed_and_an_expired_one_fails(cli, xproj):
    future = dt.date.today() + dt.timedelta(days=30)
    _setup(xproj, extra='exceptions = "development/licence-exceptions.toml"\n')
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-only")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    (xproj / "development").mkdir(exist_ok=True)
    exc = xproj / "development/licence-exceptions.toml"
    exc.write_text(f'schema = "steward.licence-exceptions/1"\n[[exception]]\ntarget = "copyleft"\nlicence = "GPL-3.0-only"\n'
                   f'reason = "replaced in 2.0"\napprover = "the maintainer"\ndate = 2026-11-25\nexpires = {future}\n')
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = _r(rep, "R-80")
    assert r["status"] == "PASS" and "R-80.exception" in codes(r)
    exc.write_text(exc.read_text().replace(f"expires = {future}", "expires = 2026-01-01"))
    _, rep = cli.check(xproj, "licence")
    assert _r(rep, "R-80")["status"] == "FAIL"


def test_V7_the_release_manifest_records_the_inventory_and_refuses_an_open_fail(cli, xproj):
    _setup(xproj)
    cli("licence", "notices", "--write")
    dist = xproj / "dist"
    dist.mkdir()
    (dist / "fixture-1.0.0-py3-none-any.whl").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    man = xproj / "manifest.json"
    code, out, err = cli("release", "manifest", "--version", "1.0.0", "--dist", dist, "--output", man)
    assert code == 0, err
    doc = json.loads(man.read_text())
    assert doc["licence"]["declared"] == "MIT" and doc["licence"]["dependencies"][0]["name"] == "goodlib"
    _pkg(xproj, "copyleft", "2.0", "AGPL-3.0-only")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    code, _, err = cli("release", "manifest", "--version", "1.0.0", "--dist", dist, "--output", xproj / "m2.json")
    assert code == 65 and "licence checks are open" in err


# ---------------------------------------------------------------- around the scenarios
def test_a_public_project_needs_current_notices(cli, xproj):
    _setup(xproj)
    _, rep = cli.check(xproj, "licence")
    assert "R-80.notices_missing" in codes(_r(rep, "R-80"))
    cli("licence", "notices", "--write")
    _pkg(xproj, "newlib", "3.0", "BSD-3-Clause")
    _lock(xproj, [("goodlib", "1.0"), ("newlib", "3.0")])
    _, rep = cli.check(xproj, "licence")
    assert "R-80.notices_stale" in codes(_r(rep, "R-80"))


@pytest.mark.parametrize("expr,policy,status", [
    ("MIT OR GPL-3.0-only", "permissive-only", "PASS"),
    ("MIT AND GPL-3.0-only", "permissive-only", "FAIL"),
    ("LGPL-3.0-only", "permissive-only", "FAIL"),
    ("LGPL-3.0-only", "weak-copyleft-ok", "PASS_OBLIGATION"),
    ("GPL-2.0-or-later", "gpl-compatible", "PASS_OBLIGATION"),
    ("AGPL-3.0-only", "gpl-compatible", "FAIL"),
    ("Apache-2.0 WITH LLVM-exception", "permissive-only", "PASS"),
    ("not a licence ((", "permissive-only", "UNKNOWN"),
    ("LicenseRef-Proprietary", "permissive-only", "UNKNOWN"),
])
def test_the_policy_table(expr, policy, status):
    from types import SimpleNamespace

    from steward import licence as li
    cfg = SimpleNamespace(licence=SimpleNamespace(distribution="public", policy=policy, allow=[], deny=[]))
    assert li.verdict(expr, cfg)[0] == status


def test_classifiers_and_deny_lists(cli, xproj):
    _setup(xproj, extra='deny = ["BSD-*"]\n')
    _pkg(xproj, "oldlib", "1.0", classifiers=["BSD License"])
    _lock(xproj, [("goodlib", "1.0"), ("oldlib", "1.0")])
    _, out, _ = cli("licence", "inventory", "--json")
    rows = {r["name"]: r for r in json.loads(out)["dependencies"]}
    assert rows["oldlib"]["how"] == "classifier" and rows["oldlib"]["status"] == "FAIL"


def test_cyclonedx_sbom(cli, xproj):
    _setup(xproj)
    code, out, _ = cli("licence", "notices", "--format", "cyclonedx")
    doc = json.loads(out)
    assert code == 0 and doc["bomFormat"] == "CycloneDX" and doc["components"][0]["licenses"][0]["expression"] == "MIT"


def test_licence_is_not_applicable_until_configured(cli, xproj):
    _, rep = cli.check(xproj)
    for rule in ("R-79", "R-80", "R-81", "R-82"):
        assert _r(rep, rule)["status"] == "NOT_APPLICABLE"


def test_prose_about_headers_and_markers_is_neither_a_header_nor_a_hint(cli, xproj):
    _setup(xproj)
    (xproj / "src").mkdir()
    marker = "port" + "ed from"
    (xproj / "src/doc.py").write_text('"""Files carrying `SPDX-License-Identifier:` or `Derived-from:` headers.\n'
                                      f'- **R-82**: comments such as "{marker}" are listed.\n"""\n'
                                      f'HINT = "{marker}"\n')
    (xproj / "src/ok.py").write_text("# SPDX-License-Identifier: MIT\nx = 1\n")
    gsh(xproj, "git", "add", "-A")
    _, rep = cli.check(xproj, "licence")
    assert _r(rep, "R-81")["status"] == "PASS" and _r(rep, "R-82")["status"] == "PASS"
