# Implementation Plan: Claude Enablement Content Delivery Platform (PoC)

**Status:** Plan of record for the proof of concept. Nothing built yet.
**Date:** 27 September 2026 (revision 3: forge moved to GitHub, no self-hosted compute, demo cut for 28 September 2026; decisions 2.18 to 2.27 added. Revision 2: review fixes; decisions 2.14 to 2.17)
**Audience:** Claude Code and the engineer supervising it.
**Companion documents:** `HANDOVER-content-delivery-platform.md`, `OPERATIONS-content-delivery-platform.md`, `TECHCONSIDERATION-content-delivery-platform.html`. Where this plan conflicts with them, **this plan wins**. Section 2 lists every supersession.

---

## 0. Working rules for Claude Code

1. **This is a PoC on GitHub Free, in a public repository (2.18).** The production forge is undecided: GitHub or Version 1's enterprise GitLab. Keep forge-specific code thin. Gates, planning, builds, deploys, reports and matching live in `dk`; workflows only call it. A forge move then rewrites workflow YAML and the issue client, not the logic.
2. **Everything is infrastructure as code.** Terraform for AWS and GitHub configuration. Console or manual steps are allowed only where section 7.5 lists them. If you find yourself needing a manual step not on that list, stop and ask.
3. **Do not re-propose rejected options** (handover section 7, plus section 2 of this plan) without new information. In particular: no ASGs, no per-customer compute, no Cognito, no OIDC federation for learner sign-in, no Atlassian, no session identifier in logs. GitHub Actions OIDC to AWS for CI is permitted (2.20); the rule refers to learner sign-in only.
4. **Work phase by phase** (section 8). Do not start a phase until the previous phase's exit criteria pass. Report which acceptance tests (section 9) a phase makes runnable. Section 8.2 sets the demo cut.
5. **Ask before deviating.** If a specified resource, setting or behaviour turns out not to exist or not to work as described, say so plainly, propose the nearest working alternative, and wait for a decision. Several items are flagged **VERIFY**; check them against current AWS or GitHub documentation before relying on them.
6. **Naming.** All AWS resources use the prefix variable `name_prefix`, default `fde-delivery`. Tag everything with `project`, `environment = "poc"` and `managed_by = "terraform"`.
7. **Language.** Content, UI strings, changelogs and generated documents use UK English.
8. **Learner-facing web assets** (login page, gate page, dashboard) are vanilla HTML, CSS and JavaScript with no build step.
9. **No long-lived secrets in GitHub.** CI authenticates to AWS through OIDC (7.3); there are no AWS keys and no Actions secrets. Run-time secrets live in SSM Parameter Store as `SecureString` parameters (standard tier, no charge) and are read only by the Lambdas.
10. **Cost is a design constraint.** This PoC is sized for demonstration load (a few requests per second at most). Do not add capacity, redundancy or managed services beyond this plan without asking. Section 7.6 lists the cost posture.

---

## 1. Scope

### In scope for the PoC

This is Phase 1 of the original design, amended by section 2:

- A single public GitHub repository on GitHub Free, GitHub-hosted runners, and OIDC from Actions to AWS
- The content model (modules, bundles and manifests with reverse lookup) and synthetic content
- MkDocs Material site builds and WeasyPrint stamped PDFs, regenerated in the same workflow run as the site
- Build gates and selective rebuilds of affected customers only
- S3 and CloudFront delivery with signed-cookie access and a per-customer revocation switch
- Email one-time-code authentication against per-customer domain allowlists
- Pull request preview URLs and native approval-gated auto-merge
- CloudFront standard logging v2 with personal fields excluded at source, and a minimal Athena aggregate
- A static freshness dashboard, automatic overdue-review issues, and an issue-closure audit
- Phase 2 readiness: a controlled feature vocabulary, the monitored-source list, and `dk match` over mock change events (6.11)

### Out of scope for the PoC (Phase 2 or later)

- The live ecosystem monitoring worker (feed polling and page diffing). Its output contract and the matching step are in scope (6.11).
- Delivery register and FDE pre-delivery notifications. The notify job is stubbed; see 6.8.
- Delivery-aware PDF prioritisation (see 2.4)
- Monthly branded engagement reports. The Athena layer is built; the report renderer is not.
- Localisation. The `en-GB` segment is reserved only.

### Removed from the roadmap

- OIDC federation for learner sign-in (former method B / Phase 3)
- Identity-backed completion tracking (former Phase 3). No persistent learner identity exists to back it.
- A self-hosted forge and its operations: host, runners, backups, restore, patching, hardening, scheduling (rev 3; 2.21)

---

## 2. Decisions register

