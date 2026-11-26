"""PresentationKit v0.3: plan, stage confirmation, claim ceiling, values, limitations, structure, figures, visual,
language; preferences and their precedence (RELEASE_v0.3_SPEC §8)."""

import pytest

from steward import talk as tk

from conftest import append, codes, edit, gate, one

PLAN = "talks/progress-update/talk.toml"
SLIDES = "talks/progress-update/slides.tex"


@pytest.fixture(autouse=True)
def isolated_prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_CONFIG_HOME", str(tmp_path / "config-home"))  # never touch the real home


def test_example_talk_passes_draft_and_final(cli, example):
    code, rep = cli.check(example, "talk")
    assert code == 0 and all(r["status"] in ("PASS", "NOT_APPLICABLE") for r in rep["verdict"]["results"])
    code, rep = cli.check(example)
    assert code == 0 and gate(rep)["eligible"]
    assert cli("check", "--repo", example, "--final")[0] == 0


def test_no_talk_not_applicable(cli, tmp_path):
    cli("init", "--repo", tmp_path)
    _, rep = cli.check(tmp_path)
    assert one(rep, "R-21")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- R-21, R-22
def test_plan_tbd_incomplete_and_targeted_needs_decisions(cli, example):
    edit(example, PLAN, "duration_min = 10", 'duration_min = "TBD"')
    _, rep = cli.check(example)
    assert one(rep, "R-21")["status"] == "INCOMPLETE"
    edit(example, PLAN, 'unresolved_decisions = ["Bootstrap resamples: keep 2000 or raise to 5000?"]', "unresolved_decisions = []")
    _, rep = cli.check(example)
    assert "R-21.no_decisions" in codes(one(rep, "R-21"))


def test_plan_invalid_fails_and_others_unknown(cli, example):
    edit(example, PLAN, 'audience     = "technical"', 'audience     = "everyone"')
    _, rep = cli.check(example)
    assert one(rep, "R-21")["status"] == "FAIL" and one(rep, "R-23")["status"] == "UNKNOWN"


def test_stage_must_be_confirmed(cli, example):
    edit(example, PLAN, 'stage_source = "confirmed"', 'stage_source = "proposed"')
    code, rep = cli.check(example)
    assert one(rep, "R-22")["status"] == "UNKNOWN" and code == 3


def test_unusual_combination_listed(cli, example):
    edit(example, PLAN, 'stage        = "development"', 'stage        = "concept"')
    edit(example, PLAN, 'purpose      = "progress-update"', 'purpose      = "conference-talk"')
    _, rep = cli.check(example)
    assert "R-22.unusual" in codes(one(rep, "R-22"))


# ---------------------------------------------------------------- R-23 claim ceiling
def test_overstatement_without_evidence_fails(cli, example):
    append(example, PLAN, '\n[[claims]]\nid = "c2"\ntext = "Donor-aware models win"\nstatus = "validated"\n')
    code, rep = cli.check(example)
    res = one(rep, "R-23")
    assert res["status"] == "FAIL" and "R-23.overstatement" in codes(res) and code == 1


def test_validated_needs_confirmatory_contract_and_computed_values(cli, example):
    append(example, PLAN, '\n[[claims]]\nid = "c2"\ntext = "x"\nstatus = "validated"\nevidence = ["contract:expr-clf"]  # c2\n')
    _, rep = cli.check(example)
    assert one(rep, "R-23")["status"] == "INCOMPLETE"
    edit(example, PLAN, 'evidence = ["contract:expr-clf"]  # c2', 'evidence = ["contract:expr-clf", "value:n_donors"]')
    _, rep = cli.check(example)
    assert one(rep, "R-23")["status"] == "PASS"


def test_published_needs_identifier_and_unknown_status(cli, example):
    edit(example, PLAN, 'stage        = "development"', 'stage        = "concept"')
    append(example, PLAN, '\n[[claims]]\nid = "p"\ntext = "x"\nstatus = "published"\nevidence = ["doi:10.5555/abc"]\n')
    _, rep = cli.check(example)
    assert one(rep, "R-23")["status"] == "PASS"
    append(example, PLAN, '\n[[claims]]\nid = "u"\ntext = "y"\nstatus = "unknown"\n')
    _, rep = cli.check(example)
    assert one(rep, "R-23")["status"] == "UNKNOWN"


# ---------------------------------------------------------------- R-24, R-27
def test_unknown_value_key_fails(cli, example):
    edit(example, SLIDES, "\\val{n_donors} donors", "\\val{n_donor} donors")
    _, rep = cli.check(example)
    assert "R-24.unknown_key" in codes(one(rep, "R-24"))


def test_typed_number_blocks_final(cli, example):
    edit(example, SLIDES, "\\item The benchmark keeps every donor in one split.", "\\item 120 samples in total.")
    _, rep = cli.check(example)
    assert one(rep, "R-24")["status"] == "PASS"
    assert cli("check", "--repo", example, "--final")[0] == 2


def test_stale_shared_display_fails(cli, example):
    append(example, "benchmarks/splits/test.txt", "S041_1\n")
    _, rep = cli.check(example)
    assert "R-27.stale" in codes(one(rep, "R-27"))


def test_unregistered_graphic(cli, example):
    edit(example, SLIDES, "\\input{../../paper/tables/splits}", "\\includegraphics{shot.png}")
    _, rep = cli.check(example)
    assert "R-27.unregistered" in codes(one(rep, "R-27"))


# ---------------------------------------------------------------- R-25, R-26
def test_limitations_required_from_evaluation(cli, example):
    edit(example, PLAN, 'stage        = "development"', 'stage        = "evaluation"')
    _, rep = cli.check(example)
    res = one(rep, "R-25")
    assert res["status"] == "INCOMPLETE" and {"R-25.missing_role", "R-25.missing_frame"} <= codes(res)


