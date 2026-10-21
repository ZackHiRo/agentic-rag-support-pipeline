---
id: "demo-001"
title: "Connection Issues — Troubleshooting Guide"
type: procedure
category: technical
slug: connection-issues
source_url: "https://support.novastargames.com/hc/en-us/articles/demo-001"
source_hash: "demo-001"
---

## Overview
Players experiencing disconnections, high latency, or timeout errors during matches should follow this procedure before any escalation.

## Investigation
1. Request the player's platform (PC/Steam, PlayStation, Xbox, Switch) and server region.
2. Check the server operational status dashboard for ongoing outages or scheduled maintenance.
3. Review the player's session history in the BackOffice tool:
   - Check packet loss indicators and disconnect frequency over the last 24 hours.
   - Verify whether an automated Disconnect Penalty was triggered.

## Procedures
If no active server outage is reported:
- Ask the player for their client error log (`NetLog.txt` located in `%localappdata%/Everdawn/Saved/Logs`).
- Provide standard network troubleshooting steps (wired Ethernet connection, router power cycle, DNS flush, firewall exceptions).
- Apply macro: **Support::Connection::Request Logs & Network Steps**

If an automated Disconnect Penalty occurred due to a confirmed server-side crash:
- Verify the server crash timestamp against the player's disconnect timestamp.
- If verified, waive the penalty in BackOffice and grant 500 Starshards compensation.
- Apply macro: **Support::Connection::Crash Compensation**

## Escalation
Escalate the ticket to **Tier 2 Support** if:
- Disconnections persist after network troubleshooting and clean log analysis.
- Multiple players from the same ISP report identical routing timeouts.
Apply macro: **Support::Escalations::Escalate to Tier 2**
