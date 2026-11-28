"""0.22.0, X02: dataset access (RELEASE_v0.22.0_SPEC §X02): an unclear role, links, per-consumer spent and excluded,
deny_develop_if_spent_for, and the accession: and local: identifiers. Earlier datasets.toml files behave as before."""

import os

import pytest
from pydantic import ValidationError

from conftest import codes, one


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    with open(r / "steward.toml", "a") as f:
        f.write("\n[integrity]\n")
    return r


def datasets(root, body):
    p = root / "development/datasets.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('schema = "steward.datasets/0.1"\n' + body)


def ask(cli, dataset, consumer, use):
    code, out, err = cli("integrity", "access", dataset, "--consumer", consumer, "--use", use)
    assert code in (0, 1), err
    assert out.startswith("ALLOW" if code == 0 else "DENY"), out
    return code == 0, out


# ---------------------------------------------------------------- the item's Verify list
def test_X02_verify_1_no_own_role_and_another_role_unclear_denies_develop(cli, proj):
    datasets(proj, '''[datasets.pool]
role = "development"
identifier = "TBD"
consumers = { study1 = "unclear", study2 = "development" }
''')
    ok, out = ask(cli, "pool", "study3", "develop")
    assert not ok and "unclear" in out
    assert not ask(cli, "pool", "study3", "confirm")[0]
    assert not ask(cli, "pool", "study1", "develop")[0]       # its own role is unclear
    assert ask(cli, "pool", "study2", "develop")[0]           # a role of its own decides
    assert ask(cli, "pool", "study3", "metadata")[0]


def test_X02_verify_1_a_dataset_role_unclear_denies_consumers_without_a_role(cli, proj):
    datasets(proj, '''[datasets.pool]
role = "unclear"
identifier = "TBD"
consumers = { study2 = "development" }
''')
    assert not ask(cli, "pool", "study1", "develop")[0]
    assert ask(cli, "pool", "study2", "develop")[0]


def test_X02_verify_2_a_dataset_linked_to_a_sealed_one_denies_develop(cli, proj):
    datasets(proj, '''[datasets.report-a]
role = "sealed"
identifier = "local:report-a"
consumers = { study1 = "development" }
[datasets.series-b]
role = "development"
identifier = "accession:geo:GSE12345"
links = ["report-a"]
''')
    for consumer in ("study2", "study3"):
        ok, out = ask(cli, "series-b", consumer, "develop")
        assert not ok and "linked to report-a" in out and "sealed" in out
    # stricter than the item asks, as it accepted: an active seal also holds for the sealed dataset's own study
    assert not ask(cli, "series-b", "study1", "develop")[0]
    assert ask(cli, "series-b", "study2", "metadata")[0]


def test_X02_verify_3_spent_for_one_consumer_only(cli, proj):
    datasets(proj, '''[datasets.pool]
role = "development"
identifier = "TBD"
consumers = { studyX = { spent = true } }
''')
    ok, out = ask(cli, "pool", "studyX", "develop")
    assert not ok and "spent for studyX" in out
    assert ask(cli, "pool", "studyY", "develop")[0]
    for consumer in ("studyX", "studyY"):
        assert not ask(cli, "pool", consumer, "confirm")[0]


def test_X02_verify_4_accession_and_local_identifiers_validate(cli, proj):
    from steward.integrity import DatasetDef
    for good in ("accession:geo:GSE12345", "accession:arrayexpress:E-MTAB-1234", "local:report-7", "local:a/b.c"):
        assert DatasetDef(role="development", identifier=good).identifier == good
    for bad in ("accession:GSE12345", "accession::GSE1", "accession:geo:", "local:", "local:has space", "gse:12345"):
        with pytest.raises(ValidationError):
            DatasetDef(role="development", identifier=bad)
    datasets(proj, '''[datasets.series]
role = "development"
identifier = "accession:geo:GSE12345"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
[datasets.report]
role = "development"
identifier = "local:report-7"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
''')
    _, rep = cli.check(proj, "integrity")
    assert one(rep, "R-36")["status"] == "PASS"


# ---------------------------------------------------------------- the rest of the specification
def test_X02_excluded_for_one_consumer_closes_only_its_use(cli, proj):
    datasets(proj, '''[datasets.pool]
role = "development"
identifier = "TBD"
consumers = { study1 = { excluded = true }, study2 = { role = "development" } }
''')
    ok, out = ask(cli, "pool", "study1", "develop")
    assert not ok and "excluded for study1" in out
    assert not ask(cli, "pool", "study1", "confirm")[0]
    assert ask(cli, "pool", "study1", "metadata")[0]
    assert ask(cli, "pool", "study2", "develop")[0]
    assert ask(cli, "pool", "study3", "develop")[0]


