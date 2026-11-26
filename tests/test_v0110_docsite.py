"""0.11.0: a documentation site for each project (RELEASE_v0.11.0_SPEC)."""

import os
import shutil

import pytest

from conftest import EXAMPLE, codes, one


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "toy"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns(".steward", "__pycache__", "*.aux", "*.fls", "*.log"))
    with open(root / "steward.toml", "a") as f:
        f.write('\n[docs]\ntitle = "Toy benchmark"\n')
    monkeypatch.chdir(root)
    return root


def test_D2_init_writes_the_site_skeleton_and_never_overwrites(cli, proj):
    code, out, err = cli("docs", "init", "--pages")
    assert code == 0, err
    assert (proj / "mkdocs.yml").is_file() and (proj / "docs/index.md").is_file()
    assert (proj / ".github/workflows/steward-docs.yml").is_file()
    (proj / "docs/index.md").write_text("mine\n")
    cli("docs", "init", "--pages")
    assert (proj / "docs/index.md").read_text() == "mine\n"


def test_D3_D5_build_writes_each_kind_from_the_records_and_is_deterministic(cli, proj):
    assert cli("docs", "build")[0] == 0
    gen = proj / "docs/project"
    pages = sorted(p.name for p in gen.glob("*.md"))
    assert pages == ["contracts.md", "index.md", "overview.md", "releases.md", "runs.md", "values.md"], pages
    contracts = (gen / "contracts.md").read_text()
    assert "expr-clf" in contracts and "Generated from" in contracts and "benchmarks/expr-clf.contract.toml" in contracts
    assert "n_samples" in (gen / "values.md").read_text()
    first = {p.name: p.read_bytes() for p in gen.glob("*.md")}
    cli("docs", "build")
    assert {p.name: p.read_bytes() for p in gen.glob("*.md")} == first


