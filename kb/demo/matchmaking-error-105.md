---
id: "demo-003"
title: "Known Issue — Matchmaking Error 105 in Crossplay Parties"
type: known-issue
category: gameplay
slug: matchmaking-error-105
source_url: "https://support.novastargames.com/hc/en-us/articles/demo-003"
source_hash: "demo-003"
---

## Issue Summary
Players in mixed-platform parties (e.g. PC and console) may encounter `Matchmaking Error 105` when entering the queue if the party leader has automatic region selection enabled.

## Investigation
1. Confirm if the player was queued as a solo player or in a crossplay group.
2. Check if Error Code 105 appears in the client crash log or error screenshot.
3. Verify that the player's game client is on the latest game version (v2.4.1 or higher).

## Workaround / Temporary Solution
Inform the player that our engineering team is actively testing a hotfix for this issue. In the meantime, advise them to use the following workaround:
1. Party leader must navigate to Settings > Gameplay > Matchmaking Region.
2. Manually select their nearest geographic server instead of leaving the setting on "Auto".
3. Disband and re-form the party lobby before re-entering matchmaking queue.

Apply macro: **Support::KnownIssues::Error 105 Workaround**

## Escalation
Do not escalate individual tickets for this error unless the player reports that the manual region workaround fails after restarting their system. In those cases, tag the ticket `bug_error105_unresolved` for developer review.
