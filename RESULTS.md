# Results

## The edit row stays available

Medicare's PTP edit table lists procedure-code pairs and whether a modifier can still get the second code paid. These 20 claims use four real rows from the public practitioner changes effective October 1, 2026. Each case is five claims for one pair. The model can look that row up on every claim. The row says a modifier is allowed. This payer accepts XS and rejects 59, XE, XP, and XU. After a rejection, the model can resubmit XS inside the same claim.

The score is the first submission on claims 2 through 5: was it already `pay` / `XS`? Claim 1 is where the payer's answer can be learned. Final is the payment after any resubmission. Submits is the average number of submissions on those later claims. A hold is a claim with no submission. An unaccepted claim ended on a submission the payer rejected. Both of those were zero.

GLM runs are `20261116T012256Z`. Claude runs are `20261116T022233Z`. No request failed. Every lookup returned the row.

### Score and cost

Costs are list price for all 20 claims. First-try and final rates are claims 2 through 5 (16 claims).

| Model | First try, claims 2–5 | Final | Submits | Cost |
| --- | ---: | ---: | ---: | ---: |
| GLM 5.3 Flash + causal reflection | 100% (16/16) | 100% | 1.00 | $0.009 |
| Claude Opus 5.5 | 100% (16/16) | 100% | 1.00 | $0.299 |
| GLM 5.3 Flash | 56.2% (9/16) | 100% | 1.44 | $0.008 |
| Claude Sonnet 5.5 | 25.0% (4/16) | 100% | 1.75 | $0.206 |
| Claude Haiku 5.5 | 6.2% (1/16) | 100% | 1.94 | $0.013 |

Every model finished on `column_2: pay` / `modifier: XS`. Causal reflection matched Opus: all 16 later claims were right on the first submission. **The cost was $0.009, about 3% of Opus at $0.299.** Haiku, Sonnet, and Opus together cost $0.52.

Haiku, Sonnet, and GLM with no memory also reached the right payment. On most later claims they needed a second submission, after the payer rejected the first. Haiku corrected 15 of those 16 claims inside the claim and still missed the first submission on the next one. Sonnet did that on 12 of 16.

### By case

Counts are the first submission on claims 2 through 5.

| Pair | Causal | Opus | GLM baseline | Sonnet | Haiku |
| --- | ---: | ---: | ---: | ---: | ---: |
| 00530 / 0932T | 4/4 | 4/4 | 1/4 | 1/4 | 0/4 |
| 00532 / 0932T | 4/4 | 4/4 | 1/4 | 0/4 | 0/4 |
| 00534 / 0932T | 4/4 | 4/4 | 4/4 | 2/4 | 0/4 |
| 00537 / 0932T | 4/4 | 4/4 | 3/4 | 1/4 | 1/4 |

On the opening claim, Opus sent XS first in all 4 cases. Causal reflection did so in 3. On `00534` / `0932T` it missed that opening claim, the payer rejected the submission, and the next four claims were XS on the first try. Sonnet sent XS first on the opening claim of `00530` / `0932T` and `00534` / `0932T`, then missed most of the claims that followed in those cases (1/4 and 2/4).

### What this slice covers

The four rows are ones where Medicare allows a modifier. All four share the second code `0932T`. The claim text is written for the evaluation. The saved answer is the final one, so a missed first try means that submission was not `pay` / `XS`. The text of the rejected modifier is not in the log.

## Earlier run: the lookup was turned off after claim 1

This is a different setup, kept so that run can be reproduced. The comparison above is the one where the model can look the row up on every claim. Here the lookup returned the row on claim 1 and `{"available": false}` on claims 2 through 5. A model that declined to guess a payment scored the same as a model that paid a bundled line.

Fifty claims, ten real edits. A claim counts only when both lines match: whether the second code is paid or denied, and the modifier (`none` or `XS`). A missing answer scores as a miss. GLM runs are `20261114T202044Z`. Claude runs are `20261114T203433Z`. No request failed. No lookup on claims 2 through 5 contained the edit row.

### Score and cost

