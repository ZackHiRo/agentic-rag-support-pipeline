---
id: "demo-002"
title: "Account Linking and Recovery Guide"
type: procedure
category: account
slug: account-recovery
source_url: "https://support.novastargames.com/hc/en-us/articles/demo-002"
source_hash: "demo-002"
---

## Overview
This procedure details how support agents authenticate account ownership and process account recovery or cross-platform linking requests for NovaStar IDs.

## Investigation
1. Request the player's primary NovaStar ID (format: `EVD-XXXX-XXXX-XXXX`) and linked platform ID.
2. In BackOffice > Account Lookup:
   - Check current account status (Active, Suspended, or Flagged).
   - Review email verification status and date of account creation.
   - Inspect transaction history for any completed purchases (Nova Credits or Battle Pass).

## Procedures
To verify ownership for account recovery:
- If the player cannot access their registered email:
  - Request valid Proof of Transaction for the earliest purchase on the account (digital invoice from Steam, PlayStation Store, or Xbox Live showing Transaction ID, date, and item purchased).
  - Cross-reference the Transaction ID against BackOffice billing records.
- If ownership is confirmed:
  - Update the registered email address in BackOffice.
  - Trigger a password reset link to the new email address.
  - Apply macro: **Support::Account::Recovery Verified & Reset Sent**
- If proof of purchase is invalid or missing:
  - Inform the player that ownership cannot be verified without authentic purchase documentation.
  - Apply macro: **Support::Account::Proof Required**

## Escalation
Escalate to **Support Leadership** if:
- Suspected account takeover involving multiple high-value cosmetic transfers.
- Conflicting ownership claims between two distinct parties for the same NovaStar ID.
Apply macro: **Support::Escalations::Escalate to Support Leadership**
