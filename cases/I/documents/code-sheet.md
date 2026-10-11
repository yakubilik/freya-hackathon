# Tamsin Finance ledger code sheet (payments team, October 2026)

## close_call: outcome

| outcome | meaning | reason needed |
|---|---|---|
| promise | at least one promise recorded | no |
| paid | customer reports every product paid | no |
| transferred | handed to a queue | yes |
| no_promise | verified, no promise | yes |
| not_verified | security not passed | yes |
| not_reached | customer not reached | yes |

## close_call: reason

| reason | goes with | meaning |
|---|---|---|
| hardship | transferred, no_promise | hardship transfer accepted; or hardship, transfer declined, no promise |
| plan | transferred | payment plan request |
| human | transferred | customer asked for a person |
| refused | no_promise | refused after the attempt or did not want to talk |
| dispute | no_promise | the first unpaid product was disputed |
| service_error | no_promise | the promise could not be recorded |
| do_not_call | no_promise, not_verified | customer asked not to be called |
| failed | not_verified | wrong answers |
| declined | not_verified | refused to answer |
| callback | not_reached | callback booked |
| no_callback | not_reached | no callback could be booked |
| wrong_number | not_reached | wrong number |
| deceased | not_reached | customer deceased |
| unclear | not_reached | person on the line not confirmed |

## add_note: reason

refused, hardship, dispute, paid, service_error, do_not_call

## transfer_to_agent: queue

payments_team, hardship_team

## get_account: type

store_card, instalment_loan, auto_loan (spoken "installment loan")

## State codes (reporting only, never used on a call)

TX, AZ, NV, NM
