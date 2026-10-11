# Ashworth Mutual ledger codes (extract, October 2026)

## close_call outcome codes

| Code | Meaning | Reason required |
|---|---|---|
| PTP | promise to pay recorded | no |
| PAID | customer reports the arrears paid, nothing to promise | no |
| XFER | call transferred | yes |
| NOPTP | verified, no promise | yes |
| IDFAIL | security not passed | yes |
| NOCON | customer not reached | yes |

## close_call reason codes

| Code | With | Meaning |
|---|---|---|
| WELF | XFER | hardship transfer |
| ARR | XFER | arrangements (payment plan) transfer |
| HUM | XFER | customer asked for a person |
| COMP | XFER | complaint |
| REF | NOPTP | refused |
| HARD | NOPTP | hardship, no transfer |
| DISP | NOPTP | disputed |
| ERR | NOPTP | promise could not be recorded |
| DNC | NOPTP, IDFAIL | do not call again |
| FAIL | IDFAIL | wrong answers |
| DECL | IDFAIL | declined to answer |
| CB | NOCON | callback booked |
| NOCB | NOCON | no callback could be booked |
| WRONG | NOCON | wrong number |
| DEC | NOCON | customer deceased |
| UNCLR | NOCON | identity of the person on the line unclear |

## add_note reason codes

REF refused, HARD hardship, DISP disputed, PAID reported paid, ERR recording failed, DNC do not call.

## transfer_to_agent queues

financial_support, complaints, arrangements, agent

## Product type codes

CC credit card, PL personal loan, HP hire purchase

## Region codes (for reporting only, not used on calls)

N north, S south, SC Scotland, W Wales
