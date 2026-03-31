# Code Review Rules — Trading Bot

## General
- Comments and logs in Spanish; code (variables, functions, classes) in English
- snake_case for Python variables and functions
- UPPER_SNAKE_CASE for constants
- camelCase for JavaScript/React

## Python
- No bare except clauses — always catch specific exceptions
- Never set AUTO_EXECUTE=true without explicit WR >= 55% verification
- Never change ACCOUNT_MODE from demo to real without explicit authorization
- Never drop the MongoDB signals collection
- Use logger (not print) for all output
- Logs must include emoji + context (e.g. logger.info('✅ MongoDB conectado'))
- Strategy classes must have Strategy suffix and implement .evaluate()

## Critical modules (auto_exec.py, circuit_breaker.py, risk_manager.py)
- Never disable the circuit breaker
- Never skip WR filter checks
- MAX_TD_FALLBACK_PER_CYCLE must remain <= 5

## JavaScript / React
- camelCase for all identifiers
- No console.log in production paths — use console.error for errors only
- localStorage keys must follow pattern: wr_history_OTC_{SYMBOL}

## Security
- Never commit .env files or credentials
- Never hardcode API keys, tokens or session cookies
- PO_CI_SESSION and PO_SSID must come from environment variables only

## Git
- Commit messages: tipo: descripción en inglés, imperativo, conciso
- Types: feat:, fix:, refactor:, chore:
