# Deploy Credentials

The elastic foundation uses AWS credentials at `~/.aws/credentials`, not
private keys in this folder. This directory is kept (with this README
and `.gitignore`) only to mirror the standard project layout — there is
nothing for the operator to place here.

AWS credentials are verified in `../../../PRE_CUT_CHECKLIST.md`
§ "A.1 Tooling"; there has never been an "Elastic AWS credentials"
section for this file to point at.
