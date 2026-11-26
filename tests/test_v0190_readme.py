"""STW-010: generate and check a project's README from its own records."""

import json
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from conftest import append, codes, one
from steward import docsite, release
from steward.models import load_config

START = b"<!-- steward:readme:start -->"
END = b"<!-- steward:readme:end -->"
ASSETS = "docs/steward-readme"
BADGES = ("gate", "release", "studies", "open-items")


@pytest.fixture
def project(example):
    append(example, "steward.toml", """
[studies]

[release]
manifest = "release.json"

[tasks]
specs = ["work/*.md"]
archive = ["work/archived.md"]
board = "work/BOARD.md"
""")
    append(example, "development/studies/first.toml", '''
schema = "steward.study/1"
id = "first"
title = "A <tag> & study"
''')
    (example / "release.json").write_text('{"version":"1.2.3"}')
    append(example, "work/one.md", "- **ID:** DEMO-001\n- **Status:** in progress (draft)\n")
    append(example, "work/two.md", "- **ID:** DEMO-002\n- **Status:** done\n")
    append(example, "work/archived.md", "- **ID:** DEMO-003\n- **Status:** in progress\n")
    return example


def test_readme_regenerates_identically_and_keeps_the_rest_of_the_file(cli, project):
    readme = project / "README.md"
    before = b"# My project\r\n\r\n" + START + b"\r\nold\r\n" + END + b"\r\n"
    after = b"\r\nKeep this prose.\r\n"
    readme.write_bytes(before + after)
    code, _, err = cli("docs", "readme", "--repo", project)
    assert code == 0, err
    output = readme.read_bytes()
    assert output.startswith(before.split(b"old")[0])
    assert output.endswith(END + b"\r\n" + after)
    cfg = load_config(project)
    assert not docsite.scan(project, cfg, output.decode())
    assert b"What this project checks" in output
    assert b"A &lt;tag&gt; &amp; study" in output
    for value in (b"Gate snapshot: not recorded", b"Last release: 1.2.3", b"Studies: 1", b"Open items: 1"):
        assert value in output
    paths = {name: project / ASSETS / f"{name}.svg" for name in (*BADGES, "lifecycle")}
    first = {name: p.read_bytes() for name, p in paths.items()}
    for name, data in first.items():
        assert f"{ASSETS}/{name}.svg".encode() in output
        assert b"prefers-color-scheme: dark" in data
        ElementTree.fromstring(data)
        assert not docsite.scan(project, cfg, data.decode())
    assert cli("docs", "readme", "--repo", project)[0] == 0
    assert readme.read_bytes() == output
    assert {name: p.read_bytes() for name, p in paths.items()} == first


def test_r69_checks_readme_without_opt_in_to_site(cli, project):
    def check():
        return one(cli.check(project, "docs")[1], "R-69")

    assert check()["status"] == "NOT_APPLICABLE"
    assert cli("docs", "readme", "--repo", project)[0] == 0
    assert check()["status"] == "PASS"
    (project / "release.json").write_text('{"version":"1.2.4"}')
    result = check()
    assert result["status"] == "INCOMPLETE"
    assert "R-69.stale" in codes(result)
    assert {"README.md", f"{ASSETS}/release.svg"} <= {d["path"] for d in result["details"]}
    assert cli("docs", "readme", "--repo", project)[0] == 0
    (project / ASSETS / "studies.svg").unlink()
    assert "R-69.missing" in codes(check())
    assert cli("docs", "readme", "--repo", project)[0] == 0
    (project / "README.md").write_text("# Markers removed\n")
    assert "R-69.missing" in codes(check())


@pytest.mark.parametrize("report_path", [".steward/readme-check.json", ".steward/custom.json"])
def test_pypi_is_plain_and_reports_a_recorded_gate(cli, project, report_path):
    if report_path.endswith("custom.json"):
        append(project, "steward.toml", f'\n[docs]\nreadme_report = "{report_path}"\n')
    _, report = cli.check(project)
    gate = next(g for g in report["verdict"]["gates"] if g["name"] == "default")
    expected = "eligible" if gate["eligible"] else "blocked"
    append(project, report_path, json.dumps(report))
    code, out, err = cli("docs", "readme", "--pypi", "--repo", project)
    assert code == 0, err
    assert f"Gate snapshot | {expected}" in out
    assert "Plan → Run → Evidence → Paper and talk → Gate → Release" in out
    assert "A &lt;tag&gt; &amp; study" in out
    assert "mermaid" not in out and ".svg" not in out and START.decode() not in out
    assert not (project / ASSETS).exists()
    assert not (project / "README.md").exists() or START not in (project / "README.md").read_bytes()
    assert out == cli("docs", "readme", "--pypi", "--repo", project)[1]


