# Config

Non-secret, per-environment values (e.g. a URL that differs by environment).
Keys are **declared** in each core service's `config:` block in `infra.yml`
(committed, LLM-readable); the per-env **values** live in the `<env>.env` files
here and are gitignored. Manage with `docex config scaffold|status|set|get|copy`.
See `config_and_secrets.md § The Three Categories`.
