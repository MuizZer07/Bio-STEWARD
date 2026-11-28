"""0.22.0 X04: licence use kinds: `[licence] use = { "<package>" = "linked" | "bundled" | "invoked" }`, read by the
compatibility check (R-80). The item's Verify list and the parts around it.

Regenerate the goldens after an intended change: STEWARD_UPDATE_GOLDENS=1 pytest tests/test_v0220_licence_use.py
"""

import json
import os
from types import SimpleNamespace

import pytest

from conftest import codes, results
from test_interface import GOLDEN, _golden_bytes, machine_example  # noqa: F401
from test_interface_w02 import _valid
from test_v0120_features import gsh, xproj  # noqa: F401
from test_v0190_licence import _lock, _pkg, _setup


def _r80(rep):
    return results(rep, "R-80")[0]


def _details(r, code):
    return [d for d in r["details"] if d["code"] == code]


def _add_copyleft(x, use=None):
    """The fixture project, public and permissive-only, with a GPL-3.0 package in the lockfile; `use` declares it."""
    extra = f'use = {{ copyleft = "{use}" }}\n' if use else ""
    _setup(x, distribution="public", policy="permissive-only", extra=extra)
    _pkg(x, "copyleft", "2.0", "GPL-3.0-or-later")
    _lock(x, [("goodlib", "1.0"), ("copyleft", "2.0")])


# ---------------------------------------------------------------- the item's Verify list
def test_X04_verify_1_an_imported_gpl_package_fails_named_and_the_pre_commit_hook_reports_it(cli, xproj):
    _setup(xproj, distribution="public", policy="permissive-only")
    cli("licence", "notices", "--write")
    gsh(xproj, "git", "add", "-A")
    gsh(xproj, "git", "commit", "-qm", "base")
    assert cli("hooks", "run", "pre-commit")[0] == 0
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-or-later")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    cli("licence", "notices", "--write")
    gsh(xproj, "git", "add", "-A")
    _, rep = cli.check(xproj, "licence")
    r = _r80(rep)
    assert r["status"] == "FAIL"
    assert [d["value"] for d in _details(r, "R-80.incompatible")] == ["copyleft 2.0"]
    assert "permissive-only" in _details(r, "R-80.incompatible")[0]["message"]
    assert any(d["value"] == "copyleft (new) → 2.0" for d in _details(r, "R-80.changed"))
    code, out, err = cli("hooks", "run", "pre-commit")  # the commit that adds it
    assert code != 0 and "R-80" in out and "commit blocked" in err


def test_X04_verify_1_declared_as_linked_is_judged_as_undeclared(cli, xproj):
    _add_copyleft(xproj, "linked")
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = _r80(rep)
    assert r["status"] == "FAIL" and "R-80.incompatible" in codes(r)
    assert _details(r, "R-80.incompatible")[0]["message"].endswith("(declared use: linked)")


def test_X04_verify_2_only_invoked_as_a_separate_tool_is_not_a_fail_and_names_its_obligations(cli, xproj):
    _add_copyleft(xproj, "invoked")
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = _r80(rep)
    assert r["status"] == "PASS" and "R-80.incompatible" not in codes(r)
    ob = _details(r, "R-80.obligation")
    assert [d["value"] for d in ob] == ["copyleft 2.0"]
    assert "invoked as a separate tool" in ob[0]["message"] and "source offer" in ob[0]["message"]
    code, out, _ = cli("licence", "inventory", "--json")
    rows = {x["name"]: x for x in json.loads(out)["dependencies"]}
    assert code == 0 and rows["copyleft"]["use"] == "invoked" and rows["copyleft"]["status"] == "PASS_OBLIGATION"
    assert "use" not in rows["goodlib"]  # a package not named in [licence] use has no use key, as in 0.21


def test_X04_verify_3_a_policy_that_allows_copyleft_passes_the_imported_package(cli, xproj):
    _setup(xproj, distribution="public", policy="gpl-compatible")
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-or-later")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = _r80(rep)
    assert r["status"] == "PASS" and "R-80.incompatible" not in codes(r)
    assert [d["value"] for d in _details(r, "R-80.obligation")] == ["copyleft 2.0"]


# ---------------------------------------------------------------- around the Verify list
def test_X04_bundled_is_judged_as_linked():
    from steward import licence as li

    cfg = SimpleNamespace(licence=SimpleNamespace(distribution="public", policy="permissive-only", allow=[], deny=[]))
    for expr in ("GPL-3.0-only", "LGPL-2.1-or-later", "AGPL-3.0-only", "MIT", "LicenseRef-X"):
        assert li.verdict(expr, cfg, "bundled") == li.verdict(expr, cfg, "linked") == li.verdict(expr, cfg)


@pytest.mark.parametrize("expr,distribution,status", [
    ("GPL-3.0-only", "public", "PASS_OBLIGATION"),
    ("LGPL-3.0-only", "public", "PASS_OBLIGATION"),
    ("AGPL-3.0-only", "network", "PASS_OBLIGATION"),
    ("AGPL-3.0-only", "public", "PASS_OBLIGATION"),
    ("GPL-2.0-only", "internal", "PASS_OBLIGATION"),
    ("MIT", "public", "PASS"),
    ("LicenseRef-Proprietary", "public", "UNKNOWN"),  # an unknown licence stays unknown, whatever the use
    ("GPL-3.0-only AND LicenseRef-X", "public", "UNKNOWN"),
])
def test_X04_invoked_under_permissive_only(expr, distribution, status):
    from steward import licence as li

    cfg = SimpleNamespace(licence=SimpleNamespace(distribution=distribution, policy="permissive-only", allow=[], deny=[]))
    st, why = li.verdict(expr, cfg, "invoked")
    assert st == status
    if st == "PASS_OBLIGATION":
        assert "invoked as a separate tool" in why


