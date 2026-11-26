"""0.6.2: release review gate (R-43): independent review of the release commit, blocking findings closed."""

import shutil
import subprocess

import pytest

from conftest import codes, one

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


REG = '''schema = "steward.findings/0.1"
[[reviews]]
id = "r1"
reviewer = "Independent reviewer"
implementer = "Implementer"
revision = "{rev}"
[[findings]]
id = "A1"
review = "r1"
severity = "high"
title = "a high finding"
status = "{status}"
{extra}
'''


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    r = tmp_path / "r"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    with open(r / "steward.toml", "a") as f:
        f.write('\n[release]\nrequired = []\nreview_required = true\n')
    (r / "tests").mkdir()
    (r / "tests/test_a1.py").write_text("def test_a1(): pass\n")
    (r / "code.py").write_text("x = 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "v1")
    monkeypatch.chdir(r)
    return r


def register(repo, status="verified", extra='test = "tests/test_a1.py::test_a1"\nverified_by = "Independent reviewer"', rev=None):
    (repo / "development/assessment").mkdir(parents=True, exist_ok=True)
    (repo / "development/assessment/findings.toml").write_text(
        REG.format(rev=rev or sh(repo, "git", "rev-parse", "HEAD"), status=status, extra=extra))


def test_no_register_is_incomplete(cli, repo):
    code, rep = cli.check(repo)
    assert one(rep, "R-43")["status"] == "INCOMPLETE" and code != 0


def test_reviewed_and_verified_passes(cli, repo):
    register(repo)
    _, rep = cli.check(repo)
    assert one(rep, "R-43")["status"] == "PASS"


def test_docs_only_change_after_review_still_covered_code_change_is_not(cli, repo):
    register(repo)
    (repo / "NOTES.md").write_text("docs\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "docs")
    _, rep = cli.check(repo)
    assert one(rep, "R-43")["status"] == "PASS"
    (repo / "code.py").write_text("x = 2\n")
    sh(repo, "git", "commit", "-qam", "code")
    _, rep = cli.check(repo)
    assert "R-43.stale_review" in codes(one(rep, "R-43"))


@pytest.mark.parametrize("status,extra,expected,code", [
    ("open", "", "FAIL", "R-43.open"),
    ("confirmed", "", "FAIL", "R-43.open"),
    ("fixed", 'test = "tests/test_a1.py::test_a1"', "INCOMPLETE", "R-43.not_reverified"),
    ("verified", "", "INCOMPLETE", "R-43.no_regression_test"),
    ("accepted", "", "FAIL", "R-43.unwaived"),
])
def test_blocking_findings(cli, repo, status, extra, expected, code):
    register(repo, status=status, extra=extra)
    _, rep = cli.check(repo)
    res = one(rep, "R-43")
    assert res["status"] == expected and code in codes(res)


def test_reviewer_must_differ_from_implementer(cli, repo):
    register(repo)
    p = repo / "development/assessment/findings.toml"
    p.write_text(p.read_text().replace('implementer = "Implementer"', 'implementer = "Independent reviewer"'))
    _, rep = cli.check(repo)
    assert "R-43.not_independent" in codes(one(rep, "R-43"))


def test_optional_by_default_but_recommended(cli, repo):
    p = repo / "steward.toml"
    p.write_text(p.read_text().replace("review_required = true", "review_required = false"))
    code, rep = cli.check(repo)
    res = one(rep, "R-43")
    confirmatory = 'profile = "confirmatory"' in p.read_text()  # 0.20.2: recommended to confirmatory projects only
    assert res["status"] == "NOT_APPLICABLE" and ("R-43.recommended" in codes(res)) == confirmatory
    _, text, _ = cli("check", "--repo", repo, "--summary")
    assert ("Recommended: before any public release, an independent red-team review" in text) == confirmatory


def test_recommended_to_a_confirmatory_project_even_without_release_config(cli, tmp_path):
    cli("init", "--repo", tmp_path, "--profile", "confirmatory")
    _, text, _ = cli("check", "--repo", tmp_path, "--summary")
    assert "Recommended: before any public release" in text
    other = tmp_path / "x"
    other.mkdir()
    cli("init", "--repo", other)
    _, text, _ = cli("check", "--repo", other, "--summary")
    assert "Recommended: before any public release" not in text  # 0.20.2: not for an exploratory project


# ---------------------------------------------------------------- red-team round 3: D8
@pytest.mark.parametrize("implementer", [None, "", "   "])
def test_D8_independence_must_be_shown_not_assumed(cli, repo, implementer):
    register(repo)
    p = repo / "development/assessment/findings.toml"
    line = "" if implementer is None else f'implementer = "{implementer}"'
    p.write_text(p.read_text().replace('implementer = "Implementer"', line))
    _, rep = cli.check(repo)
    res = one(rep, "R-43")
    assert res["status"] != "PASS" and "R-43.independence_unknown" in codes(res)


@pytest.mark.parametrize("extra,code", [
    ('test = "tests/test_a1.py::test_missing"\nverified_by = "Independent reviewer"', "R-43.no_regression_test"),
    ('test = "tests/test_a1.py"\nverified_by = "Independent reviewer"', "R-43.no_regression_test"),
    ('test = "tests/test_a1.py::test_a1"', "R-43.no_reverifier"),
    ('test = "tests/test_a1.py::test_a1"\nverified_by = "  "', "R-43.no_reverifier"),
])
def test_D8_verified_needs_a_named_test_and_a_reverifier(cli, repo, extra, code):
    register(repo, extra=extra)
    _, rep = cli.check(repo)
    res = one(rep, "R-43")
    assert res["status"] == "INCOMPLETE" and code in codes(res)


def test_D8_named_test_forms_are_found(cli, repo):
    (repo / "tests/test_a1.py").write_text("import pytest\n\nclass TestA:\n    def test_m(self): pass\n\n"
                                            "@pytest.mark.parametrize('x', [1])\ndef test_p(x): pass\n")
    for name in ("tests/test_a1.py::TestA::test_m", "tests/test_a1.py::test_p"):
        register(repo, extra=f'test = "{name}"\nverified_by = "Independent reviewer"')
        _, rep = cli.check(repo)
        assert one(rep, "R-43")["status"] == "PASS", name
    # red-team G2: a parameter reference is refused (plain test names only); the plain name above is the reference
    register(repo, extra='test = "tests/test_a1.py::test_p[1]"\nverified_by = "Independent reviewer"')
    _, rep = cli.check(repo)
    assert one(rep, "R-43")["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- red-team round 4: E5
E5_FILE = '''import pytest


def helper():
    pass


def test_plain():
    pass


@pytest.mark.parametrize("x", [1, "a b", None])
def test_param(x):
    pass


@pytest.mark.parametrize("x", [1, 2], ids=["one", "two"])
def test_ids(x):
    pass


@pytest.mark.parametrize("x,y", [(1, 2), pytest.param(3, 4, id="custom")])
def test_pairs(x, y):
    pass


@pytest.mark.parametrize("x", [object()])
def test_dynamic(x):
    pass


class TestK:
    def test_m(self):
        pass


class Helper:
    def test_m(self):
        pass
'''


@pytest.mark.parametrize("node,ok", [
    ("tests/test_e5.py::test_plain", True),
    ("tests/test_e5.py::test_param", True),
    ("tests/test_e5.py::test_param[1]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::test_param[a b]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::test_param[None]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::test_ids[two]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::test_pairs[1-2]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::test_pairs[custom]", False),  # G2: parameter references refused; name the test
    ("tests/test_e5.py::TestK::test_m", True),
    ("tests/test_e5.py::helper", False),               # not a test function pytest collects
    ("tests/test_e5.py::test_param[typo]", False),     # no such parameter case
    ("tests/test_e5.py::test_ids[1]", False),          # explicit ids replace the default ones
    ("tests/test_e5.py::test_plain[1]", False),        # not parametrized
    ("tests/test_e5.py::test_dynamic[x0]", False),     # not checkable statically: name the test without [...]
    ("tests/test_e5.py::Helper::test_m", False),       # not a Test* class
])
def test_E5_test_references_must_be_collectable(repo, node, ok):
    from steward import review as rv
    (repo / "tests/test_e5.py").write_text(E5_FILE)
    assert rv.test_exists(repo, node) is ok, node


# ---------------------------------------------------------------- red-team round 5: F3
F3_FILE = '''import pytest


@pytest.mark.parametrize("x", [1], ids=["\\u00e9"])
def test_value(x):
    pass


@pytest.mark.parametrize("x", [pytest.param(1, id="\\u00e9")])
def test_param(x):
    pass
'''


@pytest.mark.parametrize("node", [
    "tests/test_f3.py::test_value[é]", "tests/test_f3.py::test_value[\\xe9]",
    "tests/test_f3.py::test_param[é]", "tests/test_f3.py::test_param[\\xe9]",
])
def test_F3_ids_pytest_would_escape_are_refused(repo, node):
    from steward import review as rv
    (repo / "tests/test_f3.py").write_text(F3_FILE)
    assert rv.test_exists(repo, node) is False
    assert rv.test_exists(repo, node.split("[")[0]) is True  # the plain test name is the reference to use


# ---------------------------------------------------------------- red-team round 6: G2
G2_FILE = 'import pytest\n\n\n@pytest.mark.parametrize("x", [1], ids=[r"a\\b"])\ndef test_value(x):\n    pass\n'


@pytest.mark.parametrize("node,ok", [
    ("tests/test_g2.py::test_value[a\\b]", False),
    ("tests/test_g2.py::test_value[a\\\\b]", False),
    ("tests/test_g2.py::test_value", True),
])
def test_G2_only_plain_test_names_are_accepted(repo, node, ok):
    from steward import review as rv
    (repo / "tests/test_g2.py").write_text(G2_FILE)
    assert rv.test_exists(repo, node) is ok, node


# ---------------------------------------------------------------- 0.6.3: known issue H1
H1_FILE = '''class TestInit:
    def __init__(self):
        pass

    def test_x(self):
        pass


class TestNew:
    def __new__(cls):
        return super().__new__(cls)

    def test_x(self):
        pass


class TestOk:
    def test_x(self):
        pass


class TestOuter:
    class TestInner:
        def test_y(self):
            pass
'''


@pytest.mark.parametrize("node,ok", [   # expectations checked against `pytest --collect-only`
    ("tests/test_h1.py::TestInit::test_x", False),
    ("tests/test_h1.py::TestNew::test_x", False),
    ("tests/test_h1.py::TestOk::test_x", True),
    ("tests/test_h1.py::TestOuter::TestInner::test_y", True),
])
def test_H1_classes_pytest_will_not_collect_are_refused(repo, node, ok):
    from steward import review as rv
    (repo / "tests/test_h1.py").write_text(H1_FILE)
    assert rv.test_exists(repo, node) is ok, node


# ---------------------------------------------------------------- 0.6.3: I1 (Codex re-verification of b4190ac)
I1_FILE = '''import unittest


class Base:
    def __init__(self):
        pass


class Plain:
    pass


class Middle(Base):
    pass


class TestChild(Base):
    def test_x(self):
        pass


class TestGrandchild(Middle):
    def test_x(self):
        pass


class TestPlainBase(Plain):
    def test_x(self):
        pass


class TestObj(object):
    def test_x(self):
        pass


class TestImported(unittest.TestCase):
    def test_x(self):
        pass
'''


@pytest.mark.parametrize("node,ok", [   # pytest collects TestPlainBase, TestObj and TestImported (checked)
    ("tests/test_i1.py::TestChild::test_x", False),        # inherited __init__
    ("tests/test_i1.py::TestGrandchild::test_x", False),   # inherited through a local chain
    ("tests/test_i1.py::TestPlainBase::test_x", True),
    ("tests/test_i1.py::TestObj::test_x", True),
    ("tests/test_i1.py::TestImported::test_x", False),     # a base from elsewhere cannot be checked: refused, never guessed
])
def test_I1_inherited_constructors_are_found(repo, node, ok):
    from steward import review as rv
    (repo / "tests/test_i1.py").write_text(I1_FILE)
    assert rv.test_exists(repo, node) is ok, node


# ---------------------------------------------------------------- v0.7 review: J7
def test_J7_a_rebound_local_base_is_refused(repo):
    from steward import review as rv
    (repo / "tests/test_j7.py").write_text("class Base:\n    pass\n\n\nclass Base:\n    def __init__(self):\n        pass\n\n\n"
                                           "class TestX(Base):\n    def test_x(self):\n        pass\n")
    assert rv.test_exists(repo, "tests/test_j7.py::TestX::test_x") is False


# ---------------------------------------------------------------- v0.8 review: K7
@pytest.mark.parametrize("prelude", [
    "class Base:\n    pass\n\n\nif True:\n    class Base:\n        def __init__(self):\n            pass\n",
    "class Base:\n    pass\n\n\ntry:\n    Base = dict\nexcept Exception:\n    pass\n",
    "object = dict\n\n\nclass Base(object):\n    pass\n",
])
def test_K7_module_level_rebinding_anywhere_is_refused(repo, prelude):
    from steward import review as rv
    (repo / "tests/test_k7.py").write_text(prelude + "\n\nclass TestX(Base):\n    def test_x(self):\n        pass\n")
    assert rv.test_exists(repo, "tests/test_k7.py::TestX::test_x") is False


# ---------------------------------------------------------------- re-verification of e7a6344: M2
def test_M2_a_failed_comparison_is_unknown_coverage(repo, monkeypatch):
    from steward import review as rv
    rev = sh(repo, "git", "rev-parse", "HEAD")
    (repo / "code.py").write_text("x = 3\n")
    sh(repo, "git", "commit", "-qam", "code")
    real = rv._git

    def failing(root, *args):
        if args and args[0] == "diff":
            import subprocess
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad object")
        return real(root, *args)
    monkeypatch.setattr(rv, "_git", failing)
    assert rv.coverage(repo, rev)[0] is None
