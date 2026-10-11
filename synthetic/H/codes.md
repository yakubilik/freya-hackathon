# Portmann Bank ledger code sheet (collections, October 2026)

## close_call: outcome

| outcome | meaning | reason needed |
|---|---|---|
| pledge | at least one pledge recorded | no |
| paid | customer reports every product paid, nothing to pledge | no |
| transferred | the call was handed to a queue | yes |
| no_pledge | security passed, no pledge | yes |
| unverified | security not passed | yes |
| unreachable | the customer was not reached | yes |

## close_call: reason

| reason | goes with | meaning |
|---|---|---|
| wellbeing | transferred | hardship transfer |
| restructuring | transferred | payment plan request |
| human | transferred | customer asked for a person |
| refused | no_pledge | refused after the attempts, or did not want to talk |
| hardship | no_pledge | hardship, the transfer could not be made |
| dispute | no_pledge | a product was disputed |
| system_error | no_pledge | the pledge could not be recorded and nothing else was recorded |
| failed | unverified | wrong answers |
| declined | unverified | refused to answer |
| callback | unreachable | callback booked |
| no_callback | unreachable | no callback could be booked |
| wrong_number | unreachable | wrong number |
| deceased | unreachable | customer deceased |
| unclear | unreachable | person on the line not confirmed |

## add_note: reason

refused, hardship, paid, failed, not_mine, already_closed, amount_wrong

## transfer_to_agent: queue

wellbeing, restructuring, front_desk

## get_account: type

credit_card, personal_loan, car_loan

## Branch codes (reporting only, never used on a call)

ZH Zurich, BE Bern, BS Basel, GE Geneva
