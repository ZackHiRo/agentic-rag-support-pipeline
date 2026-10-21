# Process Rules (Example Demonstration)

> [!NOTE]
> This is an example process rules document demonstrating the operational policies
> used in player support before the multi-agent refactor. In the multi-agent architecture,
> these rules are handled by the Safety Agent and structured Pydantic schemas.

---

## 1. PII Redaction Policy
Support agents must inspect all incoming tickets for Personally Identifiable Information (PII).
- **Must-redact:** Passwords, phone numbers, full postal addresses, government IDs, full credit card numbers.
- **Investigation process:** Cross-check the account in admin tools, then redact sensitive fields from tickets.

---

## 2. Supported and Unsupported Languages
- **Supported:** English, French, German, Spanish, Portuguese, Japanese, Simplified Chinese, Traditional Chinese.
- **Unsupported languages:** When a ticket arrives in an unsupported language, write the reply in English and include standard machine translation advisory notice.

---

## 3. Third-Party Inquiries
- If a user contacts support on behalf of another player ("my friend", "my sibling"), agents must explain privacy regulations prevent discussing third-party account details.
- Request the account owner contact support directly from their registered email.

---

## 4. Escalation Paths
- **Tier 2 Technical Support:** Persistent network issues, complex billing discrepancies, corrupt client installations.
- **Tier 3 Engineering:** Verified reproducible server-side exploits, critical game-wide outages.
- **Support Leadership:** High-priority controversies, legal inquiries, severe RLT (Real Life Threat) safety reports.
