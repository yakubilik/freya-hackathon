# freya-statement-mock

Our mock of Freya Bank's statement services for the final case, on Cloudflare Workers. A stateless replay of the
pack's `test-environment/test-customers.json` (copied to `data/`): for a test customer / card / week it returns
exactly the listed HTTP status and body, after `delaySeconds` when present.

Deployed: see `.url`.

## Routes

From the bank's service contract (`sources/documents/2026-10-01-service-contract.md`). All `POST`, JSON in and out,
body `{"data": {...}, "call": {...}}`; only `data` decides the answer.

| Path | `data` lookup |
|---|---|
| `/voice/v1/cards.list` | `customerNo` |
| `/voice/v1/cards.balance` | `cardNumber` |
| `/voice/v1/statement.week.get` | `cardNumber` |
| `/voice/v1/statement.week.decide` | `cardNumber`, `newStatementWeek` |
| `/voice/v1/statement.week.change` | `cardNumber`, `newStatementWeek` |
| `/voice/v1/contact.email.get` | `customerNo` |
| `/voice/v1/statement.pdf.send` | `customerNo` |

`cardNumber` is the masked number as `cards.list` gives it (`540000******1234`); the cards.balance mask
(`5400********1234`) and a full number also resolve. Not in the file: the service's 404 from contract §4
(`FB_IVR_CHANNEL_102/120/121/107`), else 400 `INVALID_ARGUMENTS_ERROR`, in the contract's error envelope.
`GET /health` lists the routes.

## Deploy and check

```sh
set -a; source ~/.config/cloudflare/workers.env; set +a
cd mock/statement && npx -y wrangler@4 deploy
python3 check.py "$(cat .url)"     # every pack entry, exact status + body; exit 0 only if all match
```

Local: `npx -y wrangler@4 dev --port 8798`, then `python3 check.py http://localhost:8798`.
