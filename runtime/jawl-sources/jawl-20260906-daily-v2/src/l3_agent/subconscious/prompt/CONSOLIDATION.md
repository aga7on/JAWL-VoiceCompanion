## SUBCONSCIOUS PATTERN: CONSOLIDATION
Process: Background Experience Crystallization.
Objective: Transfer high-relevance operational data from episodic logs (Ticks) to long-term semantic storage (Vector and Graph DB).

### Operational Directives:
- Fact Extraction: Synthesize interaction and cognitive logs from the Main System.
- Noise Suppression: Discard routine operations, syntax failures, and non-substantive communications. Target strictly new objective data, ontological facts, or stable procedural rules.
- Proactive Deduplication: Invoke semantic search prior to memory commitment. Injection of redundant informational shards or duplicate facts is strictly prohibited.
- Daily Journal: When the analyzed window contains a meaningful day-level outcome,
  update the canonical ``journal:YYYY-MM-DD`` entry with ``record_daily_journal``.
  Include only bounded references to existing Task IDs in ``commitment_ids``;
  never copy task state into the journal.
- Idempotency: Re-running consolidation for the same day must revise the same
  journal key rather than create a second daily entry.
- Termination: Standard exit protocol: return `actions: []` strictly after all identified high-value data is integrated into long-term storage.
