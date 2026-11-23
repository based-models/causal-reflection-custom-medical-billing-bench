# Medical Billing Benchmark: AI Agents That Learn From Payer Feedback

100% first-pass accuracy. 97% lower inference cost than Claude Opus 5.5. No retraining.

Medical billing agents need to do more than identify the right codes. They need to learn from payer feedback so they don't repeat the same mistakes across claims. This open-source benchmark evaluates [Causal Reflection](https://www.basedmodels.com/blog/introducing-causal-reflection), a method that enables AI models to learn from previous outcomes without retraining. Using real Medicare coding edits and simulated payer responses, we demonstrate how a low-cost model can match frontier-model accuracy while reducing unnecessary claim resubmissions.

## Results

We evaluated seven model configurations across 20 simulated claims using real Medicare National Correct Coding Initiative (NCCI) procedure-to-procedure edits. The primary metric is first-pass accuracy on follow-up claims: does the agent submit the correct payment decision and modifier on its first attempt, without requiring another rejection?

| Model | First-pass accuracy | Submissions per follow-up claim | Total inference cost |
| --- | ---: | ---: | ---: |
| GLM 5.3 Flash + Causal Reflection | 100% | 1.00 | $0.009 |
| Inkling 2 Small + Causal Reflection | 100% | 1.00 | $0.017 |
| Claude Opus 5.5 | 100% | 1.00 | $0.299 |
| Inkling 2 Small | 93.8% | 1.06 | $0.011 |
| GLM 5.3 Flash | 56.2% | 1.44 | $0.008 |
| Claude Sonnet 5.5 | 25.0% | 1.75 | $0.206 |
| Claude Haiku 5.5 | 6.2% | 1.94 | $0.013 |

Accuracy measures the first submission on 16 follow-up claims across four coding scenarios. Costs cover all 20 claims at published token rates. Every model ultimately reached the correct decision after permitted retries.

Key findings:

- Frontier-level accuracy: GLM 5.3 Flash with Causal Reflection matched Claude Opus on all 16 follow-up claims.
- **97% lower cost: $0.009 versus $0.299 in total inference cost.**
- Fewer retries: first-pass accuracy improved from 56.2% to 100% compared with the same GLM model without Causal Reflection.
- No retraining: improvements come from retaining and reusing successful outcomes, not updating model weights.
- Inkling 2 Small with Causal Reflection also matched Claude Opus on all 16 follow-up claims, at 94% lower cost: $0.017 versus $0.299.
- On Inkling, first-pass accuracy improved from 93.8% to 100% compared with the same model without Causal Reflection. The plain model was already right on 15 of 16 follow-up claims.

See [RESULTS.md](RESULTS.md) for detailed results and reproducible comparisons.

## How It Works

The benchmark simulates a common medical billing problem: a payer rejects a claim because the submitted procedure codes require a specific modifier. In this evaluation, the payer accepts XS (a modifier indicating a service was performed at a separate anatomical site) and rejects alternatives: 59, XE, XP, and XU.

1. Look up the coding rule. The agent retrieves the applicable Medicare NCCI edit to determine whether a modifier is permitted.
2. Submit the claim. The agent selects a modifier and receives simulated payer feedback. Incorrect modifiers are rejected.
3. Learn from the outcome. Causal Reflection retains the accepted modifier (XS) for that code pair.
4. Apply it to the next claim. When the same scenario occurs again, the agent uses XS on its first submission, avoiding another rejection.

Without Causal Reflection, the model can repeat the same mistake on subsequent claims, even after correcting it previously. With Causal Reflection, the agent remembers what worked.

## Benchmark Design

The evaluation uses the public CMS NCCI practitioner edits, effective October 1, 2026.

Test configuration:

- 20 claims across four real Medicare procedure-code pairs
- Five consecutive claims per code pair
- Synthetic claim narratives and simulated payer responses
- Access to CMS coding rules on every claim
- Seven model configurations, including a same-model baseline

The benchmark tests whether an agent retains and applies a previously successful modifier. The correct modifier is XS for all four scenarios. Unlike a static coding knowledge test, this evaluation measures whether an agent improves its decisions from prior feedback.

