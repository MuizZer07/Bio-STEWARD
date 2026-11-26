"""0.8.1: adopter-reported defects (RELEASE_v0.8.1_SPEC §1.1). Each test is named after its request ID."""

import json
import shutil
import subprocess
import zipfile

import pytest

from conftest import REPO, codes, gate, one

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gitrepo(cli, tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.name", "T")
    sh(r, "git", "config", "user.email", "t@example.org")
    cli("init", "--repo", r)
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-qm", "init")
    monkeypatch.chdir(r)
    return r


# ---------------------------------------------------------------- AR-01, AR-02: git worktrees
@git_needed
def test_AR01_hooks_install_from_a_linked_worktree(cli, gitrepo, tmp_path):
    wt = tmp_path / "proj-wt-task"
    sh(gitrepo, "git", "worktree", "add", "-q", str(wt), "-b", "task")
    code, out, err = cli("hooks", "install", "--repo", wt)
    assert code == 0, err
    hooks = sh(wt, "git", "rev-parse", "--path-format=absolute", "--git-common-dir")
    from pathlib import Path
    assert (Path(hooks) / "hooks/pre-commit").is_file()


@git_needed
def test_AR02_init_in_a_worktree_takes_the_main_repository_name(cli, gitrepo, tmp_path):
    wt = tmp_path / "proj-wt-task"
    sh(gitrepo, "git", "worktree", "add", "-q", str(wt), "-b", "task2")
    (wt / "steward.toml").unlink()
    cli("init", "--repo", wt)
    assert 'project = "proj"' in (wt / "steward.toml").read_text()
    (wt / "steward.toml").unlink()
    cli("init", "--repo", wt, "--project", "chosen-name")
    assert 'project = "chosen-name"' in (wt / "steward.toml").read_text()


# ---------------------------------------------------------------- AR-03: dry runs, profile-aware templates
@git_needed
def test_AR03_hooks_install_dry_run_writes_nothing(cli, gitrepo):
    code, out, _ = cli("hooks", "install", "--dry-run", "--protect", "main")
    assert code == 0 and "pre-commit" in out and "main" in out
    assert not (gitrepo / ".git/hooks/pre-commit").exists()


def test_AR03_templates_follow_the_profile(cli, tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    cli("init", "--repo", a)
    assert (a / "steward.toml").is_file()
    assert not (a / "development/templates/benchmark.contract.toml").exists()
    cli("init", "--repo", b, "--profile", "confirmatory")
    assert (b / "development/templates/benchmark.contract.toml").is_file()
    cli("init", "--repo", c, "--templates", "contract")
    assert (c / "development/templates/benchmark.contract.toml").is_file()
    assert not (c / "development/templates/prior_work.prior.toml").exists()


# ---------------------------------------------------------------- AR-16 / SR-007: R-42 with nothing built
CFF = 'cff-version: 1.2.0\nmessage: "c"\ntitle: "x"\nauthors:\n  - name: "A"\n'


@pytest.fixture
def release(cli, tmp_path, monkeypatch):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[release]\n[privacy]\ndenylist_file = "development/denylist.txt"\n')
    for name, text in (("CITATION.cff", CFF), ("LICENSE", "MIT\n"), ("README.md", "# x\n"), ("development/denylist.txt", "secretterm\n")):
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_AR16_nothing_built_never_passes(cli, release):
    _, rep = cli.check(release, "release")
    assert one(rep, "R-42")["status"] == "NOT_APPLICABLE"
    _, out, _ = cli("check", "--repo", release, "--format", "json", "--final", "release")
    res = one(json.loads(out), "R-42")
    assert res["status"] == "INCOMPLETE" and "R-42.no_dist" in codes(res)


def test_AR16_built_without_a_manifest_is_incomplete(cli, release):
    (release / "dist").mkdir()
    with zipfile.ZipFile(release / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", "x = 1\n")
    _, rep = cli.check(release, "release")
    assert one(rep, "R-42")["status"] == "INCOMPLETE"


@pytest.mark.parametrize("member", ["x = 1\n", 'x = "secretterm"\n'])
def test_SR007_the_audit_command_and_r42_agree(cli, release, member):
    (release / "dist").mkdir()
    with zipfile.ZipFile(release / "dist/p-1.0-py3-none-any.whl", "w") as z:
        z.writestr("p/__init__.py", member)
    cli("release", "manifest")
    audit_code, _, _ = cli("release", "audit")
    _, rep = cli.check(release, "release")
    refused = audit_code == 1
    assert refused == (one(rep, "R-42")["status"] == "FAIL"), (audit_code, one(rep, "R-42"))


# ---------------------------------------------------------------- AR-17, AR-20: pre-commit follows its gate, quietly
@git_needed
def test_AR17_AR20_pre_commit_blocks_only_on_its_gate_and_is_quiet(cli, gitrepo):
    with open(gitrepo / "steward.toml", "a") as f:
        f.write('\n[release]\nrequired = ["MISSING.txt"]\n\n[gates.everyday]\nrequire = ["R-01"]\n')
    cli("hooks", "install", "--gate", "everyday")
    sh(gitrepo, "git", "add", "-A")
    p = subprocess.run(["git", "commit", "-qm", "release-only FAIL"], cwd=gitrepo, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr                # R-42 FAILs, but the gate does not require it
    assert len((p.stdout + p.stderr).strip().splitlines()) <= 4, p.stdout + p.stderr   # quiet: summary and gate lines
    (gitrepo / "steward.toml").write_text((gitrepo / "steward.toml").read_text() + "\n[polcy]\nx = 1\n")
    sh(gitrepo, "git", "add", "-A")
    p = subprocess.run(["git", "commit", "-qm", "gate FAIL"], cwd=gitrepo, capture_output=True, text=True)
    assert p.returncode != 0 and "R-01" in p.stdout + p.stderr   # blocking: the full summary is shown


# ---------------------------------------------------------------- AR-18: using-steward names every rule
def test_AR18_using_steward_lists_every_rule_and_the_current_schema():
    from steward.rules import RULES
    text = (REPO / "skills/using-steward/SKILL.md").read_text()
    missing = [r for r in RULES if r not in text]
    assert not missing, missing
    assert "steward.toml/0.1" not in text


# ---------------------------------------------------------------- AR-19 / FB-4 / FB-9: what a gate and a summary say
def test_AR19_the_gate_line_says_how_much_was_evaluated(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, out, _ = cli("check", "--repo", tmp_path, "--summary")
    line = next(l for l in out.splitlines() if l.startswith("Gate default"))
    assert "passed" in line and "not applicable" in line
    assert any(l.startswith("Configured:") and " of " in l for l in out.splitlines())


def test_AR19_min_evaluated_blocks_a_nearly_empty_gate(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write("\n[gates.default]\nrequire = [\"R-01\", \"R-02\", \"R-05\"]\nmin_evaluated = 2\n")
    code, rep = cli.check(tmp_path)
    g = gate(rep)
    assert not g["eligible"] and g["reason"] == "gate.min_evaluated" and code != 0


def test_FB9_a_configured_table_is_configured_even_with_nothing_recorded(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    with open(tmp_path / "steward.toml", "a") as f:
        f.write('\n[integrity]\ndecisions = "development/none.md"\n')  # nothing recorded: no log either
    _, out, _ = cli("check", "--repo", tmp_path, "--summary")
    line = next(l for l in out.splitlines() if l.startswith("Configured:"))
    assert "integrity (nothing recorded)" in line
    assert "not configured" not in line.split("integrity (nothing recorded)")[1].split("·")[0]


# ---------------------------------------------------------------- SR-009: pre-push evaluates the pushed commits
@pytest.fixture
def pushing(cli, gitrepo, tmp_path):
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", str(remote))
    sh(gitrepo, "git", "remote", "add", "origin", str(remote))
    sh(gitrepo, "git", "push", "-q", "origin", "main")
    with open(gitrepo / "steward.toml", "a") as f:
        f.write('\n[gates.push]\nrequire = ["R-01"]\n')
    sh(gitrepo, "git", "commit", "-qam", "gate")
    cli("hooks", "install", "--gate", "push")
    return gitrepo


@git_needed
def test_SR009_a_branch_without_configuration_is_pushed_with_a_notice(pushing):
    sh(pushing, "git", "checkout", "-q", "-b", "ungoverned")
    sh(pushing, "git", "rm", "-q", "steward.toml")
    sh(pushing, "git", "commit", "-qm", "no config")
    p = subprocess.run(["git", "push", "-q", "origin", "ungoverned"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode == 0 and "no steward.toml" in p.stderr


@git_needed
def test_SR009_the_pushed_commit_decides_not_the_working_tree(pushing):
    sh(pushing, "git", "checkout", "-q", "-b", "broken")
    (pushing / "steward.toml").write_text((pushing / "steward.toml").read_text() + "\n[polcy]\nx = 1\n")
    sh(pushing, "git", "commit", "-qam", "broken config", "--no-verify")
    sh(pushing, "git", "checkout", "-q", "main")                       # a clean, passing checkout
    p = subprocess.run(["git", "push", "-q", "origin", "broken"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode != 0 and "refs/heads/broken" in p.stderr
    (pushing / "steward.toml").write_text((pushing / "steward.toml").read_text() + "\n[polcy]\nx = 1\n")  # dirty, broken
    p = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr                                  # the pushed commit passes; the dirty tree is ignored


@git_needed
def test_SR009_deleting_a_protected_branch_is_refused(pushing):
    cli_ = None  # noqa: F841
    sh(pushing, "git", "push", "-q", "origin", "main:release-x")
    import subprocess as sp
    from steward.cli import main
    main(["hooks", "install", "--force", "--gate", "push", "--protect", "main"])
    p = sp.run(["git", "push", "-q", "origin", ":main"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode != 0 and "protected" in p.stderr
    p = sp.run(["git", "push", "-q", "origin", ":release-x"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr  # an unprotected branch may be deleted


# ---------------------------------------------------------------- 0.8.1 review: N1, N2 (high)
@git_needed
def test_N1_pre_push_runs_no_checkout_hook_or_filter_of_the_pushed_tree(pushing, tmp_path):
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    hooks = pushing / ".git/hooks"
    (hooks / "post-checkout").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (hooks / "post-checkout").chmod(0o755)
    sh(pushing, "git", "config", "filter.evil.smudge", str(script))
    sh(pushing, "git", "config", "filter.evil.clean", "cat")
    sh(pushing, "git", "checkout", "-q", "-b", "filtered")
    (pushing / ".gitattributes").write_text("*.txt filter=evil\n")
    (pushing / "data.txt").write_text("x\n")
    sh(pushing, "git", "add", ".gitattributes", "data.txt")
    sh(pushing, "git", "commit", "-qm", "filtered tree", "--no-verify")
    if marker.exists():
        marker.unlink()
    p = subprocess.run(["git", "push", "-q", "origin", "filtered"], cwd=pushing, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert not marker.exists(), "validating the pushed tree ran a hook or filter"


def test_N2_hook_text_carries_no_configured_values_and_names_are_validated(cli, tmp_path):
    from steward import hooks as hk
    for name in ("x; touch /tmp/pwned", "$(id)", "a b"):
        with pytest.raises(ValueError):
            hk.render("pre-push", gate="default", protected=[name])
        with pytest.raises(ValueError):
            hk.render("pre-commit", gate=name, protected=[])
    text = hk.render("pre-push", gate="default", protected=["main", "release/1.0"])
    # only validated names reach the hook, as quoted arguments to steward; the script holds no shell logic of its own
    assert "exec " in text and "hooks run pre-push" in text and "$protected" not in text and "for p in" not in text


@git_needed
def test_N2_install_never_writes_through_a_symlinked_hook(cli, gitrepo, tmp_path):
    outside = tmp_path / "outside-hook"
    outside.write_text("original\n")
    (gitrepo / ".git/hooks").mkdir(exist_ok=True)
    (gitrepo / ".git/hooks/pre-commit").symlink_to(outside)
    code, out, err = cli("hooks", "install", "--force")
    assert outside.read_text() == "original\n"
    assert "symlink" in (out + err)


# ---------------------------------------------------------------- re-verification of 7fd0970: O1 - O4
def test_O1_the_hook_runs_python_isolated_from_the_checkout(tmp_path):
    from steward import hooks as hk
    for kind in ("pre-commit", "pre-push"):
        text = hk.render(kind, gate="default", protected=[])
        assert " -I -m steward.cli" in text, text


@git_needed
def test_O1_a_planted_module_in_the_checkout_is_not_loaded(pushing, tmp_path):
    marker = tmp_path / "planted"
    (pushing / "steward").mkdir()
    (pushing / "steward/__init__.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    (pushing / "steward/cli.py").write_text("raise SystemExit(0)\n")
    sh(pushing, "git", "add", "-f", "steward")
    sh(pushing, "git", "commit", "-qm", "plant", "--no-verify")
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "x"], cwd=pushing, capture_output=True, text=True)
    assert not marker.exists()


@git_needed
def test_O3_a_hooks_path_through_a_symlink_is_refused(cli, gitrepo, tmp_path):
    real = tmp_path / "elsewhere-hooks"
    real.mkdir()
    link = tmp_path / "linked-hooks"
    link.symlink_to(real)
    sh(gitrepo, "git", "config", "core.hooksPath", str(link))
    code, out, err = cli("hooks", "install")
    assert code == 64 and "symlink" in (out + err) and not any(real.iterdir())


@git_needed
def test_O4_the_staged_check_keeps_the_invoking_checkouts_pin(cli, gitrepo, monkeypatch, tmp_path):
    import uuid
    from steward import authorize as az
    from steward import hooks as hk
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    tf = az.trust_file()
    tf.write_text(f'[repos."{uuid.uuid4()}"]\nbaseline = "{"0" * 40}"\nsigners = """x"""\ncheckout = "{gitrepo.resolve()}"\n')
    staged = tmp_path / "staged"
    staged.mkdir()
    cli("init", "--repo", staged)
    with az.checkout_hint(gitrepo):
        code, text = hk._check(staged, "default")
    assert code == 1 and "R-33" in text  # the staged copy is judged against the invoking checkout's pin
