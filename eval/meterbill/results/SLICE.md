# meterbill slice: tokens per task by arm

cost_weighted = input + 1.25*cache_creation + 0.1*cache_read + 5*output. Grades: vis = visible suite, tgt = hidden target tests, keep = hidden keep/trap tests.

## Tasks

### C1

Means over reps (1); token columns are per session.

| metric | nothing | claudemd | clarity |
|---|---|---|---|
| input | 12.00 | 14.00 | 18.00 |
| cache_creation | 16,690 | 18,080 | 19,809 |
| cache_read | 114,651 | 156,569 | 172,879 |
| output | 3,166 | 3,518 | 2,583 |
| cost_weighted | 48,170 | 55,861 | 54,982 |
| turns | 9.00 | 8.00 | 9.00 |
| cost_usd | 0.11 | 0.12 | 0.12 |
| wall_s | 24.20 | 26.60 | 23.80 |
| files read | 4.00 | 1.00 | 0.00 |
| distinct files read | 4.00 | 1.00 | 0.00 |
| clarity-ctl reads | 0.00 | 0.00 | 1.00 |
| clarity-ctl writes | 0.00 | 0.00 | 2.00 |
| tool calls | Bash 3, Glob 1, Read 4 | Bash 6, Read 1 | Bash 8 |
| clarity-ctl verbs | - | - | close 1, start 1, status 1 |
| grade (rep 1) | vis P / tgt P / keep - | vis P / tgt P / keep - | vis P / tgt P / keep - |
| keep tests failed | - | - | - |
| cache/module-dict in diff | - | - | - |
| memory files changed | - | CLAUDE.md | AGENTS.md; EPOCHS/015_2026-11-11__plans-list-command/EPOCH.md; worklog.yaml |

Paired differences vs clarity (positive = the arm used more):

| pair | input | cache_creation | cache_read | output | cost_weighted | turns | cost_usd | wall_s |
|---|---|---|---|---|---|---|---|---|
| nothing - clarity (n=1) | -6.00 | -3,119 | -58,228 | 583 | -6,813 | 0.00 | -0.01 | 0.40 |
| claudemd - clarity (n=1) | -4.00 | -1,729 | -16,310 | 935 | 879 | -1.00 | 0.00 | 2.80 |

### T1

Means over reps (1); token columns are per session.

| metric | nothing | claudemd | clarity |
|---|---|---|---|
| input | 12.00 | 20.00 | 14.00 |
| cache_creation | 12,246 | 15,934 | 13,324 |
| cache_read | 97,104 | 209,840 | 127,592 |
| output | 1,970 | 3,669 | 2,258 |
| cost_weighted | 34,880 | 59,266 | 40,718 |
| turns | 6.00 | 11.00 | 7.00 |
| cost_usd | 0.08 | 0.12 | 0.09 |
| wall_s | 20.40 | 35.10 | 21.80 |
| files read | 0.00 | 0.00 | 0.00 |
| distinct files read | 0.00 | 0.00 | 0.00 |
| clarity-ctl reads | 0.00 | 0.00 | 2.00 |
| clarity-ctl writes | 0.00 | 0.00 | 3.00 |
| tool calls | Bash 4, Glob 1 | Bash 9, Grep 1 | Bash 6 |
| clarity-ctl verbs | - | - | close 1, note 1, show 2, start 1 |
| grade (rep 1) | vis P / tgt P / keep F | vis P / tgt P / keep P | vis P / tgt P / keep P |
| keep tests failed | test_keep::test_override_edited_between_invoices_is_used[same_resolver_object] | - | - |
| cache/module-dict in diff | - | - | - |
| memory files changed | - | CLAUDE.md | AGENTS.md; EPOCHS/008_2026-11-11__per-build-invoice-tax-lookup/EPOCH.md; worklog.yaml |

Paired differences vs clarity (positive = the arm used more):

| pair | input | cache_creation | cache_read | output | cost_weighted | turns | cost_usd | wall_s |
|---|---|---|---|---|---|---|---|---|
| nothing - clarity (n=1) | -2.00 | -1,078 | -30,488 | -288 | -5,838 | -1.00 | -0.01 | -1.40 |
| claudemd - clarity (n=1) | 6.00 | 2,610 | 82,248 | 1,411 | 18,548 | 4.00 | 0.03 | 13.30 |

## Replay (memory writing), epochs 1-8

| arm | epoch | turns | input | cache_creation | cache_read | output | cost_weighted | wall_s |
|---|---|---|---|---|---|---|---|---|
| claudemd | e1 | 3 | 6 | 9,358 | 43,558 | 1,762 | 24,869 | 13.50 |
| claudemd | e2 | 3 | 6 | 7,256 | 43,633 | 1,194 | 19,409 | 10.80 |
| claudemd | e3 | 3 | 6 | 8,881 | 45,763 | 1,919 | 25,279 | 15.00 |
| claudemd | e4 | 3 | 6 | 8,183 | 44,787 | 1,029 | 19,858 | 10.80 |
| claudemd | e5 | 3 | 6 | 8,511 | 45,195 | 1,179 | 21,059 | 11.50 |
| claudemd | e6 | 3 | 6 | 8,869 | 46,279 | 1,610 | 23,770 | 12.90 |
| claudemd | e7 | 3 | 6 | 9,532 | 47,805 | 1,608 | 24,742 | 14.70 |
| claudemd | e8 | 4 | 8 | 10,426 | 68,086 | 1,925 | 29,474 | 15.60 |
| clarity | e1 | 4 | 8 | 10,463 | 65,203 | 1,591 | 27,562 | 14.10 |
| clarity | e2 | 4 | 8 | 7,906 | 62,136 | 947 | 20,839 | 10.20 |
| clarity | e3 | 3 | 6 | 8,669 | 45,653 | 1,276 | 21,788 | 12.40 |
| clarity | e4 | 4 | 8 | 7,457 | 60,591 | 1,028 | 20,528 | 11.30 |
| clarity | e5 | 6 | 12 | 9,131 | 99,608 | 1,575 | 29,262 | 19.00 |
| clarity | e6 | 5 | 10 | 8,600 | 81,356 | 1,495 | 26,371 | 15.20 |
| clarity | e7 | 4 | 8 | 8,966 | 64,314 | 1,483 | 25,062 | 14.60 |
| clarity | e8 | 4 | 8 | 8,311 | 62,761 | 1,237 | 22,858 | 13.70 |

Memory at e08:

| arm | files | chars |
|---|---|---|
| claudemd | 1 | 11,033 |
| clarity | 6 | 23,805 |
