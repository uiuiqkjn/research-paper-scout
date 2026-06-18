---
name: research-paper-scout
description: "Scout prior art for a proposed research direction by searching scholarly databases and judging title/abstract content overlap, not just keyword matches. Use when the user asks whether a direction has already been studied, whether an idea is novel, \"has anyone done this?\", \"is this direction novel?\", \"有没有人做过这个方向?\", or provides a proposed topic plus keywords, year range, max results, and optional venues. Produce exactly two files: papers.csv and prior_art_conclusion.md."
---

# Research Paper Scout

Use this skill to run a reproducible, cross-database prior-art check for a proposed research topic.

## Inputs

Collect or infer these fields before running the script:

- `research_topic`: concise proposed direction or question. Prefer a statement that includes the problem, method, data/domain, and evaluation target when available.
- `keywords`: comma/semicolon-separated method names, task names, datasets, domains, acronyms, and synonyms.
- `year_from`, `year_to`: inclusive publication year range.
- `max_results`: number of ranked papers to keep. Use 50-100 for prior-art checks unless the user asks for a smaller set.
- `venues`: optional comma/semicolon-separated conference, journal, or venue abbreviations.

If the topic is too vague to distinguish problem, method, and domain, ask for the missing topic details instead of inventing them.

## Run The Search

Prefer the bundled script for end-to-end searches:

```bash
python3 /Users/zhang/.codex/skills/research-paper-scout/scripts/research_paper_scout.py \
  --intent prior-art \
  --research-topic "retrieval augmented generation for scientific literature" \
  --keywords "RAG,retrieval augmented generation,scientific literature,question answering" \
  --year-from 2021 \
  --year-to 2026 \
  --max-results 50 \
  --venues "ACL,EMNLP,NAACL,NeurIPS,ICLR,SIGIR" \
  --output-dir ./outputs
```

The script searches OpenAlex, Crossref, DBLP, arXiv, and Semantic Scholar when available. It deduplicates by normalized DOI first, then normalized title; enriches candidates with Semantic Scholar metadata when possible; reranks results; and writes:

- `papers.csv`
- `prior_art_conclusion.md`

Do not create BibTeX, JSON, or extra ranking summaries unless the user explicitly asks for additional files.

## Ranking Signals

Treat the ranking as a heuristic for scouting, not as bibliometric truth.

- Content similarity: overlap between the proposed topic/keywords and each paper's title plus abstract after normalization.
- Concept coverage: coverage of the proposed topic, method, data/domain, and evaluation concepts.
- Domain focus: presence of distinctive domain anchors instead of generic research terms.
- Method focus: evidence that the proposed technical approach appears in the title/abstract.
- Citations: log-scaled citation count so older classics do not dominate.
- Recency: modest boost for newer papers inside the requested year range.
- Venue match: strong boost for requested venues; smaller boost for known selective venues.
- Survey/review signal: small boost for `survey`, `review`, `systematic review`, `taxonomy`, `overview`, or `tutorial`.

## Prior-Art Verdict

Base the verdict on title and abstract content, not title keyword containment alone.

- `likely_done`: multiple papers strongly match the same problem, method, and domain pairing.
- `partially_done`: adjacent work exists, but the exact task, method, modality, dataset, population, constraint, or evaluation differs.
- `no_clear_prior_work_found`: no strong content-level match appears in the searched sources.

When judging closeness, compare:

- Research problem or task.
- Core method or technical approach.
- Data, object, population, benchmark, or domain.
- Application scenario.
- Evaluation goal, metric, or claimed contribution.

Separate these cases clearly:

- Same problem and similar method.
- Same problem but different method or setting.
- Same method but different problem, data, or domain.

Avoid saying "nobody has done this" unless the search is very narrow and all APIs succeeded. Prefer "I did not find a clear prior match in these sources."

## Research Gaps

Phrase gaps as follow-up hypotheses, not definitive claims. Useful signals include:

- Keywords with few or no strong matches.
- Recent relevant papers with low citation counts.
- Results clustered in a narrow venue or subfield.
- Repeated limitations visible in abstracts.
- Survey coverage without many recent empirical papers.

## API And Failure Handling

- OpenAlex, Crossref, DBLP, and arXiv work without API keys.
- Semantic Scholar enrichment works without `S2_API_KEY`, but rate limits are stricter. If `S2_API_KEY` exists, the script also runs Semantic Scholar search.
- If one source fails, continue with remaining sources and disclose partial coverage in `prior_art_conclusion.md`.
- For high-stakes literature reviews, recommend manual validation of inclusion criteria, related-work sections, and references.

## Output Rules

The final user response should return only links to the two generated files:

- `papers.csv`
- `prior_art_conclusion.md`

Do not paste paper lists inline unless the user explicitly asks.

`prior_art_conclusion.md` must contain the direct answer, verdict and confidence, 3-5 closest evidence papers, why they are content-similar or different, what seems already covered, possible remaining novelty, possible research gaps, reliability warnings when needed, and API/source status.

`papers.csv` must contain scores, content similarity, concept coverage, domain/method focus, bibliographic metadata, URLs, sources, survey flag, and abstracts.