def test_D4_a_page_with_a_private_term_writes_nothing(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "secret"\nfile = "development/secret.txt"\n')
    (proj / "development/secret.txt").write_text("Responder classification\n")  # appears in the contract title
    code, _, err = cli("docs", "build")
    assert code == 65 and "secret" in err and not (proj / "docs/project").exists()


def test_D4_sealed_datasets_are_named_not_described_and_decisions_are_opt_in(cli, proj):
    text = (proj / "steward.toml").read_text().replace('[docs]\ntitle = "Toy benchmark"\n',
                                                     '[docs]\ntitle = "Toy benchmark"\npublish = ["overview", "decisions"]\n')
    (proj / "steward.toml").write_text(text)
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write('\n## 2026-11-24: publish the site\n- **Quote:** "private wording here"\n')
    assert cli("docs", "build")[0] == 0
    dec = (proj / "docs/project/decisions.md").read_text()
    assert "2026-11-24: publish the site" in dec and "private wording here" not in dec


def test_D6_r69_reports_a_stale_site_and_a_current_one(cli, proj):
    _, rep = cli.check(proj, "docs")
    assert one(rep, "R-69")["status"] == "INCOMPLETE"
    cli("docs", "build")
    _, rep = cli.check(proj, "docs")
    assert one(rep, "R-69")["status"] == "PASS", one(rep, "R-69")
    p = proj / "development/prior_work/expr-clf.prior.toml"
    c = proj / "benchmarks/expr-clf.contract.toml"
    c.write_text(c.read_text().replace('title    = "', 'title    = "Revised: ', 1))
    _, rep = cli.check(proj, "docs")
    res = one(rep, "R-69")
    assert res["status"] == "INCOMPLETE" and "R-69.stale" in codes(res), res


def test_D6_not_configured(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path, "docs")
    assert one(rep, "R-69")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- review of 4dd0531: T1 - T7
def _publish(proj, kinds):
    t = (proj / "steward.toml").read_text()
    import re
    t = re.sub(r'\[docs\]\ntitle = "Toy benchmark"\n(publish = \[.*\]\n)?', '[docs]\ntitle = "Toy benchmark"\npublish = ' +
               "[" + ", ".join(f'"{k}"' for k in kinds) + "]\n", t)
    (proj / "steward.toml").write_text(t)


def test_T1_a_retired_page_is_removed_and_flagged(cli, proj):
    _publish(proj, ["overview", "decisions"])
    cli("docs", "build")
    assert (proj / "docs/project/decisions.md").is_file()
    _publish(proj, ["overview"])
    _, rep = cli.check(proj, "docs")
    assert "R-69.retired" in codes(one(rep, "R-69"))
    cli("docs", "build")
    assert not (proj / "docs/project/decisions.md").exists()


@pytest.mark.parametrize("content, patterns", [(None, False), (b"\xff\xfe\n", False), (b"([unclosed\n", True)])
def test_T2_an_unusable_term_list_refuses_the_build(cli, proj, content, patterns):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "secret"\nfile = "development/secret.txt"\n' + ("patterns = true\n" if patterns else ""))
    if content is not None:
        (proj / "development/secret.txt").write_bytes(content)
    code, _, err = cli("docs", "build")
    assert code == 65 and not (proj / "docs/project").exists(), err


def test_T3_the_r07_waiver_never_waives_publication(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "secret"\nfile = "development/secret.txt"\n')
    (proj / "development/secret.txt").write_text("Waivedword\n")
    c = proj / "benchmarks/expr-clf.contract.toml"
    c.write_text(c.read_text().replace('title    = "', 'title    = "Waivedword ', 1).replace(
        'title    = "Waivedword', 'title    = "Waivedword', 1))
    text = c.read_text().splitlines()
    text = [l + "  # steward: allow R-07" if l.startswith("title") else l for l in text]
    c.write_text("\n".join(text) + "\n")
    assert cli("docs", "build")[0] == 65


def test_T4_the_pages_workflow_regenerates_and_compares_before_publishing(cli, proj):
    cli("docs", "init", "--pages")
    wf = (proj / ".github/workflows/steward-docs.yml").read_text()
    assert wf.index("steward docs build") < wf.index("mkdocs build") and "git diff --exit-code" in wf
    assert wf.count("pages: write") == 1 and "contents: read" in wf.split("deploy:")[0]


def test_T4_a_private_title_is_caught_before_init_writes(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "secret"\nfile = "development/secret.txt"\n')
    (proj / "development/secret.txt").write_text("Toy benchmark\n")
    assert cli("docs", "init")[0] == 65 and not (proj / "mkdocs.yml").exists()


def test_T5_only_dated_entry_headings_outside_code_are_titles(cli, proj):
    _publish(proj, ["decisions"])
    with open(proj / "development/DECISIONS.md", "a") as f:
        f.write("\n## 2026-11-24: a real decision\n```\n## 2026-01-01: an example inside code\n```\n## Notes\n")
    cli("docs", "build")
    page = (proj / "docs/project/decisions.md").read_text()
    assert "a real decision" in page and "inside code" not in page and "Notes" not in page


def test_T6_a_linked_or_sealed_record_is_never_published(cli, proj, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"schema": "steward.release_manifest/0.1", "version": "SECRET-VERSION"}')
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[release]\nmanifest = "rm.json"\n')
    (proj / "rm.json").symlink_to(outside)
    code, _, err = cli("docs", "build")
    assert code == 65 and "link" in err


def test_T7_a_linked_generated_folder_fails_r69(cli, proj, tmp_path):
    cli("docs", "build")
    import shutil
    shutil.move(str(proj / "docs/project"), str(tmp_path / "elsewhere"))
    (proj / "docs/project").symlink_to(tmp_path / "elsewhere")
    _, rep = cli.check(proj, "docs")
    assert one(rep, "R-69")["status"] == "FAIL"


def test_T2_control_an_empty_readable_list_is_fine(cli, proj):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[[terms]]\nname = "secret"\nfile = "development/secret.txt"\n')
    (proj / "development/secret.txt").write_text("# no terms yet\n")
    assert cli("docs", "build")[0] == 0