| # | Decision | Supersedes | Reasoning |
|---|---|---|---|
| 2.1 | **Superseded by 2.18 (rev 3).** **Forge is GitLab Free**: the `gitlab-ee` Omnibus package with no licence file, self-hosted, PoC only. The production target is Version 1's enterprise GitLab. | GitLab CE (handover s3, s6; tech consideration stack table "MIT Expat") | Free upgrades in place with a licence key, and the pipelines are portable. The EE licence terms are acceptable for a PoC. |
| 2.2 | **Superseded by 2.21 (rev 3).** **GitLab host sized to GitLab's memory-constrained minimum, not the 1,000-user recommendation: `t3a.large` (2 vCPU, 8 GiB, x86_64)**, with the memory-constrained Omnibus settings in 7.2. **One separate, small runner instance.** | `t4g.large` with co-located runners (A2); the 8 vCPU / 16 GB sizing in the previous draft of this plan | Demo load is a handful of users at about 2 requests per second. **Checked against GitLab's documentation, 27 September 2026:** the installation requirements page says a single node in a memory-constrained environment "can run with at least 8 GB of memory", and the memory-constrained environments page sets the CPU minimum at "4 CPU cores of ARM7/ARM64 or 1 CPU core of AMD64". A 2-vCPU Graviton instance falls below that; 2 vCPU on x86 meets it. `t3a.large` is therefore the cheapest compliant option. Moving to a compliant Graviton instance (4 vCPU) would cost more, and dropping below 8 GiB would break the memory rule. GitLab also advises against burstable instances; this is **accepted for the PoC**, and the instance runs with `cpu_credits = "standard"` so CPU bursts cannot add surplus-credit charges. Runners stay off the GitLab host, per GitLab's advice. |
| 2.3 | **Authentication is email one-time code only.** Cookie minting is folded into the verify handler. No pluggable-method abstraction. Lambda function URLs behind CloudFront OAC replace API Gateway. | Pluggable verification (handover s6), method B, Phase 3 federation, API Gateway | Simplest design that meets the requirement. Federation is dropped by decision; the reintroduction cost is accepted. |
| 2.4 | **PDFs regenerate in the same pipeline as the site, for every affected customer, on every deploy.** The PDF always matches the site. | Scheduled PDF regeneration (handover s5; tech consideration build fan-out risk) | Ensures the PDF is always current before a delivery. Later, Phase 2 may prioritise PDF builds for customers with an imminent delivery, using the delivery register. |
| 2.5 | **Per-customer revocation through a CloudFront KeyValueStore** read by the viewer-request function. | Implicit "revoke on the agreed date" (ops s7) | Signed cookies cannot be revoked individually. Key rotation affects every customer. |
| 2.6 | **Personal log fields are excluded at source** using CloudFront standard logging v2 field selection: no `c-ip`, no cookies, no query string. | Truncating or hashing IP on ingest | Makes the control structural, like the session-identifier omission. |
| 2.7 | **Superseded by 2.20 (rev 3).** **CI reaches AWS through the runner's instance profile.** One runner instance carries one role covering deploy and preview writes. Deploy jobs are restricted to protected refs by job rules. | (unspecified); two-runner split in the previous draft | Cost. **Accepted PoC risk:** any job on the runner, including an MR preview job, could technically write to live customer prefixes and read the automation token. Decision 2.14 narrows this considerably: content authors cannot change the pipeline definition, and `mkdocs.yml` (including any hooks or plugins) is generated by the builder, never read from `content`. So a Developer on `content` has no route to run arbitrary code on the runner. The residual risk sits with `platform` maintainers, who are trusted. On the enterprise GitLab, split into two runners and roles, or use OIDC. |
| 2.8 | **Partly superseded by 2.22 (rev 3): approval is now native; the closure audit remains a job.** **Governance rules GitLab Free cannot enforce are enforced by jobs**: approval-gated auto-merge (2.15), and an issue-closure audit. | Policy-only enforcement (ops s8) | Required approvals and scoped labels are paid-tier features. |
| 2.9 | **Superseded by 2.21 (rev 3).** **GitLab is publicly reachable over HTTPS and protected by GitLab's own controls**, hardened as specified in 7.2: sign-up disabled, 2FA enforced, public and internal visibility restricted, throttling on, security releases applied promptly. It is exposed directly from a public subnet, with no ALB. TLS comes from Omnibus's built-in Let's Encrypt integration. Port 443 is open to `var.gitlab_ingress_cidrs` (default `0.0.0.0/0`). Port 80 is open to the internet for ACME HTTP-01 validation and the HTTP-to-HTTPS redirect. No SSH ingress. | ALB with ACM, and ingress restricted to Version 1 ranges (previous drafts) | The PoC is built in a personal AWS account before Version 1 buy-in, so no corporate IP range is available. The design must let other FDEs author without setup on their side (AT-18). **Accepted PoC risk:** a public GitLab is exposed to exploitation of unpatched vulnerabilities between releases. This is mitigated by the hardening, scheduled stops and synthetic-only content. `gitlab_ingress_cidrs` can be narrowed to a single address when not demoing. |
| 2.10 | **Learner email addresses are never persisted.** Code records are keyed by HMAC of the address. | Learner email retention and deletion runbook (ops s2, s7, M14) | Removes most of the data subject handling. SES's own logs are the only residual. |
| 2.11 | **One CloudFront distribution serves everything.** Previews and the dashboard sit behind the same learner authentication under the reserved slug `internal` (`/c/internal/...`), with an allowlist of Version 1 email domains. No second distribution and no second WAF. | Separate IP-restricted `internal` distribution (previous draft) | Reuses the auth path and removes a web ACL. It also dog-foods the learner sign-in on every review. |
| 2.12 | **Superseded by 2.21 (rev 3).** **Compute runs on a schedule.** EventBridge Scheduler stops both instances outside `var.working_hours` (default 07:00 to 19:00, Monday to Friday, Europe/London). A manual start is always possible. Anything that runs from cron on the instances (Let's Encrypt renewal, backups) is scheduled inside working hours. | Always-on | About two-thirds of compute cost removed. Customer endpoints are unaffected, because serving has no compute. |
| 2.13 | **Built in a personal AWS account, with synthetic content only.** No customer material and no Version 1 material is placed in the platform. Learner email codes may be sent to Version 1 addresses for `/c/internal/`. | Dedicated Version 1 project account (handover s3) | Proves the design before seeking buy-in. The migration target is a Version 1 account and the enterprise GitLab, and every stack is parameterised for that move. |
| 2.14 | **Superseded by 2.19 (rev 3).** **The `content` pipeline definition lives in `platform`.** The `content` project's CI/CD configuration path is set to `ci/content.yml@fde-delivery/platform`, so `content` has no `.gitlab-ci.yml` of its own. The builder tag is pinned in that file. | `content/.gitlab-ci.yml` including a template; builder pinned by `var.builder_tag` | An MR on `content` runs the pipeline from `platform`, so authors cannot remove gates or the approval logic from their own MR. This setting is available on Free. Pinning the builder tag in `platform` git records it in history, and 6.3 detects changes to it. |
| 2.15 | **Superseded by 2.22 (rev 3).** **Approved content MRs merge automatically.** A project webhook on merge request events calls a pipeline trigger on `content` `main`. A job in that triggered pipeline reads `TRIGGER_PAYLOAD`; when the event is an approval by someone other than the author, it sets the MR to auto-merge through the API. Only Maintainers may merge to `main`, and the `gitlab-bot` user is a Maintainer; FDEs are Developers. | MR `approval-check` job that fails the MR pipeline until approved (previous draft) | No extra compute or services: webhook-triggered pipelines and `TRIGGER_PAYLOAD` are available on Free. The approval-check design would have failed every MR pipeline until someone re-ran it after approval. Here, an approval is the merge action. |
| 2.16 | **Superseded by 2.23 (rev 3).** **GitLab automation uses a project access token on `content`** (`gitlab_project_access_token`, role Maintainer, scope `api`, 90-day expiry), not a root token. GitLab creates a bot user for it, referred to here as `gitlab-bot`. | Root personal access token (previous draft) | A token that any runner job can read must not be an instance admin token. This one can act only on `content`. Project access tokens are available on self-managed Free, need no user account or 2FA handling, and are created entirely in Terraform. The Terraform `gitlab` provider runs from the workstation with the admin's own token, which is never stored on the platform. |
| 2.17 | **S3 returns real 404s, and directory URLs resolve to `index.html`.** The OAC principal is granted `s3:ListBucket`, the distribution sets `default_root_object`, and the `gate` function rewrites `/c/{slug}/…/` to `…/index.html`. | Implicit (S3 403 for missing keys) | Without `ListBucket`, S3 returns 403 for a missing key. That 403 would pass through the distribution-wide 403 → gate-page rule and send a signed-in learner into a login loop. MkDocs directory URLs also need the rewrite, because S3 origins behind OAC do not resolve index documents. |
| 2.18 | **Forge is GitHub Free, with public repositories on the owner's free personal account.** Content is synthetic only (2.13), so public visibility is acceptable. Stakeholders are aware. The enterprise forge choice (GitHub or Version 1's enterprise GitLab) is deferred. | 2.1 | On the Free plan, branch protection, required reviews and auto-merge work only on public repositories. GitHub Pro would allow private repositories and was declined for cost. Removes the forge host, its operations and most of the cost (7.6). |
| 2.19 | **One monorepo for the PoC** (layout in section 4). `.github/CODEOWNERS` makes the owner the required reviewer for everything outside `content/`. Because `builder/` is in the same repository, a change under `builder/` is how 6.3 detects a builder or theme change. | 2.14; two projects; `BUILDER_TAG` pinning and `state/last-deployed-builder-tag` | One repository, one set of protections, one PR to change content and builder together. Code owner review replaces the cross-project CI configuration path as the control on workflow and builder changes. The split into platform and content repositories is technical debt (section 12). |
| 2.20 | **CI reaches AWS through GitHub Actions OIDC** with two IAM roles (7.3). `deploy` is trusted only for `repo:{owner}/{repo}:environment:production` and carries the deploy permissions. `preview` is trusted for `repo:{owner}/{repo}:pull_request` and writes only to `c/internal/previews/*`. GitHub-hosted `ubuntu-24.04` runners; no runner instance. | 2.7 | Short-lived credentials, no stored AWS keys, and a real split between PR and deploy permissions at no cost. This resolves the accepted risk in 2.7. The `production` environment admits only `main` (7.2), so a PR that edits a workflow still cannot obtain the deploy role. Fork PRs receive no OIDC token and are not previewed. |
| 2.21 | **No self-hosted forge and no compute.** Removed: the `foundation`, `gitlab-config` and `runner` stacks; the VPC; the GitLab host; backups; the scheduler; patching; hardening; the automation token; the webhook and trigger. Stacks are `bootstrap` → `delivery` → `github`. | 2.2, 2.9, 2.12 | Follows from 2.18. Serving already had no compute, and CI now runs on GitHub-hosted runners. AT-16 and AT-20 are removed. |
| 2.22 | **Approval and auto-merge are native.** Branch protection on `main` requires one approving review, dismisses stale approvals on push, and requires code owner review and the required status checks. Authors enable auto-merge on their own PR. GitHub does not let authors approve their own PRs. | 2.15; the approval part of 2.8 | No custom job, token or webhook. Every control the rev 2 job emulated is a platform setting on a public repository. |
| 2.23 | **Issues are GitHub Issues.** The dashboard, overdue-issue, closure-audit and `dk match` jobs call the GitHub REST API with the workflow's `GITHUB_TOKEN` (`issues: write`). The scheduled report runs from a workflow `schedule` at 07:00 UTC daily. | 2.16; GitLab issues; the GitLab pipeline schedule | The job token is short-lived and scoped to the repository, so there is no automation token to store or rotate. With no instances to stop, there is no working-hours constraint. |
| 2.24 | **PR previews** build affected customers to `c/internal/previews/pr-{number}/{slug}/` and expose the URL through the GitHub deployment environment `preview`. A workflow on `pull_request` `closed` deletes the prefix; the 14-day lifecycle rule remains as a backstop. | MR previews and the `stop` job (rev 2, 6.10) | The same design on GitHub primitives. |
| 2.25 | **Phase 2 readiness with mock data**: a controlled feature vocabulary, the monitored-source list, mock change events and `dk match`, which raises `change` issues (6.11). The real feed and page-diff worker remains Phase 2. | Ecosystem monitoring wholly out of scope (rev 2, section 1) | Makes the handover's Phase 2 flow (change detected → affected modules and customers → issue for the owner) demonstrable, and fixes the event contract the worker must meet. |
| 2.26 | **Demo fallbacks are permitted and recorded as technical debt** (section 12): SES sandbox with verified recipients, the `demo_show_code` flag, and the CloudFront default hostname if the domain is not live. | (none) | The demo is on 28 September 2026. Each fallback has a named exit in section 12. |
| 2.27 | **Region is `eu-west-1`**, single region. ACM certificates and the WAF web ACL for CloudFront are necessarily in `us-east-1`. | Region open (rev 2, section 11) | The owner already has infrastructure in eu-west-1 and wants a single region for billing. |

