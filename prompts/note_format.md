# Internal note format (always apply)

The `internal_note` output MUST follow the schema defined below.
Preserve section names, ordering, and the three-part structure:
Identification → Assessment → Resolution.

---

## Required Internal Note Schema

```markdown
## Identification
- **Customer ID:** (Player's unique account identifier, e.g. EVD-1234-5678-ABCD. Use `(pending)` if unknown)
- **Platform:** (PC, PS4, PS5, Xbox, Switch, Mobile, or `(pending)` if unknown)
*(Include Reported User ID and Reference ID ONLY if this is a player report ticket; omit both entirely otherwise):*
- **Reported User ID:** (Reported/offending player's ID)
- **Reference ID:** (In-game report or telemetry ID)

## Assessment
- **Summary:** (Very concise 1–2 sentence statement of the issue so anyone opening the ticket immediately knows what it is about. If an error message or error code is present, it MUST be included here.)
- **Findings:** (Relevant technical findings from admin tool investigation, error codes, proof of purchase validation, ban reasons, or session data. Use `(pending)` for lookups the human agent still needs to perform.)
- **Matched Documentation:** (Title and section of the operational SOP or Known Issue applied, e.g., "Connection Issues — Troubleshooting Guide > Procedures". State "None" if no SOP matched.)

## Resolution
- **Actions Taken:** (Ordered list of actions performed on this ticket, e.g.:
  - Investigated session logs in admin tools
  - Provided network troubleshooting steps to player
  - Requested client diagnostic logs)
- **PII Status:** (State "None detected" if no PII was found. If PII was present, state "Detected — [type, e.g., phone number, full address, password]".)
- **Escalation:** (State "N/A" if not escalated. If escalated, specify reason, evidence, and target tier/team.)
```

---

## Operating Instructions

1. **Player reports only:** Do NOT include `Reported User ID` or `Reference ID` unless the ticket is reporting another player.
2. **Concise summary:** Keep the Summary short and immediately informative. Always include any error message or code.
3. **Do not invent data:** Never fabricate customer IDs, admin tool results, macro names, compensation values, or ban reasons.
4. **Use pending markers:** Where the human agent still needs to perform a verification or tool lookup, use `(pending)`.
5. **Language:** Internal notes must ALWAYS be written in English, regardless of the incoming ticket language.
6. **Escalations:** If the ticket meets escalation criteria, specify the reason for escalation, evidence gathered, and target tier/team clearly in the Escalation field.
