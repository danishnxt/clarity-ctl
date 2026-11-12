# e24 covariates (recorded before any e24 task session; nothing fixed)

## CLAUDE.md lines per epoch (claudemd arm, from memory snapshots; seed is 15 lines, cap in its own text is 200)
e1 48, e2 53, e3 59, e4 61, e5 63, e6 72, e7 79, e8 85, e9 94, e10 95, e11 100, e12 105, e13 114, e14 117, e15 124, e16 131,
e17 135, e18 140, e19 145, e20 148, e21 153, e22 158, e23 164, e24 170 (33,547 chars). Never pruned; under the cap at e24.

## Fact presence at e24
All of f16a, f17a, f18a, f19a, f20a, f21a, f22a, f23a, f24a, f24b are present in both arms' e24 memory, each with its rule and
reason. claudemd carries them as lines in `CLAUDE.md` (Decisions / In progress, lines 111-167: "Payment reminders ... second 28
days (changed from 21 ...)", "Automatic allocation ... oldest due date first, ties ... lower invoice number ... leftover ...
wallet ... skip VOID", "Data purge ... 25 months ... rejects 30 days (changed from 90) ... HARD RULE ...", "Credit notes
still produce CN-<TENANT>-... User rules for when built: ... CN-<ENTITY>-...", "Payment allocation extra rules ... 0.50 ...
6900", "Ledger credit notes NOT built ... ORIGINAL invoice ..."). clarity carries them as notes on ideas #41 (reminders: +7,
+21 then "CHANGE OF PLAN ... +28", +35 with finance@meterbill.example, 5.00 EUR and 30-day rules), #45 (allocation, wallet
leftover, skip void), #47 and #52/#53 (retention, 90 superseded by 30, hard rule), #58 (credit note entity), #59 (FX at
payment date, 0.50 write-off to 6900), #38 (ledger credit notes, original accounts).

## Superseded values in clarity's AGENTS.md block (Standing decisions)
- 90-day rejects: shown. #47 ("... files in data/rejects are kept 90 days.") is listed as a standing decision next to #52
  ("... SUPERSEDES #47's note: ... kept 30 days (not 90) ..."); the block does not retire #47.
- 21-day second reminder: not shown in the block (reminders are an idea, #41; the 21 and the change to 28 are in its notes).
- Older superseded entries are still listed too: #6 (lru_cache read-once) and #19 (event_id dedupe; reversed by #24).

## Memory size at e24
claudemd 33,547 chars (1 file); clarity worklog.yaml 54,949 chars, AGENTS.md 9,070 chars, plus EPOCHS and config.