Unchanged from the companion documents: URL-first delivery; S3 and CloudFront with no serving compute; MkDocs Material and WeasyPrint; manifests reference module IDs only; branding by CSS variables only; reserved `en-GB` segment; the forge's issue tracker as the ticket system (now GitHub Issues, 2.23); seven-day raw log lifecycle; logging enabled before the first customer; the two-state ticket closure rule.

---

## 3. Target architecture

```
 FDEs ──▶ GitHub (public repo, Free) ──▶ Actions, ubuntu-24.04 hosted runners
                                            │ OIDC: role deploy  (environment production, main only)
                                            │       role preview (pull_request; c/internal/previews/* only)
                         ┌──────────────────▼──── AWS account (eu-west-1) ─────────────────────┐
                         │   S3 content bucket  /c/{slug}/...  /c/internal/{previews,dashboard} │
                         │        │ OAC                                                         │
                         │        ▼                                                             │
 Learners and FDEs ─────▶│ CloudFront "delivery"                                                │
                         │   /c/*        key group + CF Function (KVS revocation)               │
                         │   /auth/*     static login assets                                    │
                         │   /auth/api/* Lambda URLs (OAC)                                      │
                         │   WAF (us-east-1, rate rule only), logging v2 ──▶ logs (7 days) ──▶ Athena
                         │                                                                      │
                         │   Lambda auth-request / auth-verify ── DynamoDB ── SES               │
                         │   SSM Parameter Store: HMAC pepper, signing key                      │
                         └──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Repository

One public repository on the owner's personal GitHub account (2.18, 2.19). The name is `var.github_repo`, default `fde-delivery`.

```
fde-delivery/
  content/
    modules/en-GB/{module-id}/
      meta.yml
      index.md
      images/
    bundles/{bundle-id}.yml
    customers/{slug}.yml
    customers/assets/{slug}/    # logos and other branding assets
    changelog/{module-id}.md    # customer-readable changelog entries (6.6)
    ecosystem/
      features.yml              # controlled vocabulary for claude_features (6.11)
      sources.yml               # intended monitored sources (6.11)
      events/{event-id}.yml     # mock change events (6.11)
  builder/
    requirements.lock           # pinned MkDocs Material, WeasyPrint, pydantic, PyYAML, etc.
    dk/                         # Python package: gates, resolve, plan, build, stamp, deploy,
                                #   dashboard, audit, match
    theme/                      # MkDocs overrides, print CSS, PDF stamp template
    tests/                      # unit tests; acceptance/ holds the section 9 suite
  auth/
    lambda/auth_request/        # handler.py
    lambda/auth_verify/         # handler.py (includes cookie signing)
    lambda/common/              # hmac, dynamo, response helpers
    web/                        # login.html, gate.html, revoked.html, not-found.html,
                                #   auth.css, auth.js (vanilla)
    tests/                      # pytest, moto
    build.sh                    # vendors dependencies for arm64 (8.1, Packaging)
  infra/terraform/
    bootstrap/                  # state bucket only; applied once from a workstation
    delivery/                   # S3, CloudFront, WAF, key group, KVS, logging, Lambda, DynamoDB,
                                #   SES, Route 53 records, OIDC provider and CI roles (7.3)
    github/                     # integrations/github provider: repository, branch protection,
                                #   environments, labels, Actions variables, collaborator (7.2)
    modules/                    # shared Terraform modules
    apply.sh
  .github/
    workflows/                  # pr.yml, pr-closed.yml, deploy.yml, report.yml, match.yml (6)
    CODEOWNERS
  docs/
```

`.github/CODEOWNERS` assigns `*` to the owner and then lists `/content/` with no owner, so code owner review applies to everything outside `content/`, including the workflows and `CODEOWNERS` itself. Content changes need one approval from anyone with write access other than the author.

`dk` is installed from `builder/` in each job, so content and builder always build at the same commit. Content never supplies `mkdocs.yml`: `dk` generates it.

---

## 5. Content model

The schema below is the **PoC proposal**. The metadata schema and bundle taxonomy remain open decisions for production (handover s12). Implement them as pydantic models in `dk` so the schema is enforced by gate G1.

### 5.1 `meta.yml`

```yaml
id: governance-intro            # required; kebab-case; unique; equals directory name
title: Introduction to Claude governance
owner: jane-doe                 # GitHub username; assignee for change and overdue issues
tags: [governance, policy]
claude_features: [projects, admin-console]   # must be ids in content/ecosystem/features.yml
review_cadence_days: 90         # 30 | 90 | 180 per ops s8 defaults
last_reviewed: 2026-09-20       # ISO date
summary: One-sentence description shown on the dashboard.
```

### 5.2 Bundle

```yaml
id: governance-starter
title: Governance starter
modules: [governance-intro, data-handling-basics, admin-controls]
```

### 5.3 Customer manifest

```yaml
slug: acme                      # [a-z0-9-]{3,32}; becomes /c/{slug}/
name: Acme Holdings (fictional)
status: active                  # active | revoked
access_end: 2027-03-31          # informational in PoC; revocation is by status
bundles: [governance-starter]
add: [claude-code-intro]
exclude: [admin-controls]
allowlist:
  - acme.example
  - contractors.acme.example
branding:                       # CSS variables only
  --brand-primary: "#1f5fa8"
  --brand-accent: "#f2a900"
  logo: images/acme-logo.svg    # must be under customers/assets/acme/
