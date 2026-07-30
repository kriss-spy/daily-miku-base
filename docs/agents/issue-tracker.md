# Issue Tracker: GitHub

Issues and planning artifacts for this repository live in GitHub Issues. Use the `gh` CLI for all operations and infer the repository from the current clone.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- Read an issue with `gh issue view <number> --comments --json number,title,body,state,assignees,labels,url`.
- List issues with `gh issue list --state open --json number,title,body,labels,assignees,url` and suitable filters.
- Comment with `gh issue comment <number> --body "..."`.
- Apply or remove labels with `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close an issue with `gh issue close <number> --comment "..."`.

When a skill says to publish to the issue tracker, create a GitHub issue. When it says to fetch a ticket, use `gh issue view` and include comments.

## Wayfinding Operations

Wayfinding maps and tickets use GitHub's native issue relationships so the map remains visible and queryable in GitHub.

- A map is an issue labelled `wayfinder:map`.
- A ticket is a native sub-issue of its map and has exactly one of `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- Create all map and ticket issues first, then connect each ticket with `gh api --method POST repos/{owner}/{repo}/issues/<map-number>/sub_issues -f sub_issue_id=<ticket-database-id>`. Obtain the database id with `gh api repos/{owner}/{repo}/issues/<ticket-number> --jq .id`.
- Add a native blocking edge with `gh api --method POST repos/{owner}/{repo}/issues/<blocked-number>/dependencies/blocked_by -f issue_id=<blocker-database-id>`.
- Claim a ticket before work with `gh issue edit <ticket-number> --add-assignee @me`.
- List a map's children with `gh api repos/{owner}/{repo}/issues/<map-number>/sub_issues`.
- The frontier is the map's open, unassigned children whose `blocked_by` dependency list contains no open issue. Query each candidate's dependencies with `gh api repos/{owner}/{repo}/issues/<ticket-number>/dependencies/blocked_by`.
- Record a resolution as a comment, close the ticket, and append only a linked one-line gist to the map's `Decisions so far` section.

Always refer to maps and tickets by their linked titles in human-readable output, never by bare issue numbers.
