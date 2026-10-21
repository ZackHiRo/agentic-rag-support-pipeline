"""Multi-agent pipeline for Everdawn player support triage.

Agents
------
safety      – PII detection, escalation, threat classification
note        – Internal note drafting (schema-focused)
reply       – Player reply drafting (tone-focused)
steps       – Next investigation steps extraction (SOP-focused)
qa          – Quality assurance, scoring, and retry orchestration
orchestrator– Pipeline entry point; runs stages and manages retries
"""
