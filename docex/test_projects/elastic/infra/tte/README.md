# TTE store

Generated engine credentials (transfer-table `kind: minted` env vars, e.g.
`POSTGRES_PASSWORD`). `docex` mints these into `<env>.env` here on the first
bring-up / release that needs them; they are never hand-edited and never
committed. See `config_and_secrets.md § TTE Vars`.

For dev/test this local `<env>.env` is the authoritative store. For fixed
stage/prod the authority is the host `/opt/<project>/<env>/tte.env`; for elastic
it is SSM — so this dir may be empty for those envs.
