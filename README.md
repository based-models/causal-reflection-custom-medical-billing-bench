# Causal reflection on Medicare bundling edits

Medicare publishes a table of procedure-code pairs called the NCCI procedure-to-procedure (PTP) edits. Each row says that the second code is already included in the first, and whether a modifier can still get that second code paid. The table changes every quarter. This repository evaluates [causal reflection](https://www.basedmodels.com/blog/introducing-causal-reflection) on that decision, using the public practitioner changes effective October 1, 2026. The code pairs are real rows from that file. The claim text around them is written for the evaluation.

The question is what happens on the next claim for the same pair. The model can look the row up every time, submit, and read whether the payer accepted the modifier. Remembering the modifier that paid means the next claim is right on the first submission, without another rejection. On 20 of these claims, GLM 5.3 Flash with causal reflection matched Claude Opus 5.5: both were right on all 16 follow-up claims. Causal reflection cost $0.009, about 3% of Opus at $0.299. The comparison is in [RESULTS.md](RESULTS.md).

## Goal

Medicare will not pay two procedure codes together when a National Correct Coding Initiative (NCCI) procedure-to-procedure (PTP) edit says the second code is already included in the first. That denial is usually reported as CO-97, "the benefit for this service is included in the payment for another service." When the edit allows a modifier, the payer may still reject the modifier a coder tries first. The next claim for that pair should go out with the modifier that paid.

In this evaluation the CMS row stays available on every claim. The row says a modifier is allowed. The instructions list 59, XE, XP, XS, and XU, and the payer's response to `submit_answer` is what decides among them. This payer accepts XS and rejects the others. A model with no memory can look the row up, submit the wrong modifier, read the rejection, and resubmit XS inside the same claim. Causal reflection keeps the accepted answer and can use it on the next claim in the case. The baseline is the same model, with the same text and the same payer responses, and no memory between claims. Claude sees the same claims and has no memory between them either.

## The evaluation

There are 20 claims: 4 cases, 5 claims each. The cases are the first four indicator-1 additions in the October 1, 2026 practitioner change file, in code order:

| Pair | What the row says | What this payer pays |
| --- | --- | --- |
| 00530 / 0932T | Modifier allowed, effective October 1, 2026 | `pay` / `XS` |
| 00532 / 0932T | Modifier allowed, effective October 1, 2026 | `pay` / `XS` |
| 00534 / 0932T | Modifier allowed, effective October 1, 2026 | `pay` / `XS` |
| 00537 / 0932T | Modifier allowed, effective October 1, 2026 | `pay` / `XS` |

Every claim names the two codes, the date of service October 15, 2026, and this sentence: "The column-two service was performed on a separate anatomic site." The claim text does not include the edit row, and it does not say that this payer wants XS.

The model has two tools, on every claim:

- `lookup_edit` returns the CMS row when the model asks for that case's code pair and date. The row stays available on claims 2 through 5.
- `submit_answer` is the payer's decision. XS is accepted. Modifiers 59, XE, XP, and XU are rejected, and the rejection tells the model to resubmit with XS. The model may submit again inside the same claim.

Causal reflection stores the accepted answer. A rejected submission is visible inside that claim and is not the fact replayed onto the next one.

The headline is first-try correctness on claims 2 through 5: the first `submit_answer` was already `column_2: pay` / `modifier: XS`. The report also gives the final decision, how many submissions and lookups each claim took, and separate counts for a hold (no submission) and a submission the payer did not accept. Claim 1 is reported beside the headline. `summary.md` in each run directory is that report. Reprint it with:

```bash
.venv/bin/python -m ncci_bench report runs/<run-id>
```

## Dataset

The source is the public CMS practitioner PTP quarterly change file, effective October 1, 2026, posted September 1, 2026:

https://www.cms.gov/files/zip/medicare-ncci-2026q4-practitioner-quarterly-additions-deletions-revisions-ptp.zip

The copy in this repo is `data/ncci/practitioner-q4.zip`. `data/ncci/PIN.json` records the download URL and the SHA-256. The bench reads the text tables in that ZIP:

- 4,249 added edits (1,539 where a modifier is not allowed, 2,710 where a modifier may be allowed)
- 14 deleted edits
- 7 edits whose modifier indicator changed

The file lists code pairs and a modifier indicator. It does not include code descriptions, fees, or medical notes. The ZIP contains the AMA copyright notice that CMS ships with the file. This repo stores the pairs and indicators, not descriptions.

## Models

| Arm | What it is |
| --- | --- |
| `glm-baseline` | GLM 5.3 Flash, no memory between claims |
| `glm-causal` | GLM 5.3 Flash with causal reflection |
| `claude-haiku` | Claude Haiku 5.5 |
| `claude-sonnet` | Claude Sonnet 5.5 |
| `claude-opus` | Claude Opus 5.5 |

The published comparison is GLM 5.3 Flash against itself with causal reflection, and those two against Claude on the same 20 claims. DeepSeek V4.1 Flash is available as an arm and was not part of that run. List price for the tokens is included in the report. No prices are estimated beyond the published token rates.

## Run the evaluation

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Put `FIREWORKS_API_KEY` and `BASED_API_KEY` in `.env` for the GLM pair. Add `ANTHROPIC_API_KEY` only when running Claude. Keys stay local. Use `.venv/bin/python` for the commands below.

Preview one case, then run the GLM pair on all 20 claims:

```bash
.venv/bin/python -m ncci_bench run --episode payer --sessions 1 --arms glm-baseline,glm-causal --dry-run
.venv/bin/python -m ncci_bench run --episode payer --sessions 4 --arms glm-baseline,glm-causal
```

Claude on the same 20 claims:

```bash
.venv/bin/python -m ncci_bench run --episode payer --sessions 4 --arms claude-haiku,claude-sonnet,claude-opus
```

## Earlier episode

`--episode table-off` is an earlier setup. The lookup returns the row on claim 1 and `{"available": false}` on claims 2 through 5. There are 50 claims, 10 cases. The score is exact match on claims 2 through 5, and a missing answer counts as a miss. Those results are the second section of [RESULTS.md](RESULTS.md). Omitting `--episode` runs the payer episode.

```bash
.venv/bin/python -m ncci_bench run --episode table-off --sessions 6 --arms glm-baseline,glm-causal --dry-run
.venv/bin/python -m ncci_bench run --episode table-off --sessions 10 --arms glm-baseline,glm-causal
.venv/bin/python -m ncci_bench run --episode table-off --sessions 10 --arms claude-haiku,claude-sonnet,claude-opus
```

`--sessions 6` is 30 claims, two cases of each edit type. `--sessions 10` is the full 50.

## Scope

This evaluation covers one payment decision: the current PTP edit for a code pair on one date of service, and which modifier this payer will accept. The code pairs are real CMS changes. The claim text around them is written for the evaluation. The four published cases all share column-two code `0932T`. Medical necessity, appeal letters, and dollar amounts are outside this score.
