---
name: browser-investigate
description: Drive a real browser against a running doctrine project's dev environment — navigate, click, fill, and screenshot its web UI to investigate behavior or smoke-test it by hand. Uses a containerized Playwright MCP server (stdio); nothing Playwright-related is installed on the dev machine. Use whenever you need to look at, click through, screenshot, or manually exercise a running app's web interface — "open the app", "click through the login flow", "what does the dashboard look like", "smoke-test the UI". For automated/CI browser test suites, this is NOT the tool (that is the project's staging tests).
metadata:
  type: conventional
---

# browser-investigate

Drive a browser against a **running** doctrine project — usually the `dev`
environment — to see what the app actually does: load pages, click through
flows, fill forms, and capture snapshots/screenshots. This is for hands-on
investigation and exploratory smoke-testing by the agent, not for authoring
automated test suites.

Playwright (and the browser) run entirely inside a container reached over an
**stdio MCP server**. The dev machine needs only Docker and Claude Code — there
is no host-side Playwright install to manage or version.

## When this fits

Reach for this when the task is "look at / click / screenshot / manually
exercise a web UI that is currently running." If the request is to write or run
the project's *automated* end-to-end tests, that belongs to the project's
[staging tests](../testing/SKILL.md), not here.

## Prerequisites

1. **The dev stack is up.** `./bin/docex envinfra up dev` has run and the web
   service(s) are healthy. (Bringing dev up already required dev DNS to be
   routed and certs issued — see below, this is why the public URL just works.)
2. **The Playwright MCP server is registered.** It is a stdio MCP server that
   runs the browser in a container. **`setup.sh` pre-registers it** (via
   `setup/claude/mcp.sh`), so on a machine whose doctrine install is current it
   is already there — the tools come live in any session started after that
   setup run, which is the same fresh session `doctrine-update` already tells you
   to start. If the `browser_*` tools are *not* available, the registration
   didn't run or didn't take: re-run `bash ~/.claude/jean_baudrillard/setup.sh`
   (or just its `setup/claude/mcp.sh`) and restart the session.

### MCP server entry

The server's pinned config is the canonical
[`setup/claude/playwright_mcp.json`](../../setup/claude/playwright_mcp.json) in
the jean repo — the **single source of truth** for the pin, consumed by
`setup/claude/mcp.sh`. It registers at **user scope** (`~/.claude.json`
`mcpServers`), equivalent to:

```json
{
  "command": "docker",
  "args": [
    "run", "-i", "--rm", "--init",
    "mcr.microsoft.com/playwright/mcp:<tag>@sha256:<digest>"
  ]
}
```

- **stdio**: Claude Code launches the container per session and speaks MCP over
  its stdin/stdout (`-i`); `--rm` keeps containers from piling up; `--init`
  reaps the browser's child processes cleanly.
- **Containerized**: the image carries Playwright + the browsers, so nothing is
  installed on the host. The default in-container browser is headless, which is
  what you want for an agent.
- **Pinned by digest** per docex's pin-everything discipline, so the
  browser/Playwright versions don't drift between sessions. To bump the version
  later, re-resolve the digest with
  `docker buildx imagetools inspect mcr.microsoft.com/playwright/mcp:<tag> --format '{{.Manifest.Digest}}'`
  and edit the tag and `@sha256:` in `setup/claude/playwright_mcp.json` (the one
  place). `mcp.sh` compares command+args and re-registers on the next setup run,
  so the new pin lands automatically.
- **Network**: the container only needs ordinary internet egress (the default
  docker bridge gives it). No `--network` / `docex-ingress` wiring is needed —
  see the next section for why.

## Find the URL to drive

Dev web services publish **no host ports** — they sit behind the per-project
traefik and are reachable only at their domain. So you drive the browser at the
public dev URL, never `localhost:<port>`.

Build the URL from `project.yml` (the project name) and `infra/infra.yml`
(`apex_domain`, and `domain_default_process`), per the doctrine domain rules:

- Per process type on the `web` network:
  `https://<service>-<process>.dev.<project>.<apex_domain>`
  (the service and process segments are joined by a hyphen and occupy one
  label; the project segment is hyphenated too — `my_project` → `my-project`).
- The `domain_default_process` also answers at the bare-env host:
  `https://dev.<project>.<apex_domain>`.

Because the dev stack only comes up after dev DNS is routed and Let's Encrypt
certs are issued (the `preinfra development` gate), this hostname resolves
publicly and serves a valid cert. The containerized browser therefore reaches
the app **exactly as a real user would** — real DNS, real TLS — which is why no
docker-network tricks are required.

If a page won't load, confirm the stack is healthy (`docker compose ps` on the
dev stack) and that the dev hostname resolves (`./bin/docex preinfra development`
checks this) before assuming a Playwright problem.

## The driving loop

Work in a tight **navigate → snapshot → act → verify** cycle, using the MCP
browser tools:

1. **Navigate** to the target URL (`browser_navigate`).
2. **Snapshot** the page (`browser_snapshot`) to get the accessibility tree —
   prefer this over a screenshot for *deciding what to do next*, because it
   gives you the element refs you act on. Use `browser_take_screenshot` when you
   need to *show* the user what something looks like.
3. **Act** — click, type, select, submit (`browser_click`, `browser_type`, …)
   against the refs from the snapshot.
4. **Verify** — re-snapshot and check the page changed as expected; capture a
   screenshot if the user wants visual evidence. Read `browser_console_messages`
   and check network/responses when something behaves unexpectedly.

Report findings concretely: what you navigated to, what you did, what the page
did in response, and attach screenshots when they carry the point. When
smoke-testing, walk the one or two critical paths (e.g. load the landing page →
log in → reach the main view) rather than trying to be exhaustive — exhaustive
coverage is the automated suite's job, not this.

## Out of scope

- **Automated / CI browser test suites.** Authoring the project's end-to-end
  staging tests is a separate, deferred concern; this skill is for interactive,
  agent-driven investigation only.
- **Non-dev environments.** You *can* point it at any reachable URL, but the
  ergonomic path (and the no-host-ports reasoning above) is the `dev` env on the
  operator's machine.
