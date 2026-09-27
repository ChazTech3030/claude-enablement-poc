# Getting started with Claude Code

!!! note "Synthetic content"
    This module is mock material for the platform proof of concept.

Claude Code works in your terminal and editor, reading your repository and making changes you review.

## Install and sign in

Install Claude Code following your organisation's approved method, then run it from the root of a repository you know well.

## The permission model

Claude Code asks before it edits files or runs commands. You can approve once, approve for the session, or add a rule to the project's settings so routine commands stop prompting.

!!! tip
    Start strict. Loosen permissions only for commands you have seen it run correctly several times.

## A first guided change

1. Ask Claude Code to explain the repository's structure.
2. Pick a small, well-understood issue.
3. Ask for a plan before any edits.
4. Review the diff, run the tests, and commit.

## Connectors

Model Context Protocol (MCP) servers let Claude Code reach other systems, such as your issue tracker. Only connect systems your organisation has approved.