expected_learners: 250
```

### 5.4 Resolution and reverse lookup

- Resolved module set = union of bundle modules, plus `add`, minus `exclude`, ordered by bundle order and then by `add` order.
- `dk resolve --reverse` produces `module_id -> [slugs]` for all active customers. This drives selective rebuild (6.3), the dashboard (6.9), `dk match` (6.11) and, later, Phase 2 notifications.

---

## 6. Build workflows (GitHub Actions)

| Workflow | Trigger | Jobs | AWS role |
|---|---|---|---|
| `pr.yml` | `pull_request` to `main` (opened, synchronize, reopened, labeled, unlabeled) | `validate` (6.1, plus builder and auth unit tests), `plan` (6.3, against the PR base), `preview` (6.10) | `preview` |
| `pr-closed.yml` | `pull_request` closed | delete the preview prefix (6.10) | `preview` |
| `deploy.yml` | `push` to `main` | `validate` → `plan` → `build` (matrix) → `deploy` → `publish` → `notify` → `report` | `deploy` |
| `report.yml` | `schedule` `0 7 * * *` (07:00 UTC) and `workflow_dispatch` | dashboard, overdue issues, closure audit (6.9) | `deploy` |
| `match.yml` | `push` to `main` touching `content/ecosystem/events/**`, and `workflow_dispatch` | `dk match` (6.11) | none |

- Every workflow sets `permissions: {}` at the top; each job grants only what it needs (`contents: read`, `id-token: write`, `issues: write`, `deployments: write`).
- Jobs that assume `deploy` declare `environment: production`. `deploy.yml` uses `concurrency: production` so `main` deploys never overlap.
- Third-party actions are pinned to commit SHAs.

`internal` is a reserved slug. It is not a customer manifest, and G2 rejects any manifest that uses it. Its allowlist comes from `var.internal_email_domains` and is published by Terraform.

### 6.1 Build gates (job `validate`, all blocking)

| Gate | Check | Fails on |
|---|---|---|
| G1 | Metadata | `meta.yml` missing, schema invalid, `id` not equal to directory name, `last_reviewed` in the future, a `claude_features` entry not listed in `content/ecosystem/features.yml`; an event file under `content/ecosystem/events/` that fails its schema (6.11) |
| G2 | Manifest integrity | Unknown bundle or module ID, empty resolved set, duplicate slug, invalid slug, allowlist entry not a bare domain, branding key not in the permitted CSS variable list |
| G3 | Internal links and anchors | `mkdocs build --strict` failure, or an unresolved relative link or image |
| G4 | External links | Dead link after retries. **Warning only**, reported in the job log. External rot must not block delivery. |
| G5 | Images | Source image over `image_max_source_kb` (default 2048), unsupported format, or missing alt text |
| G6 | PDF render | WeasyPrint error, or the stamp block absent from the rendered output |

G3 to G6 run inside the build of each affected customer (the `preview` job on a PR, the `build` job on `main`). After G5 passes, images are converted to WebP at responsive widths (default 480, 960, 1600) with content-hashed filenames.

### 6.2 Approval-gated auto-merge (decision 2.22)

Configured by the `github` stack (7.2). Branch protection on `main` requires one approving review, dismisses stale approvals on push, requires code owner review, and requires the checks `validate`, `plan` and `preview`. The repository allows auto-merge (squash only).

- GitHub refuses an author's approval of their own PR, so the approval always comes from someone else. The reviewer persona is a second GitHub account with write access (7.5).
- The author enables auto-merge on their PR (the button, or `gh pr merge --auto --squash`). The PR merges once it is approved and the required checks pass; the merge to `main` runs `deploy.yml`.
- A push after approval dismisses the approval. The PR then waits for a fresh approval.
- Auto-merge is always enabled by a person, never by `GITHUB_TOKEN`: a merge performed as `GITHUB_TOKEN` does not trigger the `push` workflow. **VERIFY** that a merge completed by auto-merge on a person's behalf does trigger it.
- The owner is a repository admin and can bypass protection (`enforce_admins = false`) during the build; section 12 records this.

### 6.3 Selective rebuild (job `plan`)

On `main`, `dk plan` compares `HEAD` with the last successfully deployed SHA, stored in S3 at `state/last-deployed-sha`. On a PR it compares the head with the PR's base. It emits `affected.json` and exposes it as a job output.

- A changed module or its changelog marks every customer whose resolved set contains it.
- A changed manifest, or a change under `content/customers/assets/{slug}/`, marks that customer.
- A changed bundle marks every customer that references it.
- A change under `builder/` marks all active customers. This covers the theme, print CSS and builder code. A missing state object (first run, or after AT-17) also marks all active customers.
- Changes elsewhere (`auth/`, `infra/`, `docs/`, `.github/`, `content/ecosystem/`) mark no customers.
- A customer whose `status` moves to `revoked` is routed to the `publish` job (KVS and allowlist removal) and gets no build.

### 6.4 Module caching (job `build`)

Each module renders once to an intermediate form keyed by `sha256(module dir + builder tree hash)`, where the builder tree hash is `git rev-parse HEAD:builder`. The cache lives in S3 under `build-cache/`. Customer sites and PDFs assemble from the cache. Affected customers build in parallel through `strategy.matrix`, generated from the `plan` job's output with `fromJSON`. Only `main` writes to the cache (7.3).

### 6.5 Site and PDF (job `build`)

- The MkDocs Material site is built per customer with `site_url` set to `https://{delivery_domain}/c/{slug}/`. Branding variables are injected into `extra.css`.
- The PDF is built by WeasyPrint from the same rendered HTML, using the print stylesheet.
- **Stamp** (`@page` footer on every page, plus a title-page block):
  - generation timestamp (UTC, ISO 8601)
  - content version, as `git describe --always` of the repository (one SHA covers content and builder)
  - customer name
  - live URL
  - the notice: "Point-in-time snapshot. The live URL is authoritative and may have changed since this date."
- The site footer carries the same content version string. Acceptance test AT-03 compares the two.
- The PDF is written to `/c/{slug}/{slug}-enablement.pdf`, a fixed name so the site link is stable, and served under the same cookie control as the site.

### 6.6 Changelog

Each PR that changes a module must add or update `content/changelog/{module-id}.md` with a dated, customer-readable entry. G2 enforces this for changed modules, unless the PR carries the label `no-changelog`, which is permitted only for typo-level fixes. The changelog is rendered on the module page.

### 6.7 Deploy and publish (jobs `deploy`, `publish`; `deploy.yml` only)

- `aws s3 sync --delete` per affected customer to `/c/{slug}/`. The PDF is uploaded in the same job as the site.
- CloudFront invalidation of `/c/{slug}/*` per affected customer. Record the invalidation IDs and wait for completion.
- Publish allowlists: for each changed manifest, replace that customer's items in the `allowlist` table in a single transactional batch.
- Publish revocations: write `revoked:{slug}` to the KVS for customers with `status: revoked`, and delete the entry when a customer is reinstated.
- Write `state/last-deployed-sha` **only after** every affected customer has deployed and invalidated successfully.

### 6.8 Notify (stub)

This job writes `notify.json`, listing changed modules and affected customers, as a workflow artefact. Phase 2 replaces it with delivery-register lookups and FDE notifications.

### 6.9 Report (job `report` in `deploy.yml`, and `report.yml` daily)

All issue access uses the GitHub REST API with `GITHUB_TOKEN`.

- **Dashboard:** a static page built from the manifests, the reverse lookup, `meta.yml` data and GitHub Issues. For each module it shows owner, cadence, last reviewed, days overdue, customers holding it, and open issues. Output goes to `/c/internal/dashboard/`.
- **Overdue issues:** for each module past its cadence, open an issue titled `Review overdue: {module-id}` with the labels `review-overdue` and `module::{id}`, assigned to the module owner. This is idempotent: skip the module if an open issue with that label pair already exists.
- **Closure audit:** for issues closed in the last 7 days that carry `change` or `review-overdue`, reopen with an explanatory comment unless one of these holds:
  - the issue has `outcome-updated` and a linked merged PR (a closing reference, or a cross-reference in the issue timeline from a merged PR);
  - the issue has `outcome-no-change` and a comment beginning `No change:` with at least one further sentence.
- **VERIFY:** GitHub may delay scheduled runs under load, and disables schedules in public repositories after 60 days without activity. Neither matters for the PoC; `workflow_dispatch` is the manual trigger.

### 6.10 Pull request previews (decision 2.24)

- The `preview` job builds the affected customers to `c/internal/previews/pr-{number}/{slug}/`, with `site_url` set to match, and invalidates that prefix.
- The job declares `environment: { name: preview, url: https://{delivery_domain}/c/internal/previews/pr-{number}/ }`, so the link appears on the PR with no API call. Reviewers sign in with their Version 1 address.
- `pr-closed.yml` deletes the prefix when the PR closes, merged or not. An S3 lifecycle rule expires `c/internal/previews/` after 14 days as a backstop.
- Preview builds include the PDF.
- PRs from forks get no OIDC token (7.3); the `preview` job is skipped and only `validate` and `plan` run.

### 6.11 Phase 2 readiness: ecosystem data and `dk match` (decision 2.25)

**`content/ecosystem/features.yml`** is the controlled vocabulary for `claude_features`. G1 rejects any feature not listed.

```yaml
- id: projects
  name: Projects
- id: admin-console
  name: Admin console
```

**`content/ecosystem/sources.yml`** lists the sources the Phase 2 worker will monitor. Nothing reads them in the PoC except G1's schema check.

```yaml
- id: anthropic-news
  type: feed                    # feed | page_diff
  url: https://www.anthropic.com/news   # RSS feed URL; VERIFY the current feed address
  owner: jane-doe
- id: claude-blog
  type: page_diff
  url: https://claude.com/blog  # VERIFY
  owner: jane-doe
- id: docs-changelog
  type: page_diff               # or feed, if the changelog publishes one
  url: https://docs.anthropic.com/en/release-notes  # VERIFY
  owner: jane-doe
```

**`content/ecosystem/events/{id}.yml`** are mock change events, in the shape the future worker will emit:

```yaml
id: 2026-09-25-anthropic-news-projects-sharing
source: anthropic-news          # id from sources.yml
detected_at: 2026-09-25T09:14:00Z
title: Projects gain organisation-wide sharing (mock)
url: https://example.invalid/mock/projects-sharing
summary: One or two sentences describing the change.
excerpt: The relevant passage from the source, quoted verbatim.
features: [projects]            # ids from features.yml
```

**`dk match`** (run by `match.yml`):
1. For each event, find modules whose `claude_features` intersect the event's `features`, and the active customers holding those modules through the reverse lookup (5.4).
2. If at least one module matches, open one issue labelled `change`, titled `Change: {title}`, with the source link, the excerpt, the candidate modules, and the affected customers. Assign the owners of the candidate modules; an owner who cannot be assigned is named in the body instead.
3. Idempotent on event ID: the body carries the marker `dk-event: {id}`, and `dk match` skips any event whose marker appears on an existing `change` issue, open or closed.
4. Events that match no module are reported in the job summary and raise no issue.

The issue then follows the normal closure rules (6.9). The real worker in Phase 2 writes events of the same shape; `dk match` does not change.

---

## 7. Infrastructure

### 7.1 Terraform conventions

- Terraform 1.10 or later. The S3 backend uses `use_lockfile = true`, so no DynamoDB lock table is needed.
- Pin the AWS, `integrations/github` and archive providers to the current major versions. **VERIFY** the resource names below against the pinned versions.
- The default AWS provider is in `eu-west-1` (2.27). `provider "aws" { alias = "use1" region = "us-east-1" }` is used for the CloudFront ACM certificate and the WAF web ACL. **VERIFY** which region the CloudFront logging v2 delivery source must be created in (expected `us-east-1`) and whether an S3 destination in `eu-west-1` is accepted.
- Stacks are applied from the workstation in the order `bootstrap` → `delivery` → `github`, each with its own `terraform apply`. Cross-stack values pass through `terraform_remote_state`, read-only.
  - `delivery` takes `var.github_owner` and `var.github_repo` for the OIDC trust policies, so it does not depend on the repository existing.
  - `github` reads `delivery` outputs and publishes them as Actions variables (7.2).
- The `github` provider authenticates with the owner's token from `GITHUB_TOKEN` in the workstation environment (7.5). That token is never stored in Terraform state, SSM or GitHub.
- A wrapper script, `infra/terraform/apply.sh <stack>`, runs `init` and `apply` with the right backend key. For `delivery` it runs `auth/build.sh` first.

### 7.2 `github` stack

| Resource | Specification |
|---|---|
| Repository | `github_repository`: public, issues on, wiki and projects off, squash merge only, `allow_auto_merge = true`, `delete_branch_on_merge = true`. Terraform creates it; the owner then pushes the working tree |
| Branch protection | `github_branch_protection` on `main`: one approving review, `dismiss_stale_reviews = true`, `require_code_owner_reviews = true`; required status checks `validate`, `plan`, `preview`; auto-merge allowed; force pushes and deletion blocked; `enforce_admins = false` (6.2, section 12). **VERIFY** the check context names that GitHub reports for the workflow jobs |
| Environments | `production`: deployment branch policy with the custom branch `main` only, no required reviewers. `preview`: no restrictions |
| Actions variables | Non-secret values from `delivery` state: the two role ARNs, bucket name, distribution ID, KVS ARN, delivery domain, region. No Actions secrets |
| Workflow permissions | Default `GITHUB_TOKEN` permissions read-only. **VERIFY** the resource name (`github_workflow_repository_permissions` or equivalent) |
| Labels | `change`, `review-overdue`, `outcome-updated`, `outcome-no-change`, `no-changelog`. `module::{id}` labels are created by `dk` on first use |
| Collaborator | The reviewer account, `var.reviewer_github_username`, with `push` permission. The invitation is accepted by hand (7.5) |

### 7.3 CI identity (OIDC)

Created in `delivery`.

| Resource | Specification |
|---|---|
| OIDC provider | `aws_iam_openid_connect_provider` for `https://token.actions.githubusercontent.com`, client ID `sts.amazonaws.com`. **VERIFY** whether the pinned provider still requires `thumbprint_list` |
| `deploy` role | Trust: `sts:AssumeRoleWithWebIdentity`, `aud` equal to `sts.amazonaws.com`, `sub` equal (`StringEquals`, not `StringLike`) to `repo:{owner}/{repo}:environment:production`. Permissions: read, write and delete on `c/*`, `state/*` and `build-cache/*`, and `s3:ListBucket`; `cloudfront:CreateInvalidation` and `GetInvalidation` on the distribution; write on the `allowlist` table; read and write on the KVS. Maximum session 1 hour |
| `preview` role | Trust: as above, with `sub` equal to `repo:{owner}/{repo}:pull_request`. Permissions: write and delete on `c/internal/previews/*`; `s3:ListBucket` conditioned on the prefix `c/internal/previews/`; read only on `build-cache/*`, so a PR cannot seed the cache `main` uses; `cloudfront:CreateInvalidation` on the distribution (paths cannot be scoped in IAM; the worst case is a cache flush) |

- The `production` environment admits only `main` (7.2). A PR that edits a workflow to name `production` is refused before a token is issued, and a PR job's `sub` never matches the `deploy` trust.
- GitHub does not issue OIDC tokens to `pull_request` runs from forks, so forks cannot preview.
- Runners are GitHub-hosted `ubuntu-24.04` (x86_64). Jobs install the WeasyPrint system libraries (Pango and related) with `apt` and install `./builder` from `requirements.lock`, with the pip cache from `actions/setup-python`.

### 7.4 `delivery`

**S3 content bucket.**
- Private, with Block Public Access on and object ownership enforced. The bucket policy allows the distribution's OAC principal `s3:GetObject` on `c/*` and `auth/*` only, and `s3:ListBucket` on the bucket (2.17). `ListBucket` does not expose a listing through CloudFront, because every viewer path maps to a non-empty key and the bucket root is covered by `default_root_object`. What it changes is that S3 returns 404 rather than 403 for a missing key. Objects under `state/` and `build-cache/` remain unreadable through CloudFront.
- Prefixes: `c/` (including `c/internal/`), `auth/` (static login assets), `state/`, `build-cache/`.
- Lifecycle: `build-cache/` expires after 30 days; `c/internal/previews/` after 14 days.

**Logs bucket.** Lifecycle rule expiring objects after 7 days. The bucket has no other readers except Athena and the Glue table.

**Route 53.** In the hosted zone created by the domain registration (`var.hosted_zone_id`): the `learn.` alias to the distribution, DNS validation for the ACM certificate, and the SES DKIM, MAIL FROM, SPF and DMARC records. If the domain is not live, see section 12.

**CloudFront `delivery` distribution** (`learn.{domain}`; fallback: the default `*.cloudfront.net` hostname, section 12):

| Behaviour | Origin | Settings |
|---|---|---|
| `/c/*` | S3 (OAC) | Trusted key group; viewer-request CloudFront Function `gate`; cache policy CachingOptimized; compression on |
| `/auth/api/*` | Lambda function URLs (OAC, `AWS_IAM` auth) | Methods `GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE`; CachingDisabled; origin request policy forwarding no cookies, the headers `x-amz-content-sha256` and `content-type`, and no query strings except `c` |
| `/auth/*` | S3 (OAC) | Static login and gate pages; short TTL |
| default | S3 (OAC) | Minimal landing page (`default_root_object = "index.html"`, served from `auth/landing/`); no content |

- **Custom error responses:**
  - 403 → `/auth/gate.html`, response code 403, error caching minimum TTL 0. The gate page reads `location.pathname`, which is still the originally requested path, and redirects to `/auth/login.html?c={slug}&return={path}`. After 2.17, a 403 on `/c/*` can only mean "not signed in or not authorised". Auth API handlers must never return 403, because the error response applies to the whole distribution. They use 400, 401 and 429 instead.
  - 404 → `/auth/not-found.html`, response code 404, error caching minimum TTL 10. The page offers a link back to `/c/{slug}/`, derived from the path.
- **CloudFront Function `gate`** (viewer request on `/c/*`, runtime `cloudfront-js-2.0`), associated with the KVS:
  1. Parse the slug from the URI.
  2. If KVS key `revoked:{slug}` exists, return a 302 to `/auth/revoked.html` with `cache-control: no-store`. The page says that access for this organisation has ended and to contact their Version 1 FDE. This avoids a login page that would never send a code.
  3. If any of the three signed cookies is absent, return a 302 to the login URL with `c` and `return` set.
  4. Normalise directory URLs (2.17). A URI ending in `/` has `index.html` appended. A URI whose last segment has no `.` gets a 302 to the same path with a trailing `/`, so `/c/acme` becomes `/c/acme/`.
  5. Otherwise pass the request through. Signature and policy validation is done by the trusted key group, not the function. The cookie policy's `/c/{slug}/*` wildcard covers the rewritten URI.
  - **VERIFY** the order in which CloudFront evaluates signed cookies relative to the viewer-request function. The design behaves correctly under either order: the function supplies the redirect if it runs first, and the gate page supplies it if it runs second. Record which order applies.
- **WAF (us-east-1):** one web ACL with a single rate-based rule scoped to `/auth/api/`, default 100 requests per 5 minutes per IP (`var.auth_rate_limit`). No managed rule groups; each rule adds a monthly charge, and the serving path is static. Setting `var.enable_waf = false` removes the ACL entirely, saving about £5 a month. Per-email rate limiting in the Lambda and the account's Lambda concurrency limit then remain the only abuse controls. The default stays `true` while the auth endpoints are public.
- **Logging:** standard logging v2 to the logs bucket through the `aws_cloudwatch_log_delivery_source`, `_destination` and `aws_cloudwatch_log_delivery` resources (region: see 7.1).
  - **Field allowlist**, set explicitly: `date`, `time`, `x-edge-location`, `sc-bytes`, `cs-method`, `cs-uri-stem`, `sc-status`, `cs-protocol`, `time-taken`, `x-edge-result-type`, `sc-content-type`.
  - **Must not include:** `c-ip`, `cs(Cookie)`, `cs-uri-query`, `cs(User-Agent)`, `cs(Referer)`, `c-port`, `x-forwarded-for`.
  - Put a comment block in the Terraform explaining why these fields are excluded, as ops section 8 requires.
  - **VERIFY** the field-selection argument names in the pinned provider.

**Signing keys.**
- `aws_cloudfront_public_key` is created from `var.cloudfront_public_key_pem`, and `aws_cloudfront_key_group` from that key.
- The private key is generated offline and placed in Parameter Store manually as a `SecureString` (7.5). Terraform references only the parameter name. Do **not** use `tls_private_key`.

**KeyValueStore.** `aws_cloudfront_key_value_store`, associated with the `gate` function. Entries are written by `deploy.yml`, not by Terraform, so Terraform must not manage entries.

**DynamoDB** (on-demand):

| Table | Key | Attributes |
|---|---|---|
| `allowlist` | PK `slug`, SK `domain` | none |
| `codes` | PK `slug#email_hmac` | `code_hmac`, `expires_at`, `attempts`, `ttl` (TTL enabled) |
| `ratelimit` | PK `email_hmac`, SK `window_start` | `count`, `ttl` |
| `signins` | PK `slug`, SK `date` | `count` (atomic increment, no identity) |

**SES** (`eu-west-1`).
- An SESv2 email identity for `var.ses_subdomain` with Easy DKIM, plus SPF and DMARC records (`p=quarantine` for the PoC), and a custom MAIL FROM domain. Fallback if the domain is not live: a single verified sender address (section 12).
- While in the sandbox: an email identity for each address in `var.ses_sandbox_recipients`. Each recipient confirms by the link SES sends (7.5).
- A configuration set with bounce and complaint events to an SNS topic, with an email subscription to `var.ops_email`.

**Parameter Store** (`SecureString`, standard tier, default `aws/ssm` key). `…/auth/hmac-pepper` (32 random bytes, generated by Terraform with `random_password`; in state, section 12) and `…/auth/cloudfront-private-key` (manual).

**CI identity.** The OIDC provider and the `deploy` and `preview` roles (7.3).

**Athena.** A Glue database and a table over the logs prefix with partition projection on date. Add one saved query that aggregates requests and bytes per `/c/{slug}/` per day.

### 7.5 Permitted manual steps

1. SES production access request. **Submit on day one**; it is support-reviewed. Write it as an honest description of the PoC: transactional one-time codes to a small, known set of recipients.
2. Domain registration through Route 53 by the owner, which creates the hosted zone.
3. Generate the CloudFront signing key pair offline and store the private key PEM in Parameter Store as a `SecureString`.
4. Create and apply the `bootstrap` state bucket from a workstation.
5. SES sandbox recipient verification: each address in `var.ses_sandbox_recipients` (presenter, reviewer, test inboxes) clicks the verification link.
6. Create the owner's GitHub token for the Terraform `github` provider (repository administration scope) and export it as `GITHUB_TOKEN` on the workstation.
7. Create a second GitHub account for the reviewer persona, with 2FA, and accept the collaborator invitation from the `github` stack. Other FDEs (AT-18) are onboarded the same way.
8. Record the account's Lambda concurrency quota (8.1, Packaging).

### 7.6 Cost posture

Directional monthly figures, on demand, before VAT. **VERIFY** all of them with the AWS pricing calculator in P0 (A1).

| Item | Monthly |
|---|---:|
| WAF (one ACL, one rule) | about £5 |
| Route 53 hosted zone | about £0.40 |
| Domain registration (annual, about $3–15 depending on TLD) | under £1.50 |
| S3, DynamoDB, Lambda, SES, Athena, CloudFront at demo volume | under £3 |
| GitHub Actions (public repository) | free |
| **Total** | **about £8–10** |

There is no EC2, no EBS and no public IPv4 charge. CloudFront data transfer at demo volume sits within AWS's free allowance. The only further lever is `enable_waf = false`, which saves about £5 (7.4).

---

## 8. Phases

Each phase lists its **exit criteria**. Do not proceed until they pass, except where the demo cut (8.2) says otherwise.

### P0. Prerequisites

**Tasks:**
- Register the domain through Route 53 (7.5 step 2). If it will not be live in time for the demo, take the fallback in section 12.
- Install the AWS CLI v2 and Terraform 1.10 or later; configure workstation credentials for the account in `eu-west-1`.
- Create the GitHub token and the reviewer account (7.5 steps 6 and 7).
- Submit the SES production access request (7.5 step 1).
- Set `var.ses_sandbox_recipients`; after `delivery` creates the identities, each recipient verifies (7.5 step 5).
- Generate the signing key and store it (7.5 step 3).
- Apply `bootstrap`.
- Record the Lambda concurrency quota (7.5 step 8).
- Price the stack in the AWS pricing calculator and update 7.6.

**Exit:** the state bucket exists; the SES request is submitted; the domain is registered or the fallback is chosen; all required variables have values.

### P1. Delivery plane

**Tasks:**
- Apply `delivery` minus the Lambdas: S3, the distribution, the certificate and `learn.` record, WAF, key group, KVS, the `gate` function, the error responses, logging, and the OIDC provider and CI roles.
- Apply `github`; push the repository; commit `CODEOWNERS`.
- Upload a static test page to `c/test/`.

**Exit:**
- Unauthenticated requests to `/c/test/` end at the login URL.
- A cookie set minted by hand with a local script grants access. With it, `/c/test` redirects to `/c/test/`, which serves `index.html`, and `/c/test/missing/` returns the 404 page, not the login page.
- Log objects are landing, and a sample shows that none of the excluded fields are present.
- The evaluation order under **VERIFY** in 7.4 is recorded.
- A `workflow_dispatch` job on `main` with `environment: production` assumes `deploy`. A PR job assumes `preview`, can write under `c/internal/previews/`, and is refused on `c/test/`. A PR job naming `environment: production` is refused.

### P2. Authentication

**Tasks:**
- Build `auth_request`, `auth_verify` and the static login pages, to the specification in 8.1.
- Unit test with moto; run the tests in `pr.yml`.

**Exit:** AT-04 to AT-09 and AT-19 pass against the test customer, with `demo_show_code = false`. SES may still be in the sandbox; use verified recipients.

### P3. Content model and mock content

**Tasks:**
- Build the `dk` schema and resolver, plus the reverse lookup.
- Create 6 synthetic modules, 2 bundles and 2 customers:
  - `acme` and `brightwater`, both fictional, with one shared module and one module unique to each;
  - one more manifest, `oldco`, with `status: revoked`.
- Create the ecosystem data (6.11): `features.yml` covering every feature the modules use, `sources.yml` with the three sources, and at least three mock events: one matching the shared module, one matching a module unique to one customer, and one matching nothing.

**Exit:** `dk resolve` and `dk resolve --reverse` produce the expected output; G1 (including the feature vocabulary) and G2 pass on good content and fail on the broken fixtures.

### P4. Build pipeline in GitHub Actions

**Tasks:** `deploy.yml` and the `validate` and `plan` jobs of `pr.yml`; gates G3 to G6, image processing, plan (including `builder/` detection), module cache, matrix builds, site and PDF build with stamp, deploy, invalidation, allowlist and KVS publish, `state/last-deployed-sha`.

**Exit:** AT-01, AT-02, AT-03, AT-10, AT-21 and AT-22 pass.

### P5. Pull request workflow

**Tasks:** the `preview` job and `preview` environment, `pr-closed.yml`, and confirmation that branch protection and auto-merge behave as in 6.2.

**Exit:** AT-11 and AT-12 pass.

### P6. Freshness, governance and `dk match`

**Tasks:** dashboard, overdue issues, closure audit, `report.yml`, Athena saved query, `dk match` and `match.yml`.

**Exit:** AT-13, AT-14, AT-15 and AT-23 pass.

### P7. Acceptance

**Tasks:**
- Run the full suite in section 9 from a clean state.
- Two FDEs who did not build the system each author and merge a module unaided (AT-18).
- Produce the document updates listed in section 10.

**Exit:** all acceptance tests pass. **Partial completion is not completion** (ops s11).

### 8.1 Authentication specification

**`POST /auth/api/request`**, body `{ "c": slug, "email": string }`.

1. Normalise the email address: trim, lower-case the domain part, reject if it fails a basic address syntax check.
2. Compute `email_hmac = HMAC-SHA256(pepper, lower(email))`.
3. Rate limit: at most 3 requests per `email_hmac` per 15 minutes, using the `ratelimit` table with a conditional update. Over the limit returns 429.
4. If the slug exists in the `allowlist` table, the customer is not revoked, and the email domain is allowlisted (exact match, or a listed subdomain match if `allow_subdomains` is later added; the PoC uses exact match only):
   - generate the code with `secrets.randbelow(10**6)`, zero-padded to 6 digits;
   - put `codes[slug#email_hmac]` with `code_hmac = HMAC-SHA256(pepper, slug|email_hmac|code)`, `expires_at = now + 600`, `attempts = 0`, `ttl = expires_at + 3600`;
   - send through SES with the configuration set. The subject and body name the customer and give the code and its 10-minute expiry. There are no links in the email.
5. Always return 202 with the same body and similar latency, whether or not the domain is allowlisted. Add a small random delay to mask SES timing.
6. Never log the email address. Log only the slug, the outcome class and the request ID.
7. **Demo only:** when the environment variable `DEMO_SHOW_CODE` is `true` (from `var.demo_show_code`, default `false`), an allowlisted request also returns the code in the response body. This breaks step 5 and AT-05, and must never be enabled beyond the demo (section 12).

**`POST /auth/api/verify`**, body `{ "c": slug, "email": string, "code": string, "return": string }`.

1. Recompute `email_hmac` and read `codes[slug#email_hmac]`.
2. Reject with 401 if the record is missing, if `now > expires_at` (checked in code, because TTL deletion lags), or if `attempts >= 5`.
3. On a constant-time mismatch, increment `attempts` atomically and return 401.
4. On a match, conditionally delete the record (`attribute_exists` and matching `code_hmac`) so the code is single-use. If the delete loses a race, return 401.
5. Mint the cookies:
   - Build the custom policy `{"Statement":[{"Resource":"https://{delivery_domain}/c/{slug}/*","Condition":{"DateLessThan":{"AWS:EpochTime":now+604800}}}]}`.
   - Sign it with the private key from Parameter Store, cached for the life of the container. Use the algorithm CloudFront currently documents for signed cookies: historically RSA-SHA1 with PKCS#1 v1.5. **VERIFY** whether SHA-256 is now supported and use it if so.
   - Encode with CloudFront-safe base64 (`+` becomes `-`, `=` becomes `_`, `/` becomes `~`).
   - Set `CloudFront-Policy`, `CloudFront-Signature` and `CloudFront-Key-Pair-Id`, each with `Path=/c/{slug}/; Secure; HttpOnly; SameSite=Lax; Max-Age=604800`, and no `Domain` attribute.
6. Atomically increment `signins[slug][today]`.
7. Validate `return`. It must start with `/c/{slug}/`, must not contain `//`, `\` or a scheme, and must be under 512 characters. Otherwise use `/c/{slug}/`.
8. Return 200 with `{ "redirect": return }`. The page performs the navigation.

**Login page (`/auth/login.html`)**, vanilla JavaScript:
- Two steps: email, then code.
- Computes `x-amz-content-sha256` for each POST body with `crypto.subtle.digest('SHA-256', …)`, as OAC requires for Lambda function URLs.
- The copy tells the learner to ask their IT team to allowlist the sending domain if no code arrives.
- No third-party scripts, fonts or analytics.

**Packaging.** The Lambdas use the Python 3.12 or later runtime on arm64. `auth/build.sh` vendors `cryptography` with `pip install --platform manylinux2014_aarch64 --only-binary=:all: --target build/`; `apply.sh delivery` runs it, and Terraform zips the result with `archive_file`. Reserved concurrency is controlled by `var.lambda_reserved_concurrency`, default `null` (not set). New accounts often have an account-wide concurrency quota of 10, and AWS refuses any reservation that leaves fewer than 100 unreserved. Demo load needs one or two concurrent executions, and the account quota itself caps runaway use. In P0, record the account's quota in the Service Quotas console; set the variable only if the quota is 1,000.

### 8.2 Demo cut (28 September 2026)

Work P0 to P5 in order, then the `dk match` part of P6. What must work at the demo:

1. Two branded customers, `acme` and `brightwater`, live with stamped PDFs.
2. Email-code sign-in. The demo manifests allowlist mailbox domains the presenters can receive at, with a different domain per customer; the SES sandbox limits sending to verified recipients.
3. Cross-tenant denial (AT-06).
4. Revocation (AT-09).
5. A PR with a preview, then approval, auto-merge and deploy (AT-11, AT-12).
6. `dk match` raising a `change` issue from a mock event (AT-23).

Everything else continues after the demo, including G4, the dashboard, overdue issues, the closure audit, the Athena query, AT-13 to AT-15, AT-17, AT-18 and section 10. Demo fallbacks are in section 12.

---

## 9. Acceptance tests

Automate every test in `builder/tests/acceptance/` except AT-18. Each test records its evidence (command output, object listings, screenshots) as a workflow artefact.

| ID | Test | Pass criteria |
|---|---|---|
| AT-01 | Selective rebuild, unique module | Change a module held only by `acme`. Only `acme` objects change `LastModified`; `brightwater` objects are untouched; one invalidation is issued. |
| AT-02 | Shared module | Change the shared module. Both customers redeploy; both PDFs regenerate. |
| AT-03 | PDF currency | For every deployed customer, the content version in the PDF stamp equals the site footer and `state/last-deployed-sha`. |
| AT-04 | Happy path | A verified address at an allowlisted domain for `acme` receives a code, signs in, loads `/c/acme/` and downloads the PDF. |
| AT-05 | Non-allowlisted | An address at an unlisted domain gets 202 with an identical body; no SES send occurs (checked in CloudWatch metrics); no code record is created. Run with `demo_show_code = false`. |
| AT-06 | Cross-tenant | `acme` cookies requesting `/c/brightwater/` are denied and end at login. |
| AT-07 | Code controls | The code fails after 10 minutes; the sixth attempt fails even with the correct code; a used code fails on reuse; the fourth request inside 15 minutes returns 429. |
| AT-08 | Open redirect | `return` values of `//evil.example`, `https://evil.example` and `/c/brightwater/` all redirect to `/c/acme/`. |
| AT-09 | Revocation | Setting `acme` to `revoked` and deploying sends a holder of valid cookies to `/auth/revoked.html` within the KVS propagation time, and no content is served. Reinstating restores access without a new sign-in. |
| AT-10 | Gates | Separate PRs introducing a broken internal link, an oversized image, a manifest referencing a missing module, a module without `meta.yml`, and a `claude_features` entry not in `features.yml` each fail the PR workflow at the expected gate. |
| AT-11 | Preview | A PR produces a working preview URL on its `preview` environment. A Version 1 address can sign in and view it; a customer address cannot. Closing the PR removes the prefix. |
| AT-12 | Approval-gated auto-merge | (a) A PR approved by the reviewer persona, with auto-merge enabled by its author, merges once its checks pass, and `deploy.yml` deploys it. (b) An unapproved PR cannot merge. (c) A commit pushed after approval dismisses the approval, and the PR does not merge until approved again. |
| AT-13 | Logging | Logs land within the expected delivery window. A sample contains none of the excluded fields. The Athena saved query returns per-customer aggregates. |
| AT-14 | Freshness | Backdating `last_reviewed` opens exactly one overdue issue across two runs of `report.yml` (trigger the second with `workflow_dispatch` rather than waiting a day); the dashboard shows the module as overdue. |
| AT-15 | Closure audit | An issue closed without an outcome label is reopened with a comment. `outcome-no-change` without a `No change:` comment is reopened. A correctly closed issue is left alone. |
| AT-16 | **Removed in rev 3 (no self-hosted forge).** Restore | A GitLab backup restores to a newly built host, and projects, issues and runners are intact. |
| AT-17 | Rebuild delivery | `terraform destroy` and `apply` of `delivery`, followed by `github` and a full content deploy, restores all customer endpoints with no manual step other than the KVS and allowlist republish, which the workflow does. |
| AT-18 | Authorship | Two FDEs who did not build the system each author and merge a module unaided. |
| AT-19 | No stored email | A scan of every DynamoDB table and the Lambda logs finds no plaintext email address. |
| AT-20 | **Removed in rev 3 (no self-hosted forge).** GitLab hardening | From outside, an anonymous visitor cannot register and sees no projects. A new user is forced into 2FA enrolment at first sign-in. Creating a public or internal project is refused. Git over HTTPS with a password is refused and with a personal access token succeeds. |
| AT-21 | Paths and errors | Signed in to `acme`: `/c/acme` redirects to `/c/acme/`; every MkDocs directory URL serves its page; a missing page returns the 404 page with status 404, not the login page. `https://{delivery_domain}/` serves the landing page, not a bucket listing. `/state/last-deployed-sha` is not readable. |
| AT-22 | Builder change | A change under `builder/theme/` with no content change rebuilds and redeploys every active customer, and updates `state/last-deployed-sha` and the PDF stamp. |
| AT-23 | Change matching | Running `match.yml` over the mock events opens one `change` issue per matching event, with the source link, excerpt, candidate modules, affected customers and the module owner assigned. The non-matching event raises no issue. A second run opens no duplicates. |

---

## 10. Required updates to companion documents

Produce these as PRs in P7. Do not silently rewrite the documents' reasoning. Mark superseded text and add a pointer to this plan.

- **Handover:**
  - s3 and s6: account (personal for the PoC), forge (GitHub Free, public monorepo, 2.18 and 2.19; enterprise forge deferred), no self-hosted compute, access control, PDF cadence.
  - s7: add "API Gateway (for auth)", "OIDC federation" and "pluggable verification" as superseded, with reasons.
  - s11: remove Phase 3 federation and completion tracking; record that the Phase 2 matching step and event contract exist (6.11).
  - s12: record that the security review, schema and enterprise forge remain open.
- **Operations:**
  - s1: A2 and A3 no longer apply (no forge host, 2.21); A7 elevated to critical, since email codes are now the only access path; add the new assumptions A13, A14 and A16.
  - s2: remove the learner email retention items; add the SES production access request as blocking.
  - s3: add "status and access_end set in manifest".
  - s7: revocation through the manifest `status`.
  - s8: native approval-gated auto-merge (2.22) and the closure audit as enforcement; issues in GitHub Issues.
  - s9: M14 reduced to SES log review; M1 (forge patching) and backup items removed.
- **Tech consideration:** stack table (GitHub Free with GitHub Actions replacing GitLab; Lambda function URLs replacing API Gateway), the access control section, the cost model (replace with 7.6), Phase 3.

### New assumptions

| # | Assumption | Validate by | Impact if wrong |
|---|---|---|---|
| A13 | The CloudFront signed-cookie and viewer-request function order is compatible with the gate design | P1 | Redirect UX degrades to the gate page only; no security impact |
| A14 | Every customer security team accepts email codes as the sole access path | Pre-engagement | That customer receives PDFs only |
| A15 | **Obsolete in rev 3 (no self-hosted forge).** GitLab EE runs acceptably for a handful of demo users on 2 vCPU and 8 GiB with memory-constrained settings | P1 exit check | Resize to `t3a.xlarge` (4 vCPU, 16 GiB), roughly doubling the host line in 7.6 |
| A16 | Version 1 mail systems deliver one-time codes from the personal sending domain to Version 1 inboxes without quarantine | P2, using a Version 1 address | FDE previews and the dashboard fall back to access with a non-Version 1 test address temporarily added to `internal_email_domains`; record this as a known limitation for the demo |
| A17 | **Obsolete in rev 3 (no self-hosted forge).** GitLab allows a project webhook to call its own external URL, directly or through the outbound allowlist | P2 exit | Replace the webhook with a scheduled `auto-merge` pipeline every 10 minutes in working hours that scans open approved MRs; merges are slower but the logic is unchanged |

---

## 11. Inputs from the project lead

### Resolved (27 September 2026)

| Input | Value |
|---|---|
| `region` | `eu-west-1` (2.27); ACM and WAF for CloudFront in `us-east-1` |
| `internal_email_domains` | `["version1.com"]` |
| `ops_email` | set in `terraform.tfvars` (kept out of git; the presenter's personal address) |
| Working hours | Not needed: there is no compute to schedule |
| Forge | GitHub Free, public repository (2.18) |

### Still open

1. Domain: to be registered by the owner through Route 53 (pending); sending subdomain name.
2. GitHub account names: `github_owner`, `reviewer_github_username` (pending).
3. `ses_sandbox_recipients` for the demo, and the presenters' mailbox domains for the demo allowlists (8.2).
4. Image limits, if different from the defaults in 6.1.
5. Sign-off on the PoC metadata schema (5.1) as the starting point for the production schema.

---

## 12. Technical debt register (PoC)

| Item | PoC position | Later action |
|---|---|---|
| SES sandbox | The demo runs in the sandbox; presenter and reviewer addresses are verified recipients. The production access request is still submitted | On approval, remove `ses_sandbox_recipients` and the recipient identities; confirm delivery to an unverified address |
| `demo_show_code` | Optional flag on `auth_request`, default `false`, returning the code in the response. It defeats the constant-response property (8.1 step 5) | Enable only if SES delivery fails during the demo, and set it back to `false` straight after. Must never be enabled beyond the demo. Remove the flag once SES is out of the sandbox |
| Domain not live | If the domain is not live in time: the CloudFront default `*.cloudfront.net` hostname (used for `site_url` and the cookie policy resource) and a verified single-address SES sender | When the domain is live, add the certificate and `learn.` alias, switch `delivery_domain`, move SES to the domain identity, and redeploy all customers (cookies issued for the old hostname lapse) |
| Monorepo | One repository for platform and content (2.19) | Split into platform and content repositories, with the content workflow defined outside the content repository (as rev 2's 2.14 did) |
| Public repositories | Required for branch protection, required reviews and auto-merge on GitHub Free (2.18). Content is synthetic only | Move to private repositories on a paid plan or the enterprise forge before any real material is added |
| Forge choice | GitHub for the PoC | Decide between GitHub and Version 1's enterprise GitLab; the migration rewrites workflows and the issue client only (section 0 rule 1) |
| Admin bypass | `enforce_admins = false`, so the owner can merge without review during the build | Set `enforce_admins = true` after the demo, once a second code owner exists |
| Lambda reserved concurrency | Unset (8.1, Packaging); the account quota caps runaway use | Set `lambda_reserved_concurrency` once the account quota is 1,000 |
| Code request rate limit raised | `code_requests_per_window = 10` for rehearsals and the demo; 8.1 specifies 3 per address per 15 minutes | Set `code_requests_per_window` back to 3 (the variable's default) after the demo, and re-run AT-07 |
| HMAC pepper in Terraform state | Generated by `random_password`, so it sits in state (7.4) | Generate outside Terraform and reference by parameter name, as with the signing key; rotate on migration |