def test_X02_dataset_wide_spent_still_blocks_confirm_for_everyone(cli, proj):
    datasets(proj, '''[datasets.pool]
role = "development"
identifier = "TBD"
consumers = { study1 = "spent" }
[datasets.held]
role = "reserved"
identifier = "TBD"
consumers = { study2 = { role = "development", spent = false } }
''')
    assert not ask(cli, "pool", "study2", "confirm")[0]
    assert ask(cli, "held", "study2", "develop")[0]
    assert not ask(cli, "held", "study1", "develop")[0]


def test_X02_deny_develop_if_spent_for_every_or_named_consumers(cli, proj):
    datasets(proj, '''[datasets.spent-a]
role = "development"
identifier = "TBD"
consumers = { study1 = { spent = true } }
[datasets.spent-b]
role = "development"
identifier = "TBD"
consumers = { study2 = "spent" }
[datasets.fresh]
role = "development"
identifier = "TBD"
[consumers.strict]
deny_develop_if_spent_for = ["*"]
[consumers.picky]
deny_develop_if_spent_for = ["study1"]
''')
    for ds in ("spent-a", "spent-b"):
        ok, out = ask(cli, ds, "strict", "develop")
        assert not ok and "strict denies develop" in out
    assert ask(cli, "fresh", "strict", "develop")[0]
    assert ask(cli, "spent-a", "strict", "metadata")[0]
    assert not ask(cli, "spent-a", "picky", "develop")[0]
    assert ask(cli, "spent-b", "picky", "develop")[0]
    assert ask(cli, "spent-a", "other", "develop")[0]      # no policy: only the owner's own use is closed


def test_X02_links_are_followed_through_chains_and_cycles(cli, proj):
    datasets(proj, '''[datasets.a]
role = "development"
identifier = "TBD"
links = ["b"]
[datasets.b]
role = "development"
identifier = "TBD"
links = ["c", "a"]
[datasets.c]
role = "census-only"
identifier = "TBD"
links = ["b"]
[datasets.d]
role = "development"
identifier = "TBD"
links = ["e"]
[datasets.e]
role = "development"
identifier = "TBD"
links = ["d"]
''')
    ok, out = ask(cli, "a", "study1", "develop")
    assert not ok and "linked to b: linked to c: census-only" in out
    assert ask(cli, "d", "study1", "develop")[0]        # a cycle ends; nothing on it denies


def test_X02_a_link_to_an_undeclared_dataset_denies_and_fails_r36(cli, proj):
    datasets(proj, '''[datasets.a]
role = "development"
identifier = "TBD"
links = ["missing"]
''')
    ok, out = ask(cli, "a", "study1", "develop")
    assert not ok and "missing, which is not declared" in out
    _, rep = cli.check(proj, "integrity")
    res = one(rep, "R-36")
    assert res["status"] == "FAIL" and "R-36.unknown_link" in codes(res)


def test_X02_unknown_fields_in_the_consumer_table_are_rejected(cli, proj):
    datasets(proj, '''[datasets.a]
role = "development"
identifier = "TBD"
consumers = { study1 = { spend = true } }
''')
    _, rep = cli.check(proj, "integrity")
    assert one(rep, "R-36")["status"] == "FAIL"


# ---------------------------------------------------------------- earlier files behave as before
EARLIER = '''[datasets.pool-a]
role = "development"
identifier = "doi:10.1000/xyz"
paths = ["data/a/*"]
consumers = { study1 = "spent", study2 = "development" }
[datasets.pool-b]
role = "development"
identifier = "TBD"
consumers = { study1 = "reserved" }
[datasets.pool-c]
role = "census-only"
identifier = "TBD"
[datasets.pool-d]
role = "spent"
identifier = "TBD"
'''


@pytest.mark.parametrize("dataset, consumer, use, allowed, reason", [
    ("pool-a", "study1", "develop", True, "spent: develop allowed"),
    ("pool-a", "study1", "confirm", False, "spent for study1: never confirmatory again"),
    ("pool-a", "study2", "develop", True, "development: develop allowed"),
    ("pool-a", "study2", "confirm", False, "spent for study1: never confirmatory again"),
    ("pool-a", "study3", "develop", True, "development: develop allowed"),
    ("pool-b", "study1", "develop", False, "reserved for study1: kept for a later design"),
    ("pool-b", "study2", "develop", True, "development: develop allowed"),
    ("pool-c", "study1", "metadata", True, "census-only: metadata may be read"),
    ("pool-c", "study1", "develop", False, "census-only: metadata only, never the data"),
    ("pool-d", "study1", "develop", True, "spent: develop allowed"),
    ("pool-d", "study1", "confirm", False, "spent: never confirmatory again"),
])
def test_X02_an_earlier_datasets_file_gives_the_same_answers(cli, proj, dataset, consumer, use, allowed, reason):
    datasets(proj, EARLIER)
    code, out, _ = cli("integrity", "access", dataset, "--consumer", consumer, "--use", use)
    assert (code == 0) is allowed
    assert out.strip() == f"{'ALLOW' if allowed else 'DENY'} {dataset} for {consumer} ({use}): {reason}"