### Evaluation metrics

The primary metric is first-pass accuracy on claims 2–5 of each scenario. The first claim provides an opportunity to discover the payer's accepted modifier. We also measure final accuracy after retries, number of claim submissions, coding-rule lookups, and inference cost.

## Run the Benchmark

1. Install

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

2. Configure API keys

Add the following to `.env`:

- `FIREWORKS_API_KEY` — GLM baseline
- `BASED_API_KEY` — GLM with Causal Reflection
- `ANTHROPIC_API_KEY` — Claude comparisons (optional)

API keys remain local.

3. Run the evaluation

Preview one scenario:

```bash
.venv/bin/python -m ncci_bench run --episode payer --sessions 1 --arms glm-baseline,glm-causal --dry-run
```

Run all 20 claims with and without Causal Reflection:

```bash
.venv/bin/python -m ncci_bench run --episode payer --sessions 4 --arms glm-baseline,glm-causal
```

Compare against Claude:

```bash
.venv/bin/python -m ncci_bench run --episode payer --sessions 4 --arms claude-haiku,claude-sonnet,claude-opus
```

Generate a report:

```bash
.venv/bin/python -m ncci_bench report runs/<run-id>
```

## Additional Evaluation: Coding Rule Unavailable

What happens when an agent can no longer access the coding rule it previously retrieved? We evaluated 50 claims across 10 coding scenarios. The Medicare edit was available on the first claim but unavailable on subsequent claims, testing whether agents could retain and reuse prior decisions.

| Model | Follow-up accuracy | Total inference cost |
| --- | ---: | ---: |
| Inkling 2 Small + Causal Reflection | 100.0% | $0.053 |
| GLM 5.3 Flash + Causal Reflection | 95.0% | $0.029 |
| Claude Sonnet 5.5 | 40.0% | $0.638 |
| GLM 5.3 Flash | 37.5% | $0.026 |
| Inkling 2 Small | 17.5% | $0.052 |
| Claude Opus 5.5 | 15.0% | $1.693 |
| Claude Haiku 5.5 | 0.0% | $0.049 |

Key findings:

- 80 percentage points higher accuracy than Opus: 95% versus 15%.
- 98% lower inference cost than Opus: $0.029 versus $1.693.
- No retraining: Causal Reflection retains prior decisions even when the original coding rule is unavailable.
- Inkling 2 Small with Causal Reflection was correct on all 40 follow-up claims, against 17.5% for the same model without Causal Reflection. That run cost $0.053, against $0.052 for the Inkling baseline.

Accuracy measures exact-match payment decisions on 40 follow-up claims. Missing decisions count as incorrect. Opus frequently exhausted its allowed turns attempting to retrieve the unavailable rule rather than submitting an answer.

Run the evaluation:

```bash
.venv/bin/python -m ncci_bench run --episode table-off --sessions 10 --arms glm-baseline,glm-causal
.venv/bin/python -m ncci_bench run --episode table-off --sessions 10 --arms inkling-baseline,inkling-causal
```

See [RESULTS.md](RESULTS.md) for detailed methodology and results.

## Who This Is For

This benchmark is designed for teams building AI-native medical coding, billing, and revenue cycle management (RCM) systems. Potential applications include improving coding-agent reliability, reducing repeated payer rejections, and lowering inference costs in automated billing workflows.

Building an AI medical billing agent? [Explore Causal Reflection](https://www.basedmodels.com/blog/introducing-causal-reflection) to see how your agents could learn from outcomes without retraining.

## Scope and Limitations

This is a controlled evaluation, not a production medical billing study. It uses real CMS coding edits but synthetic claim descriptions and deterministic simulated payer responses. All four primary scenarios share the same column-two code and accepted modifier.

Results demonstrate outcome retention and reuse for a narrow coding decision, not general medical coding accuracy, real-world denial reduction, or production ROI. Medical necessity, appeals, reimbursement amounts, and broader payer-specific policies are outside the evaluation.
