"""0.10.0 H1: the scenario suite of DESIGN_v0.3 §8, one row per threat, each with its class and the tests that show
it. Classes: blocked (refused at a controlled boundary), detected (a later check FAILs), human (needs a person), out of
coverage (a documented limit, with a test that shows the limit)."""

import importlib

import pytest

from conftest import REPO

SCENARIOS = [
    ("An agent silently modifies a frozen cohort", "blocked at run; detected otherwise",
     ["test_integrity::test_freeze_then_drift_detected", "test_integrity::test_seal_blocks_run_and_unseal_needs_signature"]),
    ("A failed experiment disappears from the ledger", "detected; human without an anchor",
     ["test_run::test_edited_entry_fails_and_gap_fails", "test_run::test_torn_tail_incomplete_then_recover_never_deletes"]),
    ("A metric definition changes after evaluation", "detected",
     ["test_integrity::test_confirmatory_contract_freeze_needs_signature_and_timing",
      "test_integrity::test_amend_apply_refused_if_files_changed_after_proposal"]),
    ("'Reproduced' is claimed without a run record", "detected; prose is out of coverage",
     ["test_evidence::test_claim_without_run_or_with_wrong_number", "test_evidence::test_claim_source_rewritten_after_run"]),
    ("A rerun with different parameters", "detected",
     ["test_evidence::test_diff_run_lists_environment_and_code_differences", "test_evidence::test_diff_run_repeatable_and_tolerance"]),
    ("A release omits required evidence", "blocked in CI",
     ["test_v081_defects::test_AR16_built_without_a_manifest_is_incomplete", "test_v081_defects::test_AR16_nothing_built_never_passes"]),
    ("A process exceeds its allowed time", "blocked",
     ["test_run::test_limits_kill_the_tree", "test_run::test_child_processes_are_killed_with_the_parent"]),
    ("An agent authorises its own amendment", "blocked when keys are protected; otherwise human",
     ["test_authorize::test_unsigned_tag_refused", "test_authorize::test_wrong_signer_refused",
      "test_authorize::test_prepare_alone_never_authorizes"]),
    ("Concurrent agents write a ledger", "blocked (lock)",
     ["test_run::test_concurrent_writers_lose_nothing", "test_authorize::test_D7_concurrent_uses_run_the_protected_operation_once",
      "test_spend::test_A2_concurrent_workers_cannot_both_take_the_last_allocation"]),
    ("An agent bypasses steward run", "detected",
     ["test_evidence::test_claim_without_run_or_with_wrong_number"]),
    ("A policy file is edited in the working tree", "detected",
     ["test_authorize::test_signer_added_only_in_working_tree_refused", "test_authorize::test_policy_change_authorized"]),
    ("An optional tool is missing", "detected (UNKNOWN, gate blocked)",
     ["test_release::test_B5_cffconvert_is_run_when_installed"]),
    ("An empty rule set", "blocked (never a PASS)",
     ["test_scenarios::test_an_empty_rule_set_is_never_eligible"]),
    ("Spend past the cap, or with an expired authorization", "blocked (routed calls only)",
     ["test_spend::test_refused_past_authorized_budget_and_cap", "test_authorize::test_expired_and_wrong_action_refused"]),
    ("A direct SDK call bypasses the spend guard", "out of coverage (documented)",
     ["test_scenarios::test_direct_provider_calls_are_a_documented_limit"]),
    ("Seeded group or temporal leakage", "detected",
     ["test_benchmark::test_id_overlap_across_splits_fails", "test_benchmark::test_group_overlap_fails"]),
    ("Portability: the example passes from a fresh copy", "normal",
     ["test_rules::test_example_passes_every_applicable_rule", "test_determinism::test_golden_example"]),
]


@pytest.mark.parametrize("scenario, cls, tests", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_H1_every_scenario_is_shown_by_its_tests(scenario, cls, tests):
    assert tests, scenario
    for node in tests:
        mod, fn = node.split("::")
        assert hasattr(importlib.import_module(mod), fn), f"{scenario}: {node} is missing"


def test_H1_the_suite_covers_every_row_of_the_blueprint():
    assert len(SCENARIOS) == 17


def test_an_empty_rule_set_is_never_eligible():
    from steward.status import evaluate_gate
    g = evaluate_gate("empty", [], [], partial=False, min_evaluated=0)
    assert not g["eligible"]


def test_direct_provider_calls_are_a_documented_limit():
    """The spend guard sees calls routed through steward; a paid call made directly to a provider is outside it. The
    README says so (the limit is stated, not hidden)."""
    text = (REPO / "README.md").read_text()
    assert "a paid call" in text and "directly to a provider" in text and "outside its view" in text