def test_readme_and_pypi_text_pass_the_distribution_scan(cli, project):
    append(project, "steward.toml", '\n[privacy]\ndenylist_file = "private.txt"\n')
    (project / "private.txt").write_text("synthetic-private-term\n")
    assert cli("docs", "readme", "--repo", project)[0] == 0
    code, pypi, err = cli("docs", "readme", "--pypi", "--repo", project)
    assert code == 0, err
    dist = project / "dist"
    dist.mkdir()
    with ZipFile(dist / "project-1.2.3.zip", "w") as artifact:
        for rel in ["README.md", *(f"{ASSETS}/{name}.svg" for name in (*BADGES, "lifecycle"))]:
            artifact.write(project / rel, rel)
        artifact.writestr("pypi.md", pypi)
    result = release.audit_for(project, load_config(project), dist)
    assert result["findings"] == result["unscanned"] == []


def test_readme_appends_after_an_example_that_shows_the_markers(cli, project):
    readme = project / "README.md"
    original = b"# Project\n\n```md\n" + START + b"\n" + END + b"\n```\n"
    readme.write_bytes(original)
    assert cli("docs", "readme", "--repo", project)[0] == 0
    assert readme.read_bytes().startswith(original + b"\n" + START)
    assert one(cli.check(project, "docs")[1], "R-69")["status"] == "PASS"


def test_r69_tracks_the_site_and_readme_together(cli, project):
    append(project, "steward.toml", '\n[docs]\npublish = ["overview"]\n')
    assert cli("docs", "build", "--repo", project)[0] == 0
    assert cli("docs", "readme", "--repo", project)[0] == 0
    assert one(cli.check(project, "docs")[1], "R-69")["status"] == "PASS"
    (project / "docs/project/overview.md").unlink()
    (project / ASSETS / "gate.svg").unlink()
    details = one(cli.check(project, "docs")[1], "R-69")["details"]
    assert {d["path"] for d in details} == {"docs/project/overview.md", f"{ASSETS}/gate.svg"}


def test_refuses_linked_assets_before_writing_any_output(cli, project, tmp_path):
    assets = project / ASSETS
    assets.parent.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    assets.symlink_to(outside, target_is_directory=True)
    readme = project / "README.md"
    before = START + b"\n\n" + END + b"\n"
    readme.write_bytes(before)
    assert cli("docs", "readme", "--repo", project)[0] == 65
    assert readme.read_bytes() == before
    assert list(outside.iterdir()) == []
    assert one(cli.check(project, "docs")[1], "R-69")["status"] == "FAIL"


@pytest.mark.parametrize("marker_lines", [(START,), (END, START), (START, START, END)])
def test_invalid_markers_do_not_write_anything(cli, project, marker_lines):
    readme = project / "README.md"
    before = b"\n".join(marker_lines) + b"\n"
    readme.write_bytes(before)
    assert cli("docs", "readme", "--repo", project)[0] == 65
    assert readme.read_bytes() == before
    assert not (project / ASSETS).exists()
    result = one(cli.check(project, "docs")[1], "R-69")
    assert result["status"] == "FAIL"
    assert "R-69.readme_invalid" in codes(result)


def test_readme_scan_refuses_private_record_text_before_escaping(cli, project):
    append(project, "steward.toml", '\n[privacy]\ndenylist_file = "private.txt"\n')
    (project / "private.txt").write_text("A <tag> & study\n")
    readme = project / "README.md"
    before = b"# Project\n\n" + START + b"\n\n" + END + b"\n"
    readme.write_bytes(before)
    code, _, err = cli("docs", "readme", "--repo", project)
    assert code == 65 and "A <tag>" not in err
    assert readme.read_bytes() == before
    assert not (project / ASSETS).exists()
    assert cli("docs", "readme", "--pypi", "--repo", project)[0] == 65
    assert "R-69.private" in codes(one(cli.check(project, "docs")[1], "R-69"))


def test_r69_scans_the_generated_bytes_and_leaves_project_prose_to_its_own_checks(cli, project):
    append(project, "steward.toml", '\n[privacy]\ndenylist_file = "private.txt"\n')
    (project / "private.txt").write_text("only-in-prose\n")
    readme = project / "README.md"
    original = b"# Project\n\nonly-in-prose\n"
    readme.write_bytes(original)
    assert cli("docs", "readme", "--repo", project)[0] == 0
    assert readme.read_bytes().startswith(original)
    assert one(cli.check(project, "docs")[1], "R-69")["status"] == "PASS"
    asset = project / ASSETS / "gate.svg"
    asset.write_bytes(asset.read_bytes() + b"<!-- /" b"home/synthetic-user/example -->\n")  # scrub: allow; steward: allow R-07 (synthetic)
    result = one(cli.check(project, "docs")[1], "R-69")
    assert result["status"] == "FAIL" and "R-69.private" in codes(result)


def test_AF17_a_backtick_line_with_a_backtick_in_its_info_string_opens_no_fence():
    from steward import docreadme as dr
    data = b"# T\n``` not `a fence\n" + dr.START + b"\nblock\n" + dr.END + b"\n"
    assert dr._markers(data) is not None
    fenced = b"```\n" + dr.START + b"\n" + dr.END + b"\n```\n"
    assert dr._markers(fenced) is None  # markers inside a real fence are an example, not the block
