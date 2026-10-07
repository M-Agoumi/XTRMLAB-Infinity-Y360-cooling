# Branch and tag rulesets

These are GitHub [repository rulesets](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
kept in the repo so the protection settings are reviewable and easy to
restore. Files in this folder do nothing by themselves; a maintainer
imports them once:

**Settings → Rules → Rulesets → New ruleset → Import a ruleset**, then
pick the JSON file.

| File | Protects | What it enforces |
| --- | --- | --- |
| `main.json` | `main` | No direct pushes, force-pushes or deletion. Changes land through a PR with 1 code-owner approval and resolved review threads. |
| `release-tags.json` | `v*` tags | Release tags can't be created, moved or deleted, except by an admin (`PUBLISH_RELEASE.bat` runs as the owner). |

Repository admins are bypass actors on `main` in **pull request mode**:
an admin can merge their own PR without a second approval, but still
can't push straight to the branch.

There is no CI yet, so no status checks are required. When a workflow
is added, list its job names under a `required_status_checks` rule in
`main.json`, or PRs will merge without waiting for it.
