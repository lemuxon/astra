# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead:
**Security → Advisories → Report a vulnerability** on this repository.

This project talks to a cryptocurrency exchange with API keys that can place
orders. A disclosed flaw could cost someone real money, so please report
privately and give a reasonable window before publishing.

## What counts as a security issue here

- Anything that could leak credentials (`.env` values, API keys, Telegram
  tokens) into logs, the dashboard, Telegram messages, or committed files
- A path where an order can be placed that bypasses the veto chain, the kill
  switch, or the risk limits
- A way for the dashboard (`127.0.0.1:8080`) to be reached or driven from
  outside the local machine
- Anything that writes to live trading state from an unauthenticated path

## Known design limits (not vulnerabilities)

- The dashboard has no authentication by default. It binds to localhost only.
  Set `PANEL_USER` / `PANEL_PASS` before exposing it anywhere.
- Telegram authorisation is a single `CHAT_ID` check. Anyone holding the bot
  token can message the bot; the chat-id gate is what stops commands executing.
- `.env` is plaintext on disk. The bot never transmits it, but anyone with
  filesystem access has your keys.

## For users of this code

- **Use testnet keys** unless you have deliberately decided otherwise.
- Give the API key only the permissions it needs. **Never enable withdrawal.**
- Restrict the key to your IP address in Binance's API settings.
- Never commit `.env`. It is gitignored, but verify with
  `git check-ignore -v .env` after any change to `.gitignore`.
- If a key is ever pasted into a chat, an issue, a log excerpt or a screenshot,
  treat it as compromised and rotate it.