def test_X04_the_deny_list_wins_for_an_invoked_package():
    from steward import licence as li

    cfg = SimpleNamespace(licence=SimpleNamespace(distribution="public", policy="gpl-compatible", allow=[],
                                                  deny=["GPL-3.0*"]))
    assert li.verdict("GPL-3.0-or-later", cfg, "invoked")[0] == "FAIL"


def test_X04_names_match_as_installers_compare_them_and_a_stale_one_is_a_note(cli, xproj):
    _setup(xproj, distribution="public", policy="permissive-only",
           extra='use = { "Copy_Left" = "invoked", "gone-tool" = "invoked" }\n')
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-or-later")
    _pkg(xproj, "copy-left", "2.0", "GPL-3.0-or-later")
    _lock(xproj, [("goodlib", "1.0"), ("copy-left", "2.0")])
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    r = _r80(rep)
    assert r["status"] == "PASS"
    assert [d["value"] for d in _details(r, "R-80.use_unmatched")] == ["gone-tool"]


def test_X04_two_spellings_of_one_package_are_refused(cli, xproj):
    _setup(xproj, extra='use = { "copy-left" = "invoked", "Copy_Left" = "linked" }\n')
    code, out, err = cli("check", "--summary")
    assert code != 0 and "name the same package" in out + err


def test_X04_an_unknown_use_kind_is_refused(cli, xproj):
    _setup(xproj, extra='use = { copyleft = "called" }\n')
    code, out, err = cli("check", "--summary")
    assert code != 0 and "use" in out + err


def test_X04_an_exception_still_applies_to_a_linked_package(cli, xproj):
    import datetime as dt

    _add_copyleft(xproj, "bundled")
    (xproj / "development").mkdir(exist_ok=True)
    (xproj / "development/licence-exceptions.toml").write_text(
        'schema = "steward.licence-exceptions/1"\n[[exception]]\ntarget = "copyleft"\nlicence = "GPL-3.0-or-later"\n'
        f'reason = "replaced in 2.0"\napprover = "the maintainer"\ndate = {dt.date.today()}\n'
        f'expires = {dt.date.today() + dt.timedelta(days=30)}\n')
    with open(xproj / "steward.toml", "a") as f:
        f.write('exceptions = "development/licence-exceptions.toml"\n')
    cli("licence", "notices", "--write")
    _, rep = cli.check(xproj, "licence")
    assert _r80(rep)["status"] == "PASS" and "R-80.exception" in codes(_r80(rep))


def test_X04_without_use_the_inventory_is_as_before(cli, xproj):
    _setup(xproj, distribution="public", policy="permissive-only")
    _pkg(xproj, "copyleft", "2.0", "GPL-3.0-or-later")
    _lock(xproj, [("goodlib", "1.0"), ("copyleft", "2.0")])
    _, out, _ = cli("licence", "inventory", "--json")
    rows = json.loads(out)["dependencies"]
    assert all(set(x) == {"name", "version", "licence", "how", "status", "why"} for x in rows)
    assert {x["name"]: x["why"] for x in rows}["copyleft"] == (
        "GPL-3.0-or-later: strong copyleft: distributing a combined work requires the whole under compatible terms; "
        "not allowed by the permissive-only policy for a public project")


# ---------------------------------------------------------------- goldens on both worked examples
def test_X04_licence_inventory_with_use_goldens(cli, machine_example):  # noqa: F811
    name, root = machine_example
    toml = root / "steward.toml"
    text = toml.read_text(encoding="utf-8")
    old = 'site_packages = []\nlockfile = "fixture-requirements.txt"\n'
    assert old in text
    toml.write_text(text.replace(old, 'site_packages = ["fixture-env"]\nlockfile = "fixture-requirements.txt"\n'
                                      'policy = "permissive-only"\ndistribution = "public"\n'
                                      'use = { "fixture-tool" = "invoked", "fixture-lib" = "bundled" }\n'),
                    encoding="utf-8")
    (root / "fixture-requirements.txt").write_text("fixture==1\nfixture-tool==3.1\nfixture-lib==0.4\n",
                                                   encoding="utf-8")
    for pkg, version, lic in (("fixture-tool", "3.1", "GPL-3.0-or-later"), ("fixture-lib", "0.4", "MIT")):
        d = root / "fixture-env" / f"{pkg.replace('-', '_')}-{version}.dist-info"
        d.mkdir(parents=True)
        (d / "METADATA").write_text(f"Metadata-Version: 2.4\nName: {pkg}\nVersion: {version}\n"
                                    f"License-Expression: {lic}\n", encoding="utf-8")
    code, out, err = cli("licence", "inventory", "--repo", root, "--format", "json")
    doc = _valid(json.loads(out))
    assert doc["schema"] == "steward.licence_inventory/0.1"
    rows = {x["name"]: x for x in doc["dependencies"]}
    assert rows["fixture-tool"]["status"] == "PASS_OBLIGATION" and rows["fixture-tool"]["use"] == "invoked"
    assert rows["fixture-lib"]["use"] == "bundled" and "use" not in rows["fixture"]
    path = GOLDEN / f"{name}.licence-use.json"
    if os.environ.get("STEWARD_UPDATE_GOLDENS"):
        path.write_text(out, encoding="utf-8", newline="\n")
    assert out == path.read_text(encoding="utf-8") == _golden_bytes(doc), f"output differs from {path}"
    assert code != 0  # the fixture package is not installed: UNKNOWN, as without a use
