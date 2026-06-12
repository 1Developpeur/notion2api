# accounts.json Usage

Use the local login helper to create or refresh account configuration:

```bash
python login.py
```

The helper is intended for local use only. It creates the account fields required by the API service and writes them to local configuration files that must not be committed.

## Security notes

- Do not commit `accounts.json`, `.env`, browser cookies, or session tokens.
- Keep account configuration files in `.gitignore`.
- If a login session expires, rerun the local login helper and restart the service.
- Prefer separate low-privilege accounts for automation.

## Multiple account format

```json
[
  { "profile_name": "default", "token_v2": "...", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..." },
  { "profile_name": "backup", "token_v2": "...", "space_id": "...", "user_id": "...", "space_view_id": "...", "user_name": "...", "user_email": "..." }
]
```

The first healthy account is treated as primary. Failed accounts rotate to the next account after a short cooldown.
