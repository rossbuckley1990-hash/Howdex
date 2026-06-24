from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "launch"
LAUNCH_DRAFTS = LAUNCH / "drafts"
LAUNCH_TRACKING = LAUNCH / "tracking"
OUTREACH_DOCS = [
    LAUNCH_DRAFTS / "PILOT_OUTREACH.md",
    LAUNCH_DRAFTS / "SHOW_HN_DRAFT.md",
    LAUNCH_DRAFTS / "REDDIT_DRAFT.md",
    LAUNCH_DRAFTS / "AWESOME_LIST_SUBMISSION.md",
    LAUNCH_TRACKING / "PILOT_TRACKING.md",
]
DRAFTS = [
    LAUNCH_DRAFTS / "SHOW_HN_DRAFT.md",
    LAUNCH_DRAFTS / "REDDIT_DRAFT.md",
    LAUNCH_DRAFTS / "AWESOME_LIST_SUBMISSION.md",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lower(path: Path) -> str:
    return _text(path).lower()


def test_outreach_docs_exist():
    for path in OUTREACH_DOCS:
        assert path.is_file(), path


def test_drafts_do_not_claim_external_users():
    forbidden = [
        "external users exist",
        "we have external users",
        "external pilot users confirmed",
        "customers are using",
        "users are using howdex",
        "adoption is growing",
        "market validation",
    ]
    for path in DRAFTS:
        text = _lower(path)
        for phrase in forbidden:
            assert phrase not in text, f"{path} overclaims: {phrase}"


def test_drafts_do_not_claim_production_safe_autonomy():
    forbidden = [
        "provides production-safe autonomy",
        "offers production-safe autonomy",
        "enables production-safe autonomy",
        "is production-safe autonomous execution",
        "safe autonomous production execution",
    ]
    for path in DRAFTS:
        text = _lower(path)
        for phrase in forbidden:
            assert phrase not in text, f"{path} overclaims: {phrase}"
        assert "not production-safe autonomous execution" in (
            text
        ) or "does not prove broad" in text or path.name == "AWESOME_LIST_SUBMISSION.md"


def test_drafts_do_not_claim_live_cross_model_proof_unless_result_exists():
    result_files = list(ROOT.glob("**/*cross*model*result*.json")) + list(
        ROOT.glob("**/*cross*model*result*.txt")
    )
    combined = "\n".join(_lower(path) for path in DRAFTS)
    if not result_files:
        forbidden = [
            "live cross-model transfer is proven",
            "proved live cross-model transfer",
            "cross-model transfer proven",
            "verified across models in live runs",
        ]
        for phrase in forbidden:
            assert phrase not in combined


def test_tracking_file_starts_with_zero_external_users():
    tracking = _text(LAUNCH_TRACKING / "PILOT_TRACKING.md")

    assert "external_pilot_users_confirmed: 0" in tracking
    assert "external_procedure_submissions: 0" in tracking
    assert "external_verified_receipts: 0" in tracking
    assert "external_repos_using_howdex: 0" in tracking


def test_outreach_pack_contains_posting_rules_and_forbidden_claims():
    outreach = _lower(LAUNCH_DRAFTS / "PILOT_OUTREACH.md")

    assert "read and follow each community's rules" in outreach
    assert "do not spam" in outreach
    assert "external users exist" in outreach
    assert "production-safe autonomy" in outreach
    assert "live cross-model transfer has been proven" in outreach


def test_drafts_ask_for_pilots_without_claiming_pilots_exist():
    show_hn = _lower(LAUNCH_DRAFTS / "SHOW_HN_DRAFT.md")
    reddit = _lower(LAUNCH_DRAFTS / "REDDIT_DRAFT.md")

    assert "looking for pilot users" in show_hn
    assert "looking for technical feedback" in reddit
    assert "pilots have started" not in show_hn
    assert "pilots have started" not in reddit