def test_targeted_decision_must_appear(cli, example):
    edit(example, SLIDES, "Bootstrap resamples: keep 2000 or raise to 5000?", "Resampling to be discussed.")
    _, rep = cli.check(example)
    assert "R-26.decision_not_shown" in codes(one(rep, "R-26"))


def test_informational_must_not_request_feedback(cli, example):
    edit(example, PLAN, 'feedback     = "targeted"', 'feedback     = "informational"')
    edit(example, PLAN, 'role  = "decisions-needed"', 'role  = "feedback-requested"')
    _, rep = cli.check(example)
    assert one(rep, "R-26")["status"] == "FAIL"


def test_defense_needs_backup(cli, example):
    edit(example, PLAN, 'feedback     = "targeted"', 'feedback     = "defense"')
    _, rep = cli.check(example)
    assert "R-26.no_qa_backup" in codes(one(rep, "R-26"))


# ---------------------------------------------------------------- R-28, R-29
def test_slide_limit_and_contrast(cli, example):
    edit(example, PLAN, 'max_slides   = "auto"', "max_slides   = 3")
    _, rep = cli.check(example)
    assert "R-28.too_many_slides" in codes(one(rep, "R-28"))
    edit(example, PLAN, "max_slides   = 3", 'max_slides   = "auto"')
    append(example, PLAN, '\n[overrides]\npalette.text = "#bbbbbb"\n')
    _, rep = cli.check(example)
    assert one(rep, "R-28")["status"] == "FAIL"


def test_frame_overflow_from_log(cli, example):
    append(example, "talks/progress-update/slides.log", "\nOverfull \\vbox (40.0pt too high) detected at line 30\n")
    _, rep = cli.check(example)
    assert "R-28.frame_overflow" in codes(one(rep, "R-28"))


def test_strong_wording_listed_not_blocking(cli, example):
    edit(example, SLIDES, "\\item Train the baselines under controlled runs.", "\\item This proves the design is state of the art.")
    _, rep = cli.check(example)
    res = one(rep, "R-29")
    assert res["status"] == "PASS" and {d["value"].lower() for d in res["details"]} >= {"proves", "state of the art"}


# ---------------------------------------------------------------- preferences
def test_preference_precedence_and_provenance(cli, example, tmp_path):
    home = tmp_path / "config-home"
    (home / "contexts").mkdir(parents=True)
    (home / "presentation.toml").write_text('[style]\ndensity = "dense"\n[typography]\nfamily = "Fira Sans"\n')
    (home / "contexts/lab.toml").write_text('[style]\ndensity = "sparse"\n')
    (example / "presentation").mkdir()
    (example / "presentation/profile.toml").write_text('[palette]\naccent = "#0055aa"\n')
    append(example, PLAN, '\n[overrides]\nnotes.mode = "script"\n')
    edit(example, PLAN, 'format       = "talk"', 'format       = "talk"\ncontext_profile = "lab"')
    prefs = tk.resolve(example, {"notes": {"mode": "script"}}, "lab")
    assert prefs["style.density"] == ("sparse", "context:lab")
    assert prefs["typography.family"] == ("Fira Sans", "global")
    assert prefs["palette.accent"] == ("#0055aa", "project")
    assert prefs["notes.mode"] == ("script", "talk")
    assert prefs["style.aspect"][1] == "default"
    code, out, _ = cli("talk", "prefs", "progress-update", "--repo", example, "--compact")
    assert code == 0 and "[context:lab]" in out and "[default]" not in out


def test_prefs_set_validates_and_writes_only_style(cli, example, tmp_path):
    code, out, _ = cli("talk", "prefs", "--repo", example, "--set", "style.density", "sparse", "--layer", "global")
    assert code == 0 and (tmp_path / "config-home/presentation.toml").read_text().count("sparse") == 1
    assert cli("talk", "prefs", "--repo", example, "--set", "talk.content", "x", "--layer", "global")[0] == 64
    assert cli("talk", "prefs", "--repo", example, "--set", "style.density", "huge", "--layer", "project")[0] == 64


def test_contrast_and_auto_slides():
    assert round(tk.contrast("#000000", "#ffffff"), 1) == 21.0
    assert tk.contrast("#777777", "#ffffff") < 4.5
    assert tk.auto_max_slides(10, "balanced") == 10 and tk.auto_max_slides(10, "sparse") == 7


# ---------------------------------------------------------------- plan command and init
def test_talk_plan_suggests_pattern_and_writes_outline(cli, tmp_path):
    cli("init", "--repo", tmp_path, "--talk", "demo")
    code, out, _ = cli("talk", "plan", "--repo", tmp_path)
    assert code == 2 and "NOT CONFIRMED" in out
    p = tmp_path / "talks/demo/talk.toml"
    text = p.read_text()
    for a, b in (('stage        = "TBD"', 'stage        = "completed"'), ('stage_source = "proposed"', 'stage_source = "confirmed"'),
                 ('purpose      = "TBD"', 'purpose      = "conference-talk"'), ('feedback     = "TBD"', 'feedback     = "informational"'),
                 ('audience     = "TBD"', 'audience     = "specialist"'), ('duration_min = "TBD"', "duration_min = 20")):
        text = text.replace(a, b)
    p.write_text(text)
    code, out, _ = cli("talk", "plan", "--repo", tmp_path, "--write-outline")
    assert code == 0 and "pattern: completed-paper" in out and "limitations" in out and "claim ceiling" in out
    assert sum(1 for l in p.read_text().splitlines() if l.startswith("[[outline]]")) == 8
    assert cli("talk", "plan", "--repo", tmp_path, "--write-outline")[0] == 1  # never twice
