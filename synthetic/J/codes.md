# Kestrel Bank arrears ledger codes (issue October 2026)

## close_call: result

| result | meaning | detail required |
|---|---|---|
| arranged | at least one arrangement recorded | no |
| paid | every product reported paid, nothing to arrange | no |
| routed | the call was transferred | yes |
| no_arrangement | verified, nothing arranged | yes |
| not_verified | security not passed | yes |
| not_reached | customer not reached | yes |

## close_call: detail

| detail | with | meaning |
|---|---|---|
| customer_care | routed | hardship transfer |
| arrangements | routed | payment plan request |
| human | routed | customer asked for a person |
| complaint | routed | customer wants to complain |
| refused | no_arrangement | refused after the attempts, or did not want to talk |
| hardship | no_arrangement | hardship, transfer declined |
| disputed | no_arrangement | the first unpaid product was disputed |
| failed | no_arrangement | recording failed |
| do_not_call | no_arrangement, not_verified | asked not to be called |
| failed | not_verified | wrong answers |
| declined | not_verified | refused to answer |
| callback | not_reached | callback booked |
| no_callback | not_reached | no callback possible |
| wrong_number | not_reached | wrong number |
| deceased | not_reached | customer deceased |
| unclear | not_reached | person on the line not confirmed |

## add_note: flag

refused, hardship, disputed, paid, failed, do_not_call

## transfer_to_agent: queue

customer_care, arrangements, complaints, agent

## get_account: kind

card, loan, mortgage_arrears

## Region codes (reporting only, never used on a call)

LDN, MID, NTH, SCO, WAL
