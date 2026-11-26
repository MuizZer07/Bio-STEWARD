"""0.13.0: project storage cleanup (RELEASE_v0.13.0_SPEC §2; DESIGN_BRIEF_storage_cleanup)."""

import json
import os
import shutil
import subprocess

import pytest

git_needed = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def proj(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "home"))
    for env in ("HF_HOME", "TORCH_HOME", "PIP_CACHE_DIR", "CONDA_PKGS_DIRS", "XDG_CACHE_HOME"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr("steward.cleanup.SHARED_DEFAULTS", ())
    r = tmp_path / "p"
    r.mkdir()
    cli("init", "--repo", r)
    sh(r, "git", "init", "-q", "-b", "main")
    (r / "paper").mkdir()
    (r / "paper/main.tex").write_text("tex\n")
    scratch = tmp_path / "external-scratch"
    scratch.mkdir()
    (scratch / "ckpt.bin").write_bytes(b"y" * 5000)
    with open(r / "steward.toml", "a") as f:
        f.write(f'\n[storage]\n[storage.clean]\npaths = ["{scratch}"]\n')
    sh(r, "git", "add", "-A")
    sh(r, "git", "-c", "user.name=T", "-c", "user.email=t@example.org", "commit", "-qm", "init")
    (r / "src/pkg/__pycache__").mkdir(parents=True)  # by-products appear after the commit, untracked
    (r / "src/pkg/__pycache__/m.pyc").write_bytes(b"x" * 1000)
    (r / "paper/main.aux").write_text("aux\n")
    monkeypatch.chdir(r)
    return r


def _scan(cli):
    code, out, err = cli("storage", "scan", "--json")
    assert code == 0, err
    return {c["path"]: c for c in json.loads(out)["candidates"]}


def _snapshot(root):
    return sorted((str(p), p.stat().st_size) for p in root.rglob("*") if ".git" not in p.parts)


def test_C3_scan_lists_each_class_and_changes_nothing(cli, proj, tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    hf.mkdir()
    monkeypatch.setenv("HF_HOME", str(hf))
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere/big.dat").write_bytes(b"z" * 100)
    (proj / "data-link").symlink_to(tmp_path / "elsewhere")
    before = _snapshot(proj)
    c = _scan(cli)
    assert c["src/pkg/__pycache__"]["cls"] == "python" and c["paper/main.aux"]["cls"] == "docs"
    assert "paper/main.tex" not in c  # only by-products
    assert any(v["cls"] == "declared" and v["size"] == 5000 for v in c.values())
    assert any(v["cls"] == "linked" and v["path"].startswith("data-link ->") for v in c.values())
    assert any(v["cls"] == "shared" and "HF_HOME" in v["path"] for v in c.values())
    assert _snapshot(proj) == before
    _, out, _ = cli("storage", "scan")
    assert "Nothing was changed or deleted" in out and "startup disk" in out


@git_needed
def test_C3_a_tracked_cache_is_not_a_candidate(cli, proj):
    (proj / "tools/__pycache__").mkdir(parents=True)
    (proj / "tools/__pycache__/keep.pyc").write_bytes(b"k")
    sh(proj, "git", "add", "-f", "tools/__pycache__/keep.pyc")
    assert "tools/__pycache__" not in _scan(cli)


def test_C3_another_project_on_this_machine_using_the_same_folder_is_named(cli, proj, tmp_path, monkeypatch):
    from steward import cleanup as cu
    from steward.models import load_config
    monkeypatch.delenv("STEWARD_NO_REGISTRY")
    other = tmp_path / "other"
    other.mkdir()
    cli("init", "--repo", other)
    with open(other / "steward.toml", "a") as f:
        f.write(f'\n[storage]\n[storage.clean]\npaths = ["{tmp_path / "external-scratch"}"]\n')
    cu.register(other, load_config(other))
    cu.register(proj, load_config(proj))
    assert {p.name for p in cu.registered()} == {"other", "p"}
    declared = next(v for v in _scan(cli).values() if v["cls"] == "declared")
    assert "project other" in declared["users"]


def test_C2_the_registry_can_be_turned_off(cli, proj, monkeypatch):
    from steward import cleanup as cu
    from steward.models import load_config
    monkeypatch.delenv("STEWARD_NO_REGISTRY")
    t = (proj / "steward.toml").read_text().replace("[storage.clean]\n", "[storage.clean]\nregistry = false\n")
    (proj / "steward.toml").write_text(t)
    cu.register(proj, load_config(proj))
    assert cu.registered() == []


@pytest.mark.parametrize("declared", ["~", "."])
def test_C5_a_home_folder_or_the_repository_is_never_cleanable(cli, proj, declared):
    t = (proj / "steward.toml").read_text()
    t = t.replace("paths = [", f'paths = ["{declared}", ', 1)
    (proj / "steward.toml").write_text(t)
    for v in _scan(cli).values():
        if v["cls"] == "declared" and v["path"] in (declared, os.path.expanduser(declared)):
            assert v["refusals"], v


def test_C4_plan_leaves_linked_and_shared_out_unless_named(cli, proj, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (proj / "data-link").symlink_to(tmp_path / "elsewhere")
    code, out, _ = cli("storage", "clean", "--plan")
    assert code == 0 and "data-link" not in out and "__pycache__" in out
    plan = json.loads(next((proj / ".steward/cleanup").glob("*.json")).read_text())
    assert {e["cls"] for e in plan["entries"]} <= {"toolkit", "python", "docs", "declared"}
    code, out, _ = cli("storage", "clean", "--plan", "--class", "linked")
    assert "data-link" in out


def _tty(monkeypatch, answers):
    """Answers in order; "y" means yes in whatever word the prompt asks for ('proceed' when not every process could
    be inspected on this machine)."""
    import builtins
    import sys
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    it = iter(answers)

    def ask(prompt=""):
        a = next(it)
        if a == "y" and "'proceed'" in prompt:
            return "proceed"
        return a
    monkeypatch.setattr(builtins, "input", ask)


def _plan(cli, proj, *classes):
    args = ["storage", "clean", "--plan"] + [a for c in classes for a in ("--class", c)]
    assert cli(*args)[0] == 0
    return sorted((proj / ".steward/cleanup").glob("*.json"))[-1]


def test_C5_apply_refuses_without_a_terminal(cli, proj):
    plan = _plan(cli, proj)
    code, _, err = cli("storage", "clean", "--apply", plan)
    assert code == 64 and "terminal" in err and (proj / "src/pkg/__pycache__").exists()


def test_C5_apply_asks_per_location_deletes_records_and_reports(cli, proj, tmp_path, monkeypatch):
    from steward.ledger import verify
    plan = _plan(cli, proj, "python", "declared")
    _tty(monkeypatch, ["y", "n"])  # the cache yes, the external scratch no (sorted: declared first, then python)
    entries = json.loads(plan.read_text())["entries"]
    order = [e["cls"] for e in entries]
    answers = ["y" if c == "python" else "n" for c in order]
    _tty(monkeypatch, answers)
    code, out, err = cli("storage", "clean", "--apply", plan)
    assert code == 0, err
    assert not (proj / "src/pkg/__pycache__").exists() and (tmp_path / "external-scratch/ckpt.bin").exists()
    assert "freed on" in out
    led = verify(proj / "development/storage-cleanup.jsonl")
    assert not led.errors and [e["class"] for e in led.entries if e.get("kind") == "deleted"] == ["python"]


def test_C5_a_folder_replaced_after_the_plan_is_skipped(cli, proj, monkeypatch):
    plan = _plan(cli, proj, "python")
    shutil.rmtree(proj / "src/pkg/__pycache__")
    (proj / "src/pkg/__pycache__").mkdir()
    (proj / "src/pkg/__pycache__/new.pyc").write_bytes(b"n")
    _tty(monkeypatch, ["y"] * 5)
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "not the folder that was planned" in out and (proj / "src/pkg/__pycache__/new.pyc").exists()


def test_C5_a_folder_another_project_uses_needs_its_name_typed(cli, proj, tmp_path, monkeypatch):
    from steward import cleanup as cu
    from steward.models import load_config
    monkeypatch.delenv("STEWARD_NO_REGISTRY")
    other = tmp_path / "other"
    other.mkdir()
    cli("init", "--repo", other)
    with open(other / "steward.toml", "a") as f:
        f.write(f'\n[storage]\n[storage.clean]\npaths = ["{tmp_path / "external-scratch"}"]\n')
    cu.register(other, load_config(other))
    plan = _plan(cli, proj, "declared")
    _tty(monkeypatch, ["y"])
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "also used by: project other" in out and "kept" in out and (tmp_path / "external-scratch").exists()
    _tty(monkeypatch, ["shared"])
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert not (tmp_path / "external-scratch").exists()


def test_C5_a_location_with_an_open_file_is_skipped(cli, proj, tmp_path, monkeypatch):
    plan = _plan(cli, proj, "declared")
    holder = subprocess.Popen(["python3", "-c", "import sys, time\nf = open(sys.argv[1])\nprint('open', flush=True)\n"
                               "time.sleep(30)", str(tmp_path / "external-scratch/ckpt.bin")],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "open"
        _tty(monkeypatch, ["y"])
        _, out, _ = cli("storage", "clean", "--apply", plan)
        assert "has a file open there" in out and (tmp_path / "external-scratch/ckpt.bin").exists()
    finally:
        holder.kill()
        holder.wait()


# ---------------------------------------------------------------- review of 0.13.0: V1 - V4, V6
def test_V1_a_plan_entry_whose_target_was_changed_is_refused(cli, proj, tmp_path, monkeypatch):
    plan = _plan(cli, proj, "python")
    doc = json.loads(plan.read_text())
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep\n")
    st = victim.stat()
    doc["entries"][0]["real"] = str(victim.resolve())
    doc["entries"][0]["ident"] = [st.st_dev, st.st_ino, st.st_mtime_ns]
    plan.write_text(json.dumps(doc))
    _tty(monkeypatch, ["y"] * 3)
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "no longer a cleanup candidate" in out and (victim / "keep.txt").exists()


def test_V2_a_folder_whose_contents_changed_since_the_plan_is_skipped(cli, proj, monkeypatch):
    plan = _plan(cli, proj, "python")
    (proj / "src/pkg/__pycache__/new.pyc").write_bytes(b"n" * 10)
    _tty(monkeypatch, ["y"] * 3)
    _, out, _ = cli("storage", "clean", "--apply", plan)
    assert "contents changed since the plan" in out and (proj / "src/pkg/__pycache__/new.pyc").exists()


@pytest.mark.parametrize("plant, why", [("ledger.jsonl", "ledger"), ("note.txt", None)])
def test_V3_a_declared_folder_holding_a_ledger_is_kept(cli, proj, tmp_path, plant, why):
    (tmp_path / "external-scratch" / plant).write_text("x\n")
    c = next(v for v in _scan(cli).values() if v["cls"] == "declared")
    assert (any(why in r for r in c["refusals"]) if why else not c["refusals"]), c


def test_V4_a_declared_folder_overlapping_a_shared_cache_is_kept(cli, proj, tmp_path, monkeypatch):
    hf = tmp_path / "external-scratch"
    monkeypatch.setenv("HF_HOME", str(hf))
    c = next(v for v in _scan(cli).values() if v["cls"] == "declared")
    assert any("shared user cache" in r for r in c["refusals"]), c


def test_V6_an_active_run_writing_into_a_folder_and_a_broken_run_ledger_keep_it(cli, proj, tmp_path):
    from steward.ledger import Ledger
    from steward.models import load_config
    cfg = load_config(proj)
    led = Ledger(proj / "development/runs.jsonl", "runs", cfg.steward.repo_id)
    led.append("started", {"run": "r1", "cwd": ".", "outputs_before": {"src/pkg/__pycache__/out.bin": {}}})
    c = _scan(cli)["src/pkg/__pycache__"]
    assert any("active steward run" in r for r in c["refusals"]), c
    with open(proj / "development/runs.jsonl", "a") as f:
        f.write("{not json\n")
    c = _scan(cli)["paper/main.aux"]
    assert any("not intact" in r for r in c["refusals"]), c
