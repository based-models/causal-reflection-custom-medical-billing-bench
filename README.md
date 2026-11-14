# Causal reflection on Medicare bundling edits

This is a small, repeatable evaluation of [causal reflection](https://www.basedmodels.com/blog/introducing-causal-reflection) on a medical billing decision. It uses public Medicare rules, not a customer's claims.

The question is whether a model that keeps a correct earlier result does better on the next claims than the same model with no memory, and how that compares with Claude on cost and accuracy.

## Goal

Medicare will not pay two procedure codes together when a National Correct Coding Initiative (NCCI) procedure-to-procedure (PTP) edit says the second code is already included in the first. That denial is usually reported as CO-97, "the benefit for this service is included in the payment for another service." The correct fix depends on the current edit:

- The edit was deleted, so both codes can be paid.
- The edit is a hard bundle, so the second code is denied and a modifier does not change that.
- The edit allows a modifier, and the documentation supports one specific modifier.

These rules change every quarter. A model that remembers an older edit will apply the wrong payment.

In this bench, each case is five claims that share one real edit from the quarter effective October 1, 2026. The first claim can look the edit up. The next four claims are the same decision, and the lookup no longer returns the rule. Causal reflection keeps a correct first answer and can use it later. The baseline is the same model, seeing the same text and the same tool results, with no memory between claims. Claude sees the same claims and has no memory between them either.

The result that matters is accuracy on claims 2 through 5. Claim 1 shows whether the model can read the rule. Claims 2 through 5 show whether it still has that rule when the row is gone.

## Dataset

The source is the public CMS practitioner PTP quarterly change file, effective October 1, 2026, posted September 1, 2026:

https://www.cms.gov/files/zip/medicare-ncci-2026q4-practitioner-quarterly-additions-deletions-revisions-ptp.zip

The copy in this repo is `data/ncci/practitioner-q4.zip`. `data/ncci/PIN.json` records the download URL and the SHA-256. The bench reads the text tables in that ZIP:

- 4,249 added edits (1,539 where a modifier is not allowed, 2,710 where a modifier may be allowed)
- 14 deleted edits
- 7 edits whose modifier indicator changed

The file lists code pairs and a modifier indicator. It does not include code descriptions, fees, or medical notes. The ZIP contains the AMA copyright notice that CMS ships with the file. This repo stores the pairs and indicators, not descriptions.

Every claim uses the date of service October 15, 2026, so the October 1 rules are the ones in force. The correct decision does not change from one claim to the next inside a case.

## The bench

There are 50 claims: 10 cases, 5 claims each. The cases are real pairs from the change file.

| Cases | Edit in the CMS file | Correct decision |
| --- | --- | --- |
| 4 deletions | The edit ended on October 1, 2026 | Pay the second code, no modifier |
| 2 indicator changes to "modifier allowed" | The services were on separate anatomic sites | Pay the second code with modifier XS |
| 1 indicator change to "modifier not allowed" | The new rule denies the second code | Deny the second code, no modifier |
| 3 new hard bundles | A modifier does not bypass the edit | Deny the second code, no modifier |

The first six cases (30 claims) are two of each edit type. The full run is all ten cases.

Each claim tells the model the two codes, the date of service, and, for the separate-site cases, this sentence: "The column-two service was performed on a separate anatomic site." The claim text does not include the edit row. The policy for how to apply a row is in the instructions, and it is the same for every model:

1. A deletion date on or before the date of service means the second code is paid, with no modifier.
2. Modifier indicator 0 means the second code is denied. A modifier does not pay it.
3. Modifier indicator 1, together with the separate-site sentence, means the second code is paid with modifier XS.
4. Modifier indicator 1 without that sentence means the second code is denied.
5. Modifier indicator 9 means there is no active edit, so the second code is paid with no modifier.

XS is the only modifier this bench accepts. Modifiers 59, XE, XP, and XU are scored wrong. Dollar amounts are not part of the decision. The PTP file has no fees, and the graded outcome is whether the second code is paid or denied, and with which modifier.

The model has two tools, on every claim:

- `lookup_edit` returns the CMS row on the first claim when the model asks for that case's code pair and date. On claims 2 through 5 it returns `{"available": false}` and no row.
- `submit_answer` submits the decision. The answer is exactly two lines, for example `column_2: pay` and `modifier: XS`.

Causal reflection stores that answer only when it is exactly right. A wrong first answer is not replayed onto the later claims.

## Measurement

A claim is correct only when both lines match. Close wording, an extra modifier, or a swapped pay and deny is a miss.

The headline number is the exact-match rate on claims 2 through 5, causal reflection minus the same model with no memory. Claim 1 is reported beside it. The report also splits claims 2 through 5 by edit type, and it lists the cost of each model.

One check guards the setup: the number of lookup results on claims 2 through 5 that still contained the CMS row. That count is supposed to be zero. If it is not, the run did not hide the rule.

`summary.md` in each run directory is the score report. Reprint it with:

```bash
.venv/bin/python -m ncci_bench report runs/<run-id>
```

## Models

| Arm | What it is |
| --- | --- |
| `glm-baseline` | GLM 5.3 Flash, no memory between claims |
| `glm-causal` | GLM 5.3 Flash with causal reflection |
| `deepseek-baseline` | DeepSeek V4.1 Flash, no memory between claims |
| `deepseek-causal` | DeepSeek V4.1 Flash with causal reflection |
| `claude-haiku` | Claude Haiku 5.5 |
| `claude-sonnet` | Claude Sonnet 5.5 |
| `claude-opus` | Claude Opus 5.5 |

The primary comparison is a causal arm against its own baseline. Claude is the frontier comparison on the same claims. List price for the tokens is included in the report. No prices are estimated beyond the published token rates.

## Run the evaluation

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Put `FIREWORKS_API_KEY` and `BASED_API_KEY` in `.env` for the GLM pair. Add `ANTHROPIC_API_KEY` only when running Claude. Keys stay local.

Preview the 30-claim slice without calling a model:

```bash
.venv/bin/python -m ncci_bench run --sessions 6 --arms glm-baseline,glm-causal --dry-run
```

Run one case (5 claims) first:

```bash
.venv/bin/python -m ncci_bench run --sessions 1 --arms glm-baseline,glm-causal
```

Then the 30-claim slice, then the full 50:

```bash
.venv/bin/python -m ncci_bench run --sessions 6 --arms glm-baseline,glm-causal
.venv/bin/python -m ncci_bench run --sessions 10 --arms glm-baseline,glm-causal
```

Claude on the same 50 claims:

```bash
.venv/bin/python -m ncci_bench run --sessions 10 --arms claude-haiku,claude-sonnet,claude-opus
```

## Scope

This bench covers one payment decision: the current PTP edit for a code pair on one date of service. The code pairs are real CMS changes. The claim text around them is written for the evaluation. It is not a customer's claim history, a remittance, or a full billing workflow. Medical necessity, appeal letters, and dollar amounts are outside this score.
