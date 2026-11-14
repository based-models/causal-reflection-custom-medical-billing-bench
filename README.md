# Causal reflection custom medical billing bench

Fifty claims from the CMS practitioner PTP quarterly change file effective October 1, 2026. Each session is one real edit. Claim 1 can look the row up. Claims 2 through 5 get `{"available": false}` from the same tool. The causal arm keeps a successful answer on the medical workload. The baseline sees the same prompts and the same tool results, and no session.

The pre-registered score is exact match on claims 2 through 5, causal minus its own baseline. Claim 1 is reported and is not the win.

## The file

`data/ncci/practitioner-q4.zip` is the practitioner quarterly additions, deletions, and revisions file posted September 1, 2026:

https://www.cms.gov/files/zip/medicare-ncci-2026q4-practitioner-quarterly-additions-deletions-revisions-ptp.zip

`data/ncci/PIN.json` records the URL and the SHA-256. The text tables inside the ZIP are the source. This file has 4,249 additions (1,539 indicator 0 and 2,710 indicator 1), 14 deletions, and 7 modifier-indicator changes. A public write-up of a CO-97 bench reported 1,119 additions for this quarter. Deletions and indicator changes match that write-up. The addition count does not, and this bench pins the CMS file.

The ZIP includes the AMA copyright notice that CMS ships with the file. The parsed table stores code pairs and modifier indicators, not code descriptions.

## The fifty claims

Ten sessions, five claims each. Date of service is 2026-10-15. The disposition does not change inside a session.

| Order | Sessions | What the file says | Gold |
| --- | --- | --- | --- |
| 1, 2, 7, 8 | 4 deletions | The edit is deleted on 2026-10-01 | `column_2: pay` / `modifier: none` |
| 3, 9 | 2 indicator changes to 1 | A modifier is allowed, and every claim says the service was on a separate anatomic site | `column_2: pay` / `modifier: XS` |
| 4 | 1 indicator change to 0 | The new indicator is 0 | `column_2: deny` / `modifier: none` |
| 5, 6, 10 | 3 new indicator-0 edits | A modifier does not pay the second code | `column_2: deny` / `modifier: none` |

The first six sessions are the 30-claim gate: two of each edit type, including one `XS` change and one indicator-0 change.

`XS` is the only modifier the grader accepts, and only when the new indicator is 1 and the claim contains: "The column-two service was performed on a separate anatomic site." Modifiers 59, XE, XP, and XU are wrong. That rule is in the system prompt for every arm. The CMS row is not.

`lookup_edit` returns the row only on position 1 when the arguments name that session's pair and the date of service. Every other call returns `{"available": false}`. The result has no `outcome`, `status`, or `ok` field, so the medical pack does not store the lookup. `submit_answer` is exact on the two lines. Success stores the answer. Failure does not.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Dry-run, no API calls:

```bash
.venv/bin/python -m ncci_bench run --sessions 6 --arms glm-baseline,glm-causal --dry-run
```

Smoke, which you run. One session, five claims. Read the log for a finding on claims 2 through 5 before the gate:

```bash
.venv/bin/python -m ncci_bench run --sessions 1 --arms glm-baseline,glm-causal
```

Thirty-claim gate:

```bash
.venv/bin/python -m ncci_bench run --sessions 6 --arms glm-baseline,glm-causal
```

If positions 2 through 5 are ahead of the GLM baseline, run the other four sessions and then the Claude arms on the same fifty:

```bash
.venv/bin/python -m ncci_bench run --sessions 10 --arms glm-baseline,glm-causal
.venv/bin/python -m ncci_bench run --sessions 10 --arms claude-haiku,claude-sonnet,claude-opus
```

A tie or a loss on the gate stops there. Claude is not part of the gate command.

Arms are `glm-baseline`, `glm-causal`, `deepseek-baseline`, `deepseek-causal`, `claude-haiku`, `claude-sonnet`, and `claude-opus`. Decision calls use `tool_choice: auto` so a model can look the row up before it submits. The production API ignores `tool_choice`. Claude 5.5 requests omit temperature. Reprint a run with `python -m ncci_bench report runs/<run-id>`.
