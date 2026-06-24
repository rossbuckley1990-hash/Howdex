# Trust Calibration Results

This page records trust calibration results for Howdex procedures.

## Dogfood calibration run

Source: internal Howdex dogfood data.

Command:

    HOWDEX_CALIBRATION_SOURCE=dogfood python procedure_trust_calibration_test.py | tee benchmark-results/trust-calibration/dogfood-calibration.txt

Result file:

    benchmark-results/trust-calibration/dogfood-calibration.txt

## Result

Verdict:

    DOGFOOD INTERNAL ONLY
    INSUFFICIENT DATA

The run found dogfood data, but there were not enough usable samples to calculate a meaningful calibration curve.

Observed summary:

    summaries_found: 1
    summaries_with_outcome: 1
    samples_loaded: 0
    samples_skipped_missing_confidence: 1
    minimum_samples_required: 10

## Caveat

This is internal dogfood evidence only. It is not external adoption, not a public benchmark, and not proof of broad generalization.

The dogfood data currently comes from Howdex building Howdex, so it is single-repo, single-user, and early-stage. It is useful for validating the calibration machinery and tracking whether confidence/status begins to correlate with later outcomes, but it should not be presented as external validation.

## Next requirement

Future dogfood summaries should include procedure confidence/status metadata so the calibration harness can load them as usable samples.