| Model | Claims 2–5 | Claim 1 | Cost |
| --- | ---: | ---: | ---: |
| GLM 5.3 Flash + causal reflection | 95.0% (38/40) | 100% (10/10) | $0.029 |
| Claude Sonnet 5.5 | 40.0% (16/40) | 100% (10/10) | $0.638 |
| GLM 5.3 Flash | 37.5% (15/40) | 100% (10/10) | $0.026 |
| Claude Opus 5.5 | 15.0% (6/40) | 100% (10/10) | $1.693 |
| Claude Haiku 5.5 | 0.0% (0/40) | 100% (10/10) | $0.049 |

Every model read the row on claim 1 and answered all 10 opening claims correctly. The gap on this setup is what happens after the row is no longer returned.

On this setup, causal reflection is 55 points above Sonnet on claims 2 through 5, at about $0.03 against Sonnet's $0.64, and 80 points above Opus, at about $0.03 against Opus's $1.69. Haiku, Sonnet, and Opus together cost $2.38. Sonnet's 40% is the 16 deleted edits, where `pay` / `none` is the right answer. Opus is lower because it left most later claims blank.

### By edit type

Counts are claims 2 through 5.

| Edit type | Correct decision | Causal | Sonnet | GLM baseline | Opus | Haiku |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Deleted (16) | Pay, no modifier | 16 | 16 | 15 | 6 | 0 |
| Hard bundle (12) | Deny, no modifier | 12 | 0 | 0 | 0 | 0 |
| Indicator change (12) | Pay with XS, or deny | 10 | 0 | 0 | 0 | 0 |

Once the lookup returns nothing, Sonnet and the GLM baseline answer `column_2: pay` / `modifier: none`. That is the right answer for a deleted edit and the wrong answer for a hard bundle or a changed indicator. Sonnet submitted that answer on all 40 later claims. The GLM baseline submitted it on 36 and left 4 blank.

Causal reflection keeps the decision from claim 1 of that same case. It denied all 12 hard-bundle claims and got 10 of 12 indicator changes. The two misses were `column_2: pay` / `modifier: none`: one separate-site claim where the gold modifier is XS (`36836`/`36005`), and one changed indicator whose gold is deny (`33274`/`75820`).

### Why Opus scores below Sonnet on this run

Opus reads the edit as well as Sonnet does. Both were 10 for 10 on claim 1. On later claims, every answer Opus actually submitted was the same `column_2: pay` / `modifier: none` that Sonnet submitted on all 40. Six of Opus's 16 submissions were deleted edits, so they were correct. Ten were hard bundles or indicator changes, so they were wrong.

The rest of the gap is claims with no decision. Each claim allows four model turns. Sonnet looked the edit up two or three times and then submitted. Opus used all four turns on 35 of the 40 later claims, usually on another lookup. It submitted 16 of those 40. On 21 it produced no answer. On 3 the last message was that it would look the row up once more. Those 24 claims score as misses. The output limit was 2,048 tokens. Opus's longest later claim used 1,199, so the turns were not cut off by length.

Haiku submitted only the 10 opening claims. On all 40 later claims it looked the row up, received `{"available": false}`, and wrote that it would not guess a payment. A missing answer scores as a miss on this setup.

A model that answers `pay` / `none` whenever the row is hidden gets the 16 deleted edits and misses the other 24. Sonnet did that and scored 40%. Opus gave that answer when it chose to submit, and left most later claims blank, so it scored 15%.

### Cost

List price for the tokens each run actually used.

| Run | Claims | Cost |
| --- | ---: | ---: |
| GLM 5.3 Flash | 50 | $0.026 |
| GLM 5.3 Flash + causal reflection | 50 | $0.029 |
| Claude Haiku 5.5 | 50 | $0.049 |
| Claude Sonnet 5.5 | 50 | $0.638 |
| Claude Opus 5.5 | 50 | $1.693 |

## Scope

These are the public October 2026 PTP changes, with claim text written for the evaluation. The score is one payment decision: whether the column-two code is paid, and with which modifier. Medical necessity, appeal letters, and dollar amounts are outside this score.
