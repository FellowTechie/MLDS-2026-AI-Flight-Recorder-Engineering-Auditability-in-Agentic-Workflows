# EU AI Act Compliance Cheat Sheet — For Agent Developers

> ⚠️ **Key Deadline: August 2, 2026** — High-risk AI system requirements become enforceable.
> This is a technical cheat sheet, not legal advice. Consult your legal team for compliance strategy.

---

## The Three Articles That Matter for Agentic Systems

### Article 12 — Record-Keeping (Automatic Logging)

**What it says:** High-risk AI systems must allow for *automatic recording of events* ('logs') while operating.

**What it actually requires you to build:**

| Requirement | What to Log | Flight Recorder Mapping |
|------------|------------|------------------------|
| Period of each use | Session start/end timestamps | `timestamp` + `duration_ms` on root span |
| Reference database used | Which data sources were queried | `tool_calls[].tool_name` + `parameters` |
| Input data leading to match | Inputs that triggered decisions | `reasoning.rationale` + event payloads |
| Identification of verifiers | Who reviewed the results | `compliance.human_in_loop` + user ID |

**Critical word:** *"Automatic."* Not documented after the fact. Not reconstructed from memory. The system itself must produce these logs as it operates.

**Retention:** Minimum 6 months, longer if national law requires it.

---

### Article 14 — Human Oversight

**What it says:** High-risk AI systems must be designed to allow effective human oversight during use.

**What it actually requires you to build:**

| Requirement | Implementation |
|------------|---------------|
| Ability to understand system capabilities & limitations | Dashboard showing agent confidence scores, error rates |
| Ability to monitor operation | Real-time trace viewer (Langfuse/Jaeger) |
| Ability to interpret outputs | Reasoning traces with rationale logging |
| Ability to override/interrupt | Kill switch + approval gates on high-risk actions |
| Ability to decide not to use the system | Fallback routing to human operators |

**For multi-agent systems:** Human oversight must be possible at the *orchestrator level*, not just individual agent level. If 4 agents collaborate on a decision, a human must be able to trace and intervene at any point in the chain.

---

### Article 19 — Automatically Generated Logs (Retention)

**What it says:** Providers must *keep* the logs from Art. 12, to the extent they have control over them.

**What it actually requires you to build:**

| Requirement | Implementation |
|------------|---------------|
| Log retention ≥ 6 months | Hot/warm/cold storage tiers with lifecycle policies |
| Logs under provider control | Self-hosted event store, not only third-party SaaS |
| Financial institutions: retain as part of financial records | Extended retention (7+ years) with compliance tagging |

---

## Risk Classification: Is Your Agent "High-Risk"?

Your multi-agent system is likely **high-risk** (Annex III) if it's used in:

| Domain | Examples |
|--------|----------|
| Employment & HR | CV screening, interview scheduling, hiring decisions |
| Credit & Finance | Credit scoring, loan eligibility, risk assessment |
| Healthcare | Diagnostic support, treatment recommendations, triage |
| Education | Exam scoring, student assessment, admissions |
| Law Enforcement | Evidence analysis, profiling, predictive policing |
| Critical Infrastructure | Energy, water, transport management |
| Biometrics | Facial recognition, emotion detection |

**Pharma-specific:** AI systems assisting in clinical trial design, pharmacovigilance, or medical information responses may qualify as high-risk under healthcare provisions.

---

## Compliance Checklist for Agent Developers

```
□ Automatic logging enabled for all agent operations (Art. 12)
□ Logs capture: timestamps, data sources, inputs, decisions, verifiers
□ Logs are structured, machine-readable, queryable (not console.log)
□ Log retention ≥ 6 months with lifecycle management (Art. 19)
□ Human oversight dashboard operational (Art. 14)
□ Kill switch / approval gates on high-risk actions (Art. 14)
□ Reasoning traces capture WHY, not just WHAT (Art. 12 + 14)
□ PII redaction pipeline in place (GDPR intersection)
□ Guardrail checks logged with pass/fail status (Art. 9)
□ Trace correlation across all agents in the chain (multi-agent)
□ Risk management system is running, not just documented (Art. 9)
□ Technical documentation includes logging architecture (Art. 11)
□ Conformity assessment started (takes 6-12 months)
```

---

## Penalty Framework

| Violation Level | Maximum Fine |
|----------------|-------------|
| Prohibited AI practices | €35M or 7% of global annual turnover |
| High-risk system non-compliance | €15M or 3% of global annual turnover |
| Incorrect information to authorities | €7.5M or 1% of global annual turnover |

**For SMEs:** Fines are proportionally lower but still significant.

---

## Timeline at a Glance

```
Feb 2025  ████  Prohibited practices enforceable (DONE)
Aug 2025  ████  GPAI rules + governance infrastructure (DONE)
Aug 2026  ████  ← YOU ARE HERE — High-risk system requirements
Aug 2027  ████  Product-embedded AI (Annex I) + legacy GPAI
Aug 2030  ████  Legacy public sector systems
```

**Note:** The Digital Omnibus (Nov 2025) proposes conditional delays — if harmonized standards aren't ready, Annex III systems get up to Dec 2027. But don't plan for delay; plan for August 2026.

---

## Quick Reference: OTel → EU AI Act Mapping

| OTel Attribute | EU AI Act Article |
|---------------|-------------------|
| `trace_id` + `span_id` + `parent_span_id` | Art. 12 — Traceability |
| `gen_ai.agent.id` + `gen_ai.agent.name` | Art. 12 — System identification |
| `gen_ai.request.model` + `gen_ai.response.model` | Art. 12 — Model provenance |
| `gen_ai.usage.input_tokens` + cost | Art. 12 — Operational monitoring |
| `gen_ai.tool.name` + parameters | Art. 12 — Reference database / tool logging |
| Reasoning traces | Art. 14 — Interpretability for human oversight |
| Guardrail pass/fail events | Art. 9 — Risk management evidence |
| Human-in-loop flags | Art. 14 — Human oversight evidence |
| Evaluation scores | Art. 9 + Art. 72 — Post-market monitoring |

---

## Further Reading

- [Article 12 Full Text](https://artificialintelligenceact.eu/article/12/)
- [Article 14 Full Text](https://artificialintelligenceact.eu/article/14/)
- [Article 19 Full Text](https://artificialintelligenceact.eu/article/19/)
- [ISO/IEC DIS 24970:2025 — AI System Logging Standard](https://www.iso.org/standard/81203.html)
- [EU AI Act Implementation Timeline](https://artificialintelligenceact.eu/implementation/)
