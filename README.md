# Claude enablement content delivery platform (PoC)

Synthetic content only. Plan of record: [docs/IMPLEMENTATION-PLAN-content-delivery-platform-poc.md](docs/IMPLEMENTATION-PLAN-content-delivery-platform-poc.md).

```
content/     modules (en-GB), bundles, customer manifests, changelogs, ecosystem mock data
builder/     dk: gates, resolve, plan, build (MkDocs Material + WeasyPrint), deploy, dashboard, issues
auth/        sign-in Lambdas, static login pages, tests; build.py packages the Lambdas
infra/       Terraform: bootstrap -> delivery -> github; apply.sh; make-signing-key.sh
.github/     workflows: ci (gates + preview), deploy (main), preview-cleanup, report (daily governance)
```

## Local development

```bash
python -m venv .venv && .venv/Scripts/pip install -e "builder[test]" "moto[dynamodb,ssm,s3]" cryptography
.venv/Scripts/dk validate                      # gates G1-G5
.venv/Scripts/dk resolve --reverse             # module -> customers
.venv/Scripts/dk build --domain learn.example.test --no-pdf   # PDFs need Pango: built in CI
.venv/Scripts/dk match --offline               # ecosystem events -> modules -> customers
.venv/Scripts/python -m pytest -q builder/tests auth/tests
```

## First-time setup (in order)

All commands from the repository root in Git Bash, with `export AWS_PROFILE=cdn-poc`.

1. `infra/make-signing-key.sh` : CloudFront key pair; private key to Parameter Store only.
2. `infra/apply.sh bootstrap` : Terraform state bucket (local state).
3. `infra/apply.sh delivery` : S3, CloudFront, WAF, KVS, Lambdas, DynamoDB, SES, DNS, GitHub OIDC roles.
   SES sends each address in `ses_sandbox_recipients` a verification email: click it.
4. `infra/apply.sh github` : creates the public repo, branch protection, environments, labels, Actions variables.
5. Push this repository to it: `git remote add origin https://github.com/ChazTech3030/claude-enablement-poc.git && git push -u origin main`.
6. Actions > deploy > Run workflow with **full** ticked, then Actions > report > Run workflow.

## Demo script

1. `https://learn.customercdndemo.com/c/acme/` : sign-in page, code by email, branded Acme site, PDF with stamp.
2. Open `/c/brightwater/` with Acme cookies: back to sign-in (cross-tenant denial).
3. Edit a module on a branch, open a PR: `ci` runs gates, posts a preview under `/c/internal/previews/pr-N/`.
   Enable auto-merge; it merges when checks pass and `deploy` rebuilds only the affected customers.
4. Set `status: revoked` in `content/customers/acme.yml` and merge: Acme learners see "Access has ended".
5. Add a file under `content/ecosystem/events/` and merge: `report` raises a `change` issue naming the
   affected modules, owners and customers. Dashboard: `/c/internal/dashboard/`.
