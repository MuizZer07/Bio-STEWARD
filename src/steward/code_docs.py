"""One-line descriptions for result codes emitted by Steward rules (STW-035, B4).

Used by `steward explain` and `tools/build_rule_reference.py` whenever the emitting source line does not carry a
standalone literal message. Every description is one plain-English line of at least three words starting with a letter,
describing what was detected against the declared rule (never claiming truth or proof).
"""

from __future__ import annotations

CODE_DOCS: dict[str, str] = {
    # R-01 config.valid
    "R-01.overlay": "a local overlay file is active on top of steward.toml",
    "R-01.overlay_refused": "the local overlay tried to weaken or change a protected setting",
    "R-01.overlay_unreadable": "the local overlay file cannot be read or parsed",
    "R-01.records_missing": "a required process record declared in steward.toml is missing",

    # R-03 contract.consistent
    "R-03.confirmatory_unspecified": "a confirmatory contract still has a TBD or unspecified field",
    "R-03.confirmatory_without_comparison": "a confirmatory contract declares no [comparison] block",
    "R-03.confirmatory_without_thresholds": "a confirmatory contract declares no pass thresholds",
    "R-03.duplicate_id": "two benchmark contracts declare the same contract ID",
    "R-03.duplicate_split": "a contract declares two splits with the same name",
    "R-03.missing_file": "a file referenced by the benchmark contract does not exist",
    "R-03.no_test_role": "the contract's splits include no split with role = test",
    "R-03.path_outside": "a path in the benchmark contract escapes the repository root",
    "R-03.primary_undefined": "metrics.primary names a metric not listed in metrics.definitions",
    "R-03.threshold_baseline_undefined": "a threshold compares against an undeclared baseline",
    "R-03.threshold_metric_undefined": "a threshold references an undeclared metric",

    # R-04 contract.confirmatory_required
    "R-04.found": "confirmatory benchmark contract file(s) found for this profile",

    # R-05 prior_work.valid
    "R-05.duplicate_work_id": "two prior-work entries share the same work ID",
    "R-05.human_judgment": "novelty judgment is still unset and awaits the human owner",
    "R-05.unknown_work": "a comparison references a prior-work ID not declared in works",

    # R-06 prior_work.required
    "R-06.found": "prior-work record(s) with a closest_method work found",

    # R-07 privacy.scan
    "R-07.allowed_lines": "count of lines carrying an explicit R-07 allow marker",
    "R-07.bad_pattern": "a regular expression in a term list failed to compile",
    "R-07.controlled_access": "a controlled-access accession (dbGaP or EGA) appeared in a scanned file",
    "R-07.hit": "a private denylist term appeared in a scanned file (reported by list and line only)",
    "R-07.list_empty": "a configured term list contains no active terms",
    "R-07.list_missing": "a configured term list file does not exist",
    "R-07.list_unreadable": "a configured term list file could not be read as UTF-8",
    "R-07.pdf_unreadable": "PDF text could not be extracted for the privacy scan",
    "R-07.policy_hit": "a public policy term appeared in a scanned file",

    # R-09 paper.placeholders
    "R-09.marker": "an unresolved placeholder marker (TODO, TBD, FIXME, or similar) was found",
    "R-09.mode": "check mode used for the manuscript (draft or final)",

    # R-10 paper.values
    "R-10.generated_missing": "the generated values file for the manuscript is missing; run steward paper values --write",
    "R-10.generated_stale": "the generated values file is out of date; run steward paper values --write",
    "R-10.literal": "a bare numeric literal in the manuscript is not drawn from the values registry",
    "R-10.no_registry": "the manuscript references a value key, but no paper/values.toml exists",
    "R-10.source_error": "a value's source file could not be read or its pointer failed",
    "R-10.source_missing": "a value's declared source file does not exist",
    "R-10.source_unknown": "a value's source cannot be resolved or has an unsupported format",
    "R-10.unknown_key": "the manuscript references a key not defined in paper/values.toml",
    "R-10.unused": "a key defined in paper/values.toml is not referenced in the manuscript",

    # R-11 paper.displays
    "R-11.fingerprints_compared": "count of display entries whose fingerprints were compared with the lock",
    "R-11.lock_entry_invalid": "a display entry in displays.lock is missing required fingerprint fields",
    "R-11.lock_invalid": "the paper's displays.lock file cannot be parsed or fails its schema",
    "R-11.missing_file": "a figure, table, or data file named by a display entry is missing",
    "R-11.missing_script": "the generating script named by a display entry is missing",
    "R-11.no_lock": "displays.lock is missing; run steward paper displays NAME --record",
    "R-11.not_cited": "a declared display label is never referenced in the manuscript text",
    "R-11.not_included": "a declared display output file is not included in the manuscript",
    "R-11.not_recorded": "a declared display is not yet recorded in displays.lock",
    "R-11.path_outside": "a display's script, input, or output path escapes the repository root",
    "R-11.stale": "a display's script, input, or output changed since displays.lock was recorded",
    "R-11.unregistered": "a figure or table included in the manuscript is not registered in the display manifest",

    # R-12 paper.build
    "R-12.latex_error": "the LaTeX build log contains an error line",
    "R-12.mode": "check mode used for the paper build (draft or final)",
    "R-12.multiply_defined": "the LaTeX build log reports a multiply-defined label",
    "R-12.overfull": "the LaTeX build log reports an overfull box warning",
    "R-12.rerun": "the LaTeX build log asks to rerun LaTeX, BibTeX, or Biber",
    "R-12.undefined_citation": "the LaTeX build log reports an undefined citation key",
    "R-12.undefined_reference": "the LaTeX build log reports an undefined cross-reference",
    "R-12.undefined_summary": "the LaTeX build log summarizes unresolved references or citations",

    # R-13 paper.venue
    "R-13.abstract_words": "measured word count of the manuscript abstract",
    "R-13.abstract_words_over": "the manuscript abstract exceeds the venue's word limit",
    "R-13.anonymity": "a double-blind anonymity term appeared in the manuscript or PDF",
    "R-13.anonymity_no_list": "double-blind venue requires paper.anonymity_file to be configured",
    "R-13.anonymity_unreadable": "the configured anonymity term list could not be read",
    "R-13.anonymity_unspecified": "the venue profile leaves anonymity.double_blind unspecified",
    "R-13.dpi_unavailable": "Pillow is not installed, so raster figure DPI cannot be checked",
    "R-13.dpi_unknown": "a raster figure carries no resolution (DPI) metadata",
    "R-13.figure_dpi": "a raster figure's resolution is below the venue's minimum DPI",
    "R-13.figure_format": "a figure uses a file format not listed in the venue's allowed formats",
    "R-13.limit_unspecified": "a venue page or word limit is still TBD or unspecified",
    "R-13.main_end_not_found": "the configured main_ends_at marker was not found in the PDF text",
    "R-13.missing_declaration": "a required venue declaration (such as ethics or data availability) is missing",
    "R-13.missing_section": "a section required by the venue profile is missing from the manuscript",
    "R-13.mode": "check mode used for venue compliance (draft or final)",
    "R-13.no_pdf": "the compiled manuscript PDF is missing; build the paper first",
    "R-13.no_source": "the venue profile lacks a recorded source_url and retrieved date",
    "R-13.not_found": "the title or abstract could not be located in the main source file",
    "R-13.pages": "measured total page count of the compiled manuscript PDF",
    "R-13.pages_main": "the main body of the PDF exceeds the venue's main-page limit",
    "R-13.pages_total": "the PDF exceeds the venue's total page limit",
    "R-13.pages_unsupported": "page-limit checks are not implemented for .docx manuscripts in this version",
    "R-13.pdf_author_metadata": "the compiled PDF metadata names an author for a double-blind venue",
    "R-13.pdf_unreadable": "the PDF could not be read (install poppler or the [paper] extra)",
    "R-13.required_unspecified": "a required section or declaration in the venue profile is still unspecified",
    "R-13.title_words": "measured word count of the manuscript title",
    "R-13.title_words_over": "the manuscript title exceeds the venue's word limit",
    "R-13.words_unsupported": "word-limit checks are implemented for LaTeX sources only in this version",

    # R-14 paper.bibliography
    "R-14.duplicate_doi": "two bibliography entries share the same DOI",
    "R-14.duplicate_key": "the same citation key is defined more than once across .bib files",
    "R-14.malformed_identifier": "a bibliography entry's DOI, PMID, or arXiv identifier is malformed",
    "R-14.missing_entry": "a citation key used in the manuscript has no entry in the bibliography",
    "R-14.no_identifier": "a bibliography entry carries no DOI, PMID, arXiv ID, or URL",
    "R-14.parse": "a bibliography (.bib) file could not be parsed",
    "R-14.unused": "a bibliography entry is never cited in the manuscript",
    "R-14.verification": "summary counts of bibliography entries with and without verification metadata",

    # R-15 paper.consistency
    "R-15.invalid": "a cross-value consistency assertion expression could not be parsed or evaluated",
    "R-15.unavailable": "a value referenced by a consistency assertion is unavailable",
    "R-15.violated": "a cross-value consistency assertion evaluated to false",

    # R-21 talk.plan
    "R-21.custom_purpose": "the talk plan uses a custom purpose not in the built-in taxonomy",
    "R-21.no_outline": "the talk plan has no outline; run steward talk plan NAME --write-outline",
    "R-21.overrides": "the talk's preference overrides failed schema validation",
    "R-21.unknown_stage": "the talk plan names a research stage not in the taxonomy",

    # R-22 talk.stage_confirmed
    "R-22.unusual": "the talk's stage and purpose combination is unusual and should be confirmed",

    # R-23 talk.claim_ceiling
    "R-23.ceiling": "claim status ceiling permitted for the talk's declared research stage",
    "R-23.evidence_insufficient": "a talk claim lacks sufficient evidence for its stated status",
    "R-23.overstatement": "a talk claim's status exceeds the research stage's ceiling without evidence",
    "R-23.unknown_status": "a talk claim uses an unrecognized claim status",

    # R-24 talk.values
    "R-24.literal": "a bare numeric literal on a slide is not drawn from the values registry",
    "R-24.no_registry": "slides reference a value key, but no values registry is linked",
    "R-24.unknown_key": "a slide references a key not defined in the values registry",
    "R-24.variables_missing": "the generated talk variables file is missing; run steward talk values NAME --write",
    "R-24.variables_stale": "the generated talk variables file is stale; run steward talk values NAME --write",

    # R-25 talk.limitations
    "R-25.missing_frame": "no slide frame covers limitations in the built talk source",
    "R-25.missing_role": "the talk outline declares no section with the limitations role",

    # R-26 talk.structure
    "R-26.decision_not_shown": "an unresolved decision listed in the talk plan does not appear in the slides",
    "R-26.feedback_slide_in_informational": "an informational talk includes a feedback-only slide role",
    "R-26.no_decisions_section": "a targeted-feedback talk has no decisions section in its outline",
    "R-26.no_qa_backup": "the talk outline includes no Q&A or backup section",
    "R-26.no_text": "slide text could not be extracted to check structure",
    "R-26.required_section": "a section required for the talk's purpose is missing",

    # R-27 talk.figures
    "R-27.missing_file": "a source or output file for a talk display is missing",
    "R-27.not_recorded": "a talk display is not recorded in displays.lock",
    "R-27.not_traceable": "this slide format cannot be traced automatically; export to PPTX or Beamer",
    "R-27.nothing_to_trace": "no figures were found on slides to trace against the display lock",
    "R-27.stale": "a talk display changed since displays.lock was recorded",
    "R-27.unregistered": "a figure on a slide is not registered in the display manifest",

    # R-28 talk.layout
    "R-28.build_error": "the slide build log contains a compilation error",
    "R-28.contrast": "measured foreground-to-background contrast ratio is below the minimum",
    "R-28.engine": "slide engine detected for the layout check",
    "R-28.font_too_small": "text on a slide is smaller than the configured minimum font size",
    "R-28.frame_overflow": "the slide build log reports an overfull frame or box",
    "R-28.min_font": "minimum font size observed across the slides",
    "R-28.no_log": "the slide build log is missing; build the slides first",
    "R-28.no_pdf": "the compiled slide PDF is missing; build or export the slides",
    "R-28.note": "informational note from the slide layout inspector",
    "R-28.outside_slide": "a text or shape element extends outside the slide boundary",
    "R-28.pdf_reader_missing": "no PDF reader is installed to inspect slide layout (install poppler or [talk])",
    "R-28.pdf_unreadable": "the compiled slide PDF could not be read",
    "R-28.prefs": "a talk preference layer failed validation",
    "R-28.slides": "measured slide count against the configured maximum",
    "R-28.too_many_slides": "the deck has more slides than the configured maximum",

    # R-29 talk.wording
    "R-29.strong_wording": "strong or overclaiming wording found on a slide for human review",

    # R-31 ledger.intact
    "R-31.anchor_mismatch": "a signed ledger anchor does not match the ledger's hash at that sequence number",
    "R-31.anchor_ok": "a signed ledger anchor matched the ledger hash at that sequence number",
    "R-31.anchor_unverified": "a ledger anchor tag could not be verified against the pinned signers",
    "R-31.coverage": "scope note describing what hash-chain tamper evidence detects",
    "R-31.torn_tail": "the ledger ends with an incomplete trailing line; run steward ledger recover",

    # R-32 run.complete
    "R-32.failed": "a recorded run exited with a failed status",
    "R-32.interrupted": "a recorded run was interrupted before finishing; recover or rerun it",
    "R-32.killed": "a recorded run was killed (for example by a wall-time, memory, or hang limit)",
    "R-32.local_slot": "a run used a local slot instead of sharing the repository's permit slots",
    "R-32.output_changed": "a run's recorded output file changed after the run finished",

    # R-33 policy.pin
    "R-33.awaiting_signature": "a prepared policy-change authorization payload is waiting to be signed",
    "R-33.baseline_moving": "the trust root points to a moving ref instead of a pinned commit hash",
    "R-33.changed": "a policy file differs from the pinned baseline without an authorization",
    "R-33.fingerprint": "SSH key fingerprint of a configured approval signer",
    "R-33.object": "expected working-tree digest to authorize a policy change",
    "R-33.overlay": "a local overlay setting was checked against the policy baseline",
    "R-33.pending": "approval key and trust-root setup is not yet complete",
    "R-33.pin_unreadable": "the external per-user trust pin cannot be read; re-pin with steward authorize pin",
    "R-33.policy_removed": "the policy block was removed relative to the pinned trust root",
    "R-33.signer": "authorized signer principal and key type from the signers file",
    "R-33.trust_root": "source and pinned reference of the active trust root",

    # R-34 spend.within_cap
    "R-34.actual_without_estimate": "a spend record logged an actual cost without a prior estimate",
    "R-34.over_cap": "committed spend exceeds the configured budget cap without authorization",
    "R-34.totals": "summary of recorded spend calls and committed total",
    "R-34.trust_unpinned": "a spend authorization cannot be checked because the trust root is not pinned",
    "R-34.unauthorized": "a spend record past the cap lacks an intact signed authorization",
    "R-34.verification_unavailable": "spend authorization signature cannot be checked in this environment",

    # R-35 integrity.frozen
    "R-35.proposal_pending": "an amendment proposal is open and awaiting a signed approval",
    "cohort.changed": "a frozen cohort file changed after the freeze",
    "params.changed": "a frozen parameter value changed after the freeze",
    "protocol.drift": "a frozen protocol file changed after the freeze",

    # R-36 integrity.datasets
    "R-36.role_mismatch": "a dataset's declared role differs from the role recorded in the integrity ledger",
    "R-36.role_unrecorded": "a dataset is declared sealed or spent but was never sealed with steward seal",
    "R-36.sealed_changed": "a sealed dataset's content hash changed after sealing",
    "R-36.unknown_link": "a dataset's links list names a dataset not declared in datasets.toml",

    # R-37 integrity.sealed_unused
    "R-37.paper_reports_sealed": "a manuscript value reads from a sealed dataset before a signed unseal",
    "R-37.run_read_sealed": "a recorded run read a sealed dataset before a signed unseal",

    # R-38 integrity.decisions
    "R-38.append_only_history": "number of git commits inspected to check that decisions logs are append-only",
    "R-38.append_only_weak": "decisions log history was checked without a pinned policy baseline",
    "R-38.decisions_base_unknown": "the git base ref for checking decisions-log history could not be resolved",
    "R-38.history_partial": "only a bounded prefix of git history was inspected for the decisions log",
    "R-38.no_decision": "a gated integrity action lacks a matching entry in DECISIONS.md",
    "R-38.no_policy": "a gated integrity action cannot be verified because [policy] is not configured",
    "R-38.trust_unpinned": "a gated action's authorization cannot be checked because the trust root is unpinned",
    "R-38.unauthorized": "a gated integrity action lacks a verified signed authorization",
    "R-38.verification_unavailable": "authorization signatures cannot be verified in this environment",

    # R-40 evidence.claims
    "R-40.contract_not_frozen": "a claim references a contract that has not been frozen",
    "R-40.derived_binary64": "a derived value is computed in binary floating point",
    "R-40.invalid_tolerance": "a claim's numeric tolerance is negative or not finite",
    "R-40.not_numeric": "the evidence value pointed to by a claim is not numeric",
    "R-40.out_of_range": "a claimed or evidence number exceeds the exact comparison range",
    "R-40.run_missing": "a claim names a run ID not present in the run ledger",
    "R-40.run_unfinished": "a claim names a run that has no recorded outcome yet",
    "R-40.source_unreadable": "a claim's evidence source file or pointer could not be read",
    "R-40.unknown_value_key": "a claim's value_key is not defined in any paper values registry",
    "R-40.value_mismatch": "a claim's stated value differs from the recorded evidence beyond tolerance",

    # R-41 prior_work.linked
    "R-41.unknown_contract": "a claimed difference links to a benchmark contract that does not exist",

    # R-42 release.integrity
    "R-42.artifact_mismatch": "a distribution artifact's SHA-256 differs from the release manifest",
    "R-42.audited": "summary of release artifacts and member counts scanned by the audit",
    "R-42.bundle_mismatch": "a skill bundle zip differs from its recorded manifest or source files",
    "R-42.bundle_record_stale": "a skill bundle's .bundle.json record is stale relative to its zip",
    "R-42.citation": "a structural problem was found in CITATION.cff",
    "R-42.citation_changed": "CITATION.cff changed after the release manifest was written",
    "R-42.citation_invalid": "cffconvert reported schema errors in CITATION.cff",
    "R-42.citation_validator_error": "running cffconvert failed unexpectedly",
    "R-42.claims_changed": "the claim map changed after the release manifest was written",
    "R-42.claims_not_passing": "the release claim map (R-40) is not passing",
    "R-42.excluded": "a distribution archive includes a path matched by the exclusion patterns",
    "R-42.forbidden_member": "a distribution archive contains a forbidden file or directory",
    "R-42.identity_missing": "the release manifest is missing a required project identity field",
    "R-42.local_path": "a release artifact contains an absolute local home path",
    "R-42.lock_changed": "a lock file changed after the release manifest was written",
    "R-42.lock_unavailable": "a declared lock file could not be read for the release check",
    "R-42.manifest_invalid": "the release manifest cannot be parsed or fails its schema",
    "R-42.manifest_other_dist": "the release manifest was written for a different dist directory",
    "R-42.missing_artifact": "an expected distribution artifact pattern matched no built file",
    "R-42.missing_member": "a required file is missing from a built distribution archive",
    "R-42.missing_required": "a required release file (such as README or LICENSE) is missing",
    "R-42.no_claim_map": "the configured release claim map file does not exist",
    "R-42.no_dist": "no distribution artifacts exist in the configured dist directory",
    "R-42.policy_term": "a public policy term appeared inside a release artifact member",
    "R-42.policy_term_in_name": "a public policy term appeared in a release artifact member's path",
    "R-42.private_term": "a private denylist term appeared inside a release artifact member",
    "R-42.private_term_in_name": "a private denylist term appeared in a release artifact member's path",
    "R-42.shipped_secret": "a secret-like file or pattern was found inside a built distribution",
    "R-42.terms_unavailable": "a configured term list could not be loaded during the release audit",
    "R-42.version_mismatch": "a built artifact's version differs from the package version",

    # R-43 release.review
    "R-43.accepted_on_tests_unrecorded": "a finding accepted on tests lacks its recorded regression test details",
    "R-43.independence_unknown": "a review record omits its implementer, so independence cannot be checked",
    "R-43.known_issue": "a non-blocking finding is recorded as a known issue",
    "R-43.no_register": "the configured review findings register file does not exist",
    "R-43.no_regression_test": "a finding marked verified names a regression test that could not be collected",
    "R-43.open": "an open or unverified blocking review finding remains unresolved",
    "R-43.open_minor": "an open minor or low-severity review finding is recorded",
    "R-43.recommended": "an independent red-team review is recommended before releasing a confirmatory project",
    "R-43.review": "summary of a recorded independent review and the revision it covered",
    "R-43.unlisted_limitation": "a known-issue finding is not listed in the release limitations",

    # R-44 release.runtime_fingerprint
    "R-44.acknowledged": "a runtime module change was acknowledged as neutral",
    "R-44.added": "a new runtime module was added since fingerprints were recorded",
    "R-44.changed": "a runtime module changed since its fingerprint was recorded",
    "R-44.removed": "a fingerprinted runtime module was removed",
    "R-44.unparsable": "a runtime Python module could not be parsed for fingerprinting",

    # R-45 benchmark.splits
    "R-45.blank_group": "one or more sample rows have a blank group value, so group overlap is incomplete",
    "R-45.checked": "summary of splits, sample counts, and group or time checks evaluated",
    "R-45.duplicate_id": "a split file lists the same sample ID more than once",
    "R-45.empty_split": "a declared split file contains no sample IDs",
    "R-45.group_overlap": "two splits share at least one group (such as donor, patient, or study)",
    "R-45.group_unchecked": "group overlap could not be checked because metadata is missing or incomplete",
    "R-45.id_overlap": "two splits share at least one sample ID",
    "R-45.metadata_invalid": "the split metadata table is malformed or missing its declared key column",
    "R-45.metadata_missing": "the declared split metadata file does not exist",
    "R-45.no_metadata": "one or more split sample IDs are missing from the metadata table",
    "R-45.path_outside": "a split or metadata path escapes the repository root",
    "R-45.split_missing": "a declared split IDs file does not exist",
    "R-45.split_unreadable": "a split IDs file could not be read as UTF-8 text",
    "R-45.temporal_order": "an earlier split contains timestamps on or after a later split",
    "R-45.time_unchecked": "temporal split ordering could not be checked (needs time_key and metadata)",
    "R-45.time_unparsed": "one or more timestamps in the metadata could not be parsed",

    # R-46 benchmark.datasets
    "R-46.hash_mismatch": "a benchmark dataset file's SHA-256 differs from the contract's recorded hash",
    "R-46.no_hash": "a benchmark dataset in the contract has no recorded SHA-256 digest",

    # R-47 benchmark.results
    "R-47.duplicate_method": "two baselines in the contract share the same name",
    "R-47.invalid": "the benchmark results file could not be read or has an invalid table shape",
    "R-47.missing_result": "a required split, method, or metric cell is missing from the results table",
    "R-47.no_required_splits": "no test split is defined and [results] splits is not set",
    "R-47.no_results": "the declared benchmark results file does not exist",
    "R-47.not_numeric": "a benchmark result cell is not a finite number",
    "R-47.out_of_range": "a benchmark result value exceeds the exact comparison range",
    "R-47.path_outside": "the declared results file path escapes the repository root",
    "R-47.reserved_name": "a baseline uses the reserved name 'candidate'",
    "R-47.threshold_met": "a declared benchmark threshold was met by the candidate result",
    "R-47.threshold_not_evaluable": "a declared benchmark threshold could not be evaluated from the results",
    "R-47.threshold_not_met": "the candidate result did not meet a declared benchmark threshold",
    "R-47.undeclared": "the results file contains methods or metrics not declared in the contract",
    "R-47.unknown_split": "a required split listed under [results] is not defined in [splits]",

    # R-48 benchmark.comparison
    "R-48.inputs_changed": "a split file changed after the recorded comparison run executed",
    "R-48.no_output": "the declared comparison output file does not exist",
    "R-48.not_from_run": "no finished steward run recorded the comparison output with its current hash",
    "R-48.path_outside": "the comparison output path escapes the repository root",
    "R-48.procedure_unrecorded": "the comparison run did not record required inputs or seed metadata",
    "R-48.run": "run ID of the recorded comparison run checked",
    "R-48.split_missing": "a split file required by the comparison run is missing",

    # R-49 benchmark.leakage
    "R-49.declared_checked": "a leakage type is declared checked with an existing evidence path",
    "R-49.declared_not_applicable": "a leakage type is declared not applicable with a recorded reason",
    "R-49.evidence_missing": "a checked leakage type names an evidence path that does not exist",
    "R-49.reason_missing": "a not_applicable leakage declaration omits its reason",
    "R-49.undeclared": "one or more known leakage types are not declared in [leakage]",
    "R-49.unknown_type": "the contract's [leakage] table names an unrecognized leakage type",

    # R-50 storage.artifacts
    "R-50.annex_key_only": "a git-annex symlink is present locally without its annexed content",
    "R-50.annex_mismatch": "a git-annex pointer key differs from the digest in the storage registry",
    "R-50.dvc_mismatch": "a DVC pointer records an MD5 digest different from the storage registry",
    "R-50.git_unavailable": "git could not list tracked files, so large tracked files were not checked",
    "R-50.hash_mismatch": "a registered artifact's SHA-256 differs from the storage registry",
    "R-50.large_tracked": "a tracked file in git exceeds the configured large-file threshold",
    "R-50.no_retrieval": "a registered artifact lacks a retrieval note saying how to obtain it",
    "R-50.not_present": "a registered artifact is absent from the working tree",
    "R-50.path_outside": "a registered artifact or DVC pointer path escapes the repository root",
    "R-50.registry_outside": "the configured storage registry path escapes the repository root",
    "R-50.unstable": "a registered artifact changed on disk while its digest was being computed",

    # R-51 governance.constitution
    "R-51.recommended": "add constitution version under [steward] to align with project governance",
    "R-51.version_differs": "the declared constitution version differs from the toolkit's current version",

    # R-52 repro.current
    "R-52.contract_invalid": "a reproduction contract file could not be parsed or failed validation",
    "R-52.failed": "the latest reproduction check on this tree recorded mismatched outputs",
    "R-52.ledger": "the reproduction ledger has a hash-chain or formatting error",
    "R-52.no_files": "the reproduction record checked zero files, so it cannot pass",
    "R-52.no_git": "git is unavailable, so the current tree hash cannot be matched",
    "R-52.no_manifest": "the reproduction contract's manifest file does not exist",
    "R-52.not_current": "no reproduction check covers the current repository tree",
    "R-52.passed": "a passing reproduction check covers the current repository tree",
    "R-52.torn_tail": "the reproduction ledger ends with an incomplete trailing line",

    # R-53 exchange.valid
    "R-53.bad_transition": "an exchange item's ledger records a disallowed state transition",
    "R-53.deferred_stale": "a deferred inbox item's target version has already been released",
    "R-53.duplicate_id": "two exchange items or aliases claim the same exchange ID",
    "R-53.ledger_broken": "exchange/log.jsonl failed hash-chain verification or has a torn tail",
    "R-53.misplaced": "an exchange item is in the wrong subfolder for its sender project code",
    "R-53.name_mismatch": "an exchange item's filename stem does not match its header ID",
    "R-53.orphan_response": "a response item names a target ID not present in inbox/ or outbox/",
    "R-53.receipt_mismatch": "an outbox item differs from the bytes the peer recorded in its receipt",
    "R-53.removed_after_retirement": "a superseded or withdrawn inbox item's file was removed while its receipt remains",
    "R-53.response_target_mismatch": "a response's Answers binding does not match the bytes of the target item",
    "R-53.symlink": "exchange/ or an entry inside it is a symbolic link, which is refused",
    "R-53.tag_missing": "a shipped item names a release tag that does not exist in this repository",
    "R-53.tag_not_verified": "a peer-reported shipped tag is stated in the ledger but not verified locally",
    "R-53.unacknowledged": "a received inbox item has exceeded ack_days without a decision",
    "R-53.undelivered": "an outbox item has no committed receipt from its peer after the grace window",
    "R-53.unknown_entry": "an unexpected file or folder is present inside exchange/",
    "R-53.upgrade_available": "a received release notice advertises a newer version than currently used",
    "R-53.wrong_counterparty": "a response came from a project other than the item's addressee",

    # R-54 exchange.intake
    "R-54.future_date": "an exchange item's last state carries a date in the future",
    "R-54.inbox_edited": "a received inbox item was edited after its receipt hash was recorded",
    "R-54.ledger": "exchange/log.jsonl could not be verified for inbox intake checks",
    "R-54.no_decision": "an acknowledged inbox item has waited past ack_days without a decision",
    "R-54.receipt_unverified": "one or more inbox items have no recorded receipt hash to compare against",

    # R-55 session.handoff
    "R-55.missing": "the configured session handoff file does not exist",
    "R-55.over_budget": "the session handoff exceeds the configured word budget",
    "R-55.private": "the session handoff contains a private term or local home path",
    "R-55.shape": "the session handoff is missing one or more required sections",
    "R-55.stale": "a decisions log changed after the session handoff was last committed",
    "R-55.words": "word count of the session handoff against its configured budget",

    # R-56 boundary.clean
    "R-56.computed_import": "a dynamic or computed import was found and cannot be statically checked",
    "R-56.forbidden_distribution": "pyproject.toml declares a dependency forbidden by the boundary rule",
    "R-56.forbidden_import": "a Python file imports a module forbidden by the boundary rule",
    "R-56.no_pyproject": "the declared pyproject.toml file does not exist",
    "R-56.pyproject_invalid": "the declared pyproject.toml file could not be parsed",
    "R-56.scanned": "count of Python files parsed for boundary import checks",
    "R-56.unparsable": "a Python file could not be parsed for boundary import checks",

    # R-57 tasks.unique
    "R-57.duplicate_id": "two task specification files declare the same task ID",
    "R-57.next_id_invalid": "the board's Next unused ID does not match the configured id_pattern",
    "R-57.next_id_stale": "the board's Next unused ID is already in use by an existing task",
    "R-57.no_board": "the configured task board file does not exist",
    "R-57.no_id": "a task specification file lacks an **ID:** line matching id_pattern",
    "R-57.not_on_board": "an open task specification is not listed on the task board",
    "R-57.unknown_status": "a task specification uses a status not in the allowed status list",

    # R-58 changelog.current
    "R-58.git_error": "git failed while inspecting tags or changed files since the last release",
    "R-58.no_changelog": "the configured changelog file is not committed in git",
    "R-58.no_entry": "the changelog has no Unreleased section or no entries under it",
    "R-58.no_tag": "no release tag matching the configured pattern exists yet",
    "R-58.not_ready": "a changelog entry lacks its required ready status field",
    "R-58.not_updated": "relevant files changed since the last release without updating the changelog",
    "R-58.range": "git range and count of changed files inspected since the last release tag",
    "R-58.unreadable": "git could not read HEAD's tree for the changelog check",

    # R-59 git.branch_model
    "R-59.branch_name": "a branch name does not match the declared branch naming patterns",
    "R-59.history_unavailable": "git could not read commit history for the declared branch",
    "R-59.no_git": "git is unavailable or this folder is not a git repository",
    "R-59.no_integration_branch": "the declared integration branch does not exist",
    "R-59.no_release_branch": "the declared release branch does not exist",
    "R-59.no_tag": "no release tag exists on the integration branch to anchor merge checks",
    "R-59.not_no_ff": "a merge into the integration branch was not recorded as a --no-ff merge commit",
    "R-59.refs_unavailable": "git could not list branch refs for naming checks",
    "R-59.since_unknown": "the configured since ref for branch-model history could not be resolved",
    "R-59.untagged_release_commit": "a commit on the release branch has no matching release tag",

    # R-60 skills.sync
    "R-60.dangling": "a skills copy is a broken symbolic link whose target does not exist",
    "R-60.drift": "a skills copy differs from the canonical skills directory",
    "R-60.linked": "a skills copy is properly linked to the canonical skills directory",
    "R-60.missing": "a declared skills copy directory does not exist",
    "R-60.no_canonical": "the declared canonical skills directory does not exist",
    "R-60.pointer": "a skills copy uses a STEWARD_SKILLS pointer file matching the canonical directory",
    "R-60.pointer_wrong": "a STEWARD_SKILLS pointer file does not resolve to the canonical skills directory",

    # R-61 git.conflict_markers
    "R-61.conflict_marker": "an unresolved git merge-conflict marker was found in a committed file",
    "R-61.not_scanned": "one or more committed files could not be read for conflict-marker scanning",

    # R-62 agents.ledger
    "R-62.ledger": "the agents ledger has a hash-chain or structural error",
    "R-62.not_permitted": "an attempt was scored by an agent not allowed by [agents] may_score",
    "R-62.self_scored": "an attempt was scored by its own author",
    "R-62.silent_override": "an attempt was re-scored without recording an override reason",
    "R-62.torn_tail": "the agents ledger ends with an incomplete trailing line",
    "R-62.unknown_attempt": "a score references a task and attempt number not present in the ledger",

    # R-63 frozen.intact
    "R-63.changed": "a file in a frozen set changed relative to its recorded fingerprint",
    "R-63.history_unavailable": "git history could not be read to inspect frozen-set changes",
    "R-63.invalid": "the frozen-set record file could not be parsed or failed validation",
    "R-63.no_decision": "a re-recorded frozen set lacks its required decision reference",
    "R-63.no_files": "a frozen set's glob patterns matched no files in the repository",
    "R-63.not_recorded": "a declared frozen set has not been recorded yet with steward frozen record",

    # R-64 containers.context
    "R-64.large_folder": "an unignored folder inside the container build context exceeds the size limit",
    "R-64.link_dangling": "a broken symbolic link was found inside the container build context",
    "R-64.missing": "the declared container build context directory does not exist",

    # R-65 containers.compose
    "R-65.invalid": "a declared docker-compose file is not valid YAML",
    "R-65.missing_key": "a compose service is missing a required environment key",
    "R-65.no_yaml": "PyYAML is not installed, so compose files cannot be parsed",
    "R-65.ship_ignored": "a path required to ship in the image is excluded by .dockerignore",
    "R-65.ship_missing": "a path required to ship in the image does not exist in the context",
    "R-65.unknown_service": "the configuration names a compose service not defined in the compose file",
    "R-65.unreadable": "a declared docker-compose file could not be read",
    "R-65.user_data_not_volume": "a compose service's user data path is not mounted on a named volume",

    # R-66 pins.parity
    "R-66.git_error": "git failed while comparing pinned dependencies against the last release tag",
    "R-66.incomplete": "a dependency upgrade's parity record is missing required harnesses or approval",
    "R-66.no_record": "a pinned dependency changed since the last release without a parity record",
    "R-66.no_tag": "no release tag exists yet to compare pinned dependency versions against",
    "R-66.record": "summary of a checked dependency upgrade parity record",

    # R-67 benchmark.power
    "R-67.invalid": "the power table file could not be read or fails its schema",
    "R-67.invalid_row": "one or more rows in the power table have invalid values",
    "R-67.missing_row": "the power table lacks a row for a required shrinkage factor",
    "R-67.no_power": "the contract has no power table; run steward benchmark power CONTRACT --effects FILE",
    "R-67.no_row": "no power-table row matches the contract's minimum_units",
    "R-67.stale": "the power table is out of date relative to its effects input or contract",
    "R-67.underpowered": "estimated statistical power at minimum_units is below the target power",

    # R-68 staged.runs
    "R-68.below_minimum": "an outcome stage launched before reaching the declared accrual minimum",
    "R-68.ledger": "the staged-runs ledger has a hash-chain or structural error",
    "R-68.no_go": "an outcome stage launched without a recorded GO decision",
    "R-68.no_launch": "a stage outcome was recorded without a matching launch entry",
    "R-68.torn_tail": "the staged-runs ledger ends with an incomplete trailing line",
    "R-68.unfinished": "a launched stage has no recorded outcome entry yet",

    # R-69 docs.current
    "R-69.link": "a generated documentation path is a symbolic link, which is refused",
    "R-69.missing": "a generated site page, README block, or SVG asset is missing",
    "R-69.private": "generated documentation contains a private term or local home path",
    "R-69.readme_invalid": "the README's steward block markers are malformed or cannot be updated",

    # R-70 milestones.current
    "R-70.duplicate_id": "two milestones in development/milestones.toml share the same ID",
    "R-70.invalid": "development/milestones.toml could not be parsed or failed validation",
    "R-70.past_due": "a milestone past its due date has no recorded outcome (met, moved, or dropped)",
    "R-70.unknown_item": "a milestone references an exchange item not found in exchange/",
    "R-70.unknown_task": "a milestone references a task ID not found in any task spec",

    # R-71 sprints.valid
    "R-71.added_not_by_human": "a task added after sprint opening was not recorded by a human",
    "R-71.bad_transition": "a sprint task's ledger records a disallowed state transition",
    "R-71.foreign_ledger": "the sprint ledger was opened for a different sprint ID",
    "R-71.id": "the sprint file name does not match its declared sprint ID",
    "R-71.invalid": "a sprint file under development/sprints/ failed schema or DAG validation",
    "R-71.ledger": "the sprint ledger failed hash-chain verification or has a torn tail",
    "R-71.not_opened": "task state entries appear in the sprint ledger before the sprint opened",
    "R-71.unknown_task": "the sprint ledger names a task ID not defined in the sprint file",

    # R-72 sprints.report
    "R-72.no_report": "a finished sprint has no sprint report; run steward sprint report ID",
    "R-72.stale_report": "the sprint report is older than the sprint ledger; regenerate it",
    "R-72.unchecked_done": "a task marked done does not have every done command recorded with exit 0",

    # R-73 pins.intact
    "R-73.artifact_absent": "a declared pin's artifact file is not present on disk",
    "R-73.artifact_changed": "a pin's artifact file differs from its recorded SHA-256 digest",
    "R-73.artifact_missing": "a retired pin's kept archive artifact is missing from disk",
    "R-73.identity_changed": "a retired pin's package or version differs from what the ledger recorded",
    "R-73.ledger": "the pins ledger could not be verified",
    "R-73.protected_missing": "a record protected by a pin no longer exists",
    "R-73.retirement_incomplete": "a pin retirement did not finish; run steward pins retire NAME --resume",

    # R-74 pins.lifecycle
    "R-74.callers_unavailable": "project files could not be scanned to check callers of a deprecated pin",
    "R-74.deprecated_in_use": "a deprecated pin is still imported or referenced by project code",
    "R-74.eligible": "all retirement conditions hold for this pin; it may be retired with approval",

    # R-75 studies.intact
    "R-75.reference_mismatch": "check the input's contig names and lengths or interval bounds against the declared genome",
    "R-75.reference_incomplete": "provide contig declarations with lengths or a BED file with intervals to check",
    "R-75.reference_sizes": "provide a readable chromosome-sizes file with unique contig names and positive lengths",
    "R-75.chromosome_naming": "input files mix incompatible chromosome naming conventions (such as chr1 and 1)",
    "R-75.convention_mismatch": "a study input's chromosome naming disagrees with the declared convention",
    "R-75.duplicate_input": "the same input file or accession digest appears in more than one study",
    "R-75.file_changed": "a fingerprinted study input, plan, or result changed on disk",
    "R-75.file_missing": "a recorded study input, plan, or result file is missing or outside the repo",
    "R-75.inconsistent_references": "active studies disagree on a reference declared under [studies] consistent",
    "R-75.invalid": "a study record file could not be parsed or failed schema validation",
    "R-75.matrix_missing": "a sample-sheet matrix file declared by the study is missing",
    "R-75.matrix_refused": "a sample-sheet matrix path is a link or outside the repository",
    "R-75.matrix_unrecorded": "a sample-sheet matrix file is not fingerprinted in the study record",
    "R-75.none": "no study records exist yet; create one with steward study new ID",
    "R-75.sample_confounding": "condition groups are completely confounded with a batch or covariate factor",
    "R-75.sample_duplicate": "a sample ID appears more than once in the sample sheet",
    "R-75.sample_field_missing": "a required column is missing from the sample sheet",
    "R-75.sample_imbalance": "advisory: a condition's share is strongly imbalanced across factor levels",
    "R-75.sample_no_id": "a row in the sample sheet has a blank sample ID",
    "R-75.sample_not_in_matrix": "a sample listed in the sample sheet has no matching column in the matrix",
    "R-75.sample_not_in_metadata": "a sample column in the matrix is absent from the sample sheet",
    "R-75.sample_value_missing": "a required metadata cell is blank in the sample sheet",
    "R-75.sample_value_not_allowed": "a sample metadata cell contains a value outside the allowed set",
    "R-75.samples_no_id": "the declared sample ID column is missing from the sample sheet header",
    "R-75.samples_refused": "the sample sheet path is a link or outside the repository",
    "R-75.stale_dependency": "this study depends on another study whose inputs or results changed",
    "R-75.stale_paper": "a paper citing this study is stale because the study's records changed",
    "R-75.unfingerprinted": "a study file has no recorded SHA-256; run steward study fingerprint ID --write",
    "R-75.unknown_dependency": "this study names a dependency study ID that does not exist",
    "R-75.unknown_paper": "this study lists a paper name not declared in steward.toml",

    # R-76 research.records
    "R-76.draft": "a research record is still a draft; replace its template examples and set status = done",
    "R-76.invalid": "a research record file could not be parsed or failed schema validation",
    "R-76.no_difference": "a novelty contribution does not state how it differs from prior work",
    "R-76.no_nearest": "a novelty contribution names no nearest prior-work source",
    "R-76.stale_review": "a literature review is older than [research] stale_days and due for an update",
    "R-76.undecided_gap": "a recorded gap or flaw is marked addressed or accepted without a decision",
    "R-76.unknown_relation": "a research record links to another research record ID that does not exist",

    # R-77 paper.citations
    "R-77.invalid": "the paper's citations verification file could not be parsed or failed validation",
    "R-77.no_bibliography": "the manuscript cites keys, but no .bib file is among the paper's sources",
    "R-77.no_record": "the paper's citations verification file is missing; run steward paper citations NAME --fetch",
    "R-77.no_title": "a cited bibliography entry has no title field to compare against the record",
    "R-77.outside": "the configured citations verification file path escapes the repository root",
    "R-77.parse": "a bibliography file could not be parsed for citation verification",
    "R-77.refused": "the citations verification file is a link or cannot be safely read",
    "R-77.title_mismatch": "a cited entry's title disagrees with the resolved title recorded for its DOI or PMID",
    "R-77.unverified": "a cited entry with a DOI or PMID has no entry in the citations verification record",

    # R-78 benchmark.llm_eval
    "R-78.cases_missing": "the declared [llm_eval] cases CSV file cannot be read",
    "R-78.columns": "the [llm_eval] cases CSV is missing required columns or has no rows",
    "R-78.contamination_risk": "test cases were public on or before a candidate model's stated training cutoff",
    "R-78.group_leak": "at least one study or group appears in both tuning and test cases",
    "R-78.id_conflict": "a case ID appears more than once with conflicting split or group assignments",
    "R-78.prompts_not_intact": "the named [[frozen]] prompt set is not recorded or has changed (R-63)",
    "R-78.undated_cases": "test cases lack an ISO publication date, so cutoff exposure cannot be checked",

    # R-79 licence.declared
    "R-79.declared_invalid": "the licence declared under [licence] is not an SPDX licence expression",
    "R-79.mismatch": "a project metadata file or LICENSE states a different licence than [licence] declared",

    # R-80 licence.dependencies
    "R-80.changed": "a dependency's version or licence changed relative to the committed baseline",
    "R-80.exception": "a dependency is permitted under a recorded dated licence exception",
    "R-80.incompatible": "a dependency's licence is incompatible with the project's licence policy",
    "R-80.inventory": "the dependency licence inventory encountered a reading or metadata problem",
    "R-80.notices_missing": "the third-party notices file required for public distribution is missing",
    "R-80.notices_stale": "the third-party notices file is out of date; run steward licence notices --write",
    "R-80.obligation": "a permitted dependency carries a licence obligation (such as attribution or notice)",
    "R-80.scope": "scope note stating that licence checks evaluate declared rules and metadata only",
    "R-80.unknown": "a dependency's licence could not be identified from its installed metadata",
    "R-80.use_unmatched": "an entry in [licence] use names a package not found in the dependency inventory",

    # R-81 licence.copied
    "R-81.declared": "copied, ported, or vendored code is declared in third_party and permitted by policy",
    "R-81.incompatible": "a declared or header-marked third-party file has a licence disallowed by policy",
    "R-81.obligation": "a declared third-party file is permitted with an attribution or notice obligation",
    "R-81.unknown": "a declared or header-marked third-party file has an unrecognized licence",

    # R-82 licence.hints
    "R-82.hint": "advisory: a comment suggests ported or adapted code without a third_party declaration",

    # R-83 data.contracts
    "R-83.adjusted_equals_raw": "adjusted p-values equal raw p-values on every row of the table",
    "R-83.duplicate_id": "a row identifier appears more than once in the declared id_column",
    "R-83.encoding": "the data table is not UTF-8 encoded",
    "R-83.excel_date": "a gene symbol or identifier looks like an Excel-mangled date (such as 7-Sep)",
    "R-83.format": "the data table has a structural CSV or TSV formatting error",
    "R-83.header": "the data table has a missing, empty, or malformed header row",
    "R-83.hgnc_reference": "the declared local HGNC reference TSV is missing required columns or symbols",
    "R-83.identifier": "a cell does not match the declared identifier format",
    "R-83.infinite_lfc": "a log fold-change cell contains an infinite value",
    "R-83.invalid_cell": "a cell contains a disallowed control character such as NUL",
    "R-83.log_fold_change": "a log fold-change cell is not a finite number",
    "R-83.missing_column": "a column declared in the data contract is absent from the table header",
    "R-83.missing_file": "the data table file declared in [[data.contract]] does not exist",
    "R-83.missing_id": "a data row has a blank identifier in the declared id_column",
    "R-83.mixed_ensembl_versions": "an Ensembl ID column mixes versioned and unversioned identifiers",
    "R-83.mixed_na": "the table mixes different missing-value tokens (such as NA, NaN, and empty)",
    "R-83.no_samples": "a declared sample matrix has no sample columns",
    "R-83.p_order": "an adjusted p-value is smaller than its corresponding raw p-value",
    "R-83.p_value": "a p-value cell is outside [0, 1] or not a finite number",
    "R-83.p_zero": "a p-value is recorded as exact 0 (possible numerical underflow)",
    "R-83.previous_hgnc_symbol": "a gene symbol is a previous HGNC symbol rather than the approved symbol",
    "R-83.raw_count": "a raw-count cell is negative or not an integer",
    "R-83.refused": "the declared data table is a symbolic link or has extra hard links",
    "R-83.retired_hgnc_symbol": "a gene symbol is a withdrawn HGNC symbol",
    "R-83.row_width": "a data row has a different number of columns than the header",
    "R-83.sample_not_in_matrix": "a sample in the linked sample sheet has no column in this matrix",
    "R-83.sample_not_in_sheet": "a sample column in this matrix is absent from the linked sample sheet",
    "R-83.sample_order": "the sample order in the matrix differs from the linked sample sheet",
    "R-83.study_reference": "the study record linked by this data contract could not be safely read",
    "R-83.symbol_case": "a gene symbol's casing disagrees with the linked study's declared species",
    "R-83.type": "a cell value does not match the column's declared data type",
    "R-83.unreadable": "the declared data table could not be read or changed during the check",

    # R-84 compare.shadow
    "R-84.invalid": "a saved shadow-stage comparison record could not be parsed or failed validation",
    "R-84.missing": "a declared shadow stage has no recorded comparison yet",
    "R-84.stale": "a shadow-stage comparison no longer matches its recorded runs or outputs",

    # R-85 paper.data_availability
    "R-85.accession_missing": "an accession from a cited study is missing from the paper's data-availability statement",
    "R-85.no_statement": "no data-availability file or section was found for the paper",
    "R-85.refused": "the declared data-availability file is a link or outside the repository",

    # R-86 models.records
    "R-86.contract_split": "the model record's evaluation split is not defined in its benchmark contract",
    "R-86.input_changed": "a model evaluation run's input file changed after the recorded run",
    "R-86.metric_mismatch": "a recorded model-card metric disagrees with the evaluation run's output",
    "R-86.metric_undefined": "a model-card metric is not declared in the benchmark contract",
    "R-86.metrics_unrecorded": "the referenced evaluation run did not record metric values",
    "R-86.run_context": "the referenced evaluation run does not match the model weights or split context",
    "R-86.split_file": "a split file referenced by the model's benchmark contract is missing or unreadable",
    "R-86.training_input": "a training study's input file changed since the model record was written",
    "R-86.training_study": "a training study named in the model record does not exist or failed checks",
    "R-86.weights_changed": "the model weights file is missing or differs from its recorded SHA-256",

    # R-87 release.stranger_test
    "R-87.ignored": "a stranger-test file was ignored because it was empty or dated in the future",
    "R-87.none": "no stranger-test record was found under development/assessment/",
    "R-87.stale": "the latest stranger-test record is older than [stranger_test] max_age_days",

    # R-88 tidy.stale
    "R-88.contradiction": "a task's board status contradicts what a sprint ledger recorded",
    "R-88.exchange": "an exchange item is still open after a response or awaiting acknowledgement",
    "R-88.leftover": "a merged sprint branch or worktree is still present in the repository",
    "R-88.stale_page": "a handoff or index page is older than its threshold or behind the latest tag",
    "R-88.stale_task": "an open task on the board has been untouched longer than stale_days",

    # R-89 delegation.installed
    "R-89.missing": "an agent configured under [delegation] is not installed on PATH or in its install folder",
}
