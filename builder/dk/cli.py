"""dk command line. Run from the repository root (or pass --content)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import build as b
from . import dashboard, gates, plan
from .repo import ContentError, Repo

LF = chr(10)


def _repo(args) -> Repo:
    try:
        return Repo.load(Path(args.content).resolve())
    except ContentError as e:
        _fail(e.problems)


def _fail(problems: list[str]) -> None:
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    sys.exit(1)


def _domain(args) -> str:
    d = args.domain or os.environ.get("DK_DELIVERY_DOMAIN")
    if not d:
        sys.exit("delivery domain required: --domain or DK_DELIVERY_DOMAIN")
    return d


def cmd_validate(args) -> None:
    repo = _repo(args)  # G1, G2 schema and integrity
    problems = gates.check_images(repo, args.image_max_kb) + gates.check_internal_links(repo)
    if args.changed_files:
        files = Path(args.changed_files).read_text().split()
        labels = [x for x in (args.labels or "").split(",") if x]
        problems += gates.check_changelog(repo, files, labels)
    if problems:
        _fail(problems)
    if args.external:
        for w in gates.check_external_links(repo):
            print(w)
    print(f"OK: {len(repo.modules)} modules, {len(repo.groups)} groups, {len(repo.customers)} customers, "
          f"{len(repo.events)} ecosystem events")


def cmd_resolve(args) -> None:
    repo = _repo(args)
    if args.reverse:
        print(json.dumps(repo.reverse(), indent=2))
    else:
        slugs = [args.slug] if args.slug else list(repo.customers)
        print(json.dumps({s: repo.resolve(s) for s in slugs}, indent=2))


def cmd_plan(args) -> None:
    repo = _repo(args)
    root = Path(args.content).resolve().parent
    base = args.base
    if base is None and args.from_state:
        from .deploy import read_state
        base = read_state()
    files = plan.changed_files(root, base, args.head)
    result = plan.affected(repo, files)
    result["base"], result["head"] = base, args.head
    result["revoked"] = [c.slug for c in repo.customers.values() if not c.active]
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            f.write(f"customers={json.dumps(result['customers'])}\n")
            f.write(f"any={'true' if result['customers'] else 'false'}\n")


def cmd_build(args) -> None:
    repo = _repo(args)
    root = Path(args.content).resolve().parent
    ctx = b.make_context(root, _domain(args), prefix=args.prefix)
    slugs = args.slug or [c.slug for c in repo.active_customers()]
    for slug in slugs:
        if slug not in repo.customers:
            _fail([f"unknown customer '{slug}'"])
        if not repo.customers[slug].active:
            print(f"skip {slug}: revoked")
            continue
        out = Path(args.out) / slug
        try:
            site = b.build_site(repo, slug, ctx, out, pdf=not args.no_pdf)
        except RuntimeError as e:
            _fail([str(e)])
        print(f"built {slug} -> {site} (version {ctx.version})")


def cmd_deploy(args) -> None:
    from . import deploy
    prefix = args.prefix.strip("/")
    out = Path(args.out)
    slugs = args.slug
    paths = []
    for slug in slugs:
        site = out / slug / "site"
        if not site.exists():
            _fail([f"no build for {slug} at {site}"])
        deploy.s3_sync(site, f"{prefix}/{slug}")
        paths.append(f"/{prefix}/{slug}/*")
        print(f"synced {slug}")
    if paths:
        deploy.invalidate(paths, wait=not args.no_wait)


def cmd_publish(args) -> None:
    from . import deploy
    repo = _repo(args)
    deploy.publish_allowlists(repo)
    deploy.publish_revocations(repo)
    if args.record_sha:
        deploy.write_state(args.record_sha)
        print(f"recorded {deploy.STATE_SHA} = {args.record_sha}")


def cmd_unpreview(args) -> None:
    from . import deploy
    prefix = f"c/internal/previews/pr-{args.pr}"
    deploy.s3_remove_prefix(prefix)
    deploy.invalidate([f"/{prefix}/*"], wait=False)


def cmd_dashboard(args) -> None:
    repo = _repo(args)
    root = Path(args.content).resolve().parent
    issues = None
    if not args.offline:
        from .issues import GitHub
        try:
            issues = GitHub().issues(state="open")
        except Exception as e:
            print(f"warning: issues unavailable: {e}")
    ctx = b.make_context(root, "unused")
    target = dashboard.write(repo, Path(args.out), issues, ctx.generated_at, ctx.version)
    print(f"dashboard -> {target}")


def cmd_overdue(args) -> None:
    from .issues import GitHub, open_overdue_issues
    today = dt.date.fromisoformat(args.today) if args.today else None
    open_overdue_issues(_repo(args), GitHub(dry_run=args.dry_run), today)


def cmd_audit(args) -> None:
    from .issues import GitHub, audit_closures
    audit_closures(GitHub(dry_run=args.dry_run), days=args.days)


def cmd_review(args) -> None:
    """Record a review: set last_reviewed, and add a changelog entry when something changed."""
    import re
    import yaml
    repo = _repo(args)
    if args.module not in repo.modules:
        _fail([f"unknown module '{args.module}'"])
    day = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    meta = repo.modules[args.module].path / "meta.yml"
    text = meta.read_text(encoding="utf-8")
    text, n = re.subn(r"^last_reviewed:.*$", f"last_reviewed: {day.isoformat()}", text, count=1, flags=re.M)
    if not n:
        _fail([f"{meta}: no last_reviewed line"])
    meta.write_text(text, encoding="utf-8", newline=LF)
    print(f"{args.module}: last_reviewed = {day}")
    if args.note:
        log = Path(args.content) / "changelog" / f"{args.module}.yml"
        data = yaml.safe_load(log.read_text(encoding="utf-8")) if log.exists() else {"entries": []}
        data["entries"].insert(0, {"date": day, "change": args.note})
        log.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline=LF)
        print(f"{args.module}: changelog += {day}: {args.note}")
    else:
        print("No note given: recorded as reviewed with no change. Close the review issue with outcome-no-change "
              "and a comment beginning 'No change:'.")


def cmd_match(args) -> None:
    from .issues import GitHub, match_events
    gh = None if args.offline else GitHub(dry_run=args.dry_run)
    match_events(_repo(args), gh, args.event or None)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dk", description="Enablement content delivery kit")
    p.add_argument("--content", default="content", help="path to the content directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="gates G1, G2, G3 (pre-build), G5; G4 with --external")
    s.add_argument("--image-max-kb", type=int, default=int(os.environ.get("DK_IMAGE_MAX_KB", 2048)))
    s.add_argument("--changed-files", help="file listing changed paths (enables the changelog rule)")
    s.add_argument("--labels", help="comma-separated PR labels")
    s.add_argument("--external", action="store_true", help="also check external links (warnings only)")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("resolve", help="resolved module sets, or the reverse lookup")
    s.add_argument("slug", nargs="?")
    s.add_argument("--reverse", action="store_true")
    s.set_defaults(fn=cmd_resolve)

    s = sub.add_parser("plan", help="affected customers between two commits")
    s.add_argument("--base", help="base commit (default: from state with --from-state)")
    s.add_argument("--head", default="HEAD")
    s.add_argument("--from-state", action="store_true", help="read base from state/last-deployed-sha in S3")
    s.add_argument("--out", help="write affected.json here")
    s.set_defaults(fn=cmd_plan)

    for name, fn, hlp in [("build", cmd_build, "build sites and PDFs")]:
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--slug", action="append", help="customer slug (repeatable); default all active")
        s.add_argument("--out", default="build")
        s.add_argument("--domain", help="delivery domain (or DK_DELIVERY_DOMAIN)")
        s.add_argument("--prefix", default="c", help="URL prefix: c, or c/internal/previews/pr-N")
        s.add_argument("--no-pdf", action="store_true", help="placeholder PDF (local dev without Pango)")
        s.set_defaults(fn=fn)

    s = sub.add_parser("deploy", help="sync built customers to S3 and invalidate")
    s.add_argument("--slug", action="append", required=True)
    s.add_argument("--out", default="build")
    s.add_argument("--prefix", default="c")
    s.add_argument("--no-wait", action="store_true")
    s.set_defaults(fn=cmd_deploy)

    s = sub.add_parser("publish", help="publish allowlists and revocations; optionally record the deployed sha")
    s.add_argument("--record-sha")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("unpreview", help="delete a PR preview prefix")
    s.add_argument("--pr", required=True, type=int)
    s.set_defaults(fn=cmd_unpreview)

    s = sub.add_parser("dashboard", help="render the freshness dashboard")
    s.add_argument("--out", default="build/dashboard")
    s.add_argument("--offline", action="store_true", help="skip the GitHub Issues API")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("overdue", help="open review-overdue issues")
    s.add_argument("--today", help="override today's date (testing)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_overdue)

    s = sub.add_parser("audit", help="reopen change/review issues closed without a valid outcome")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("review", help="record a module review: bump last_reviewed, optionally add a changelog entry")
    s.add_argument("module")
    s.add_argument("--note", help="customer-readable description of what changed (omit for a no-change review)")
    s.add_argument("--date", help="review date (default today)")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("match", help="match ecosystem events to modules and customers; raise issues")
    s.add_argument("--event", action="append")
    s.add_argument("--offline", action="store_true", help="print matches only")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_match)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
