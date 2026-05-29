# Deploy Credentials

This folder holds the per-environment SSH private keys used by
`docex release <env>` (fixed foundation only). For the smoke test the
target host is `localhost` on the dev machine, but `docex release`
still drives ansible against it over SSH, so an SSH keypair is still
required.

Private keys (`stage`, `prod`) are gitignored. Public keys (`*.pub`) may
be committed.

For setup steps, see `../../../PRE_CUT_CHECKLIST.md` § "Fixed deploy
credentials".
