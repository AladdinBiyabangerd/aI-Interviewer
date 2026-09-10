# Java question source ingestion

Uploaded question PDFs enter a private, deterministic staging workflow. They do not
become public assessment questions automatically. This keeps extraction fast and makes
every source question, answer, page and parser release reviewable before publication.

## Why this path does not use RAG

Question extraction is a document-structure problem: find numbered stems and choices,
pair each item with its exact answer and explanation, and preserve page provenance. A
retrieval model would add latency and probabilistic matching where exact numbering is
available. `scripts/extract_java_questions.py` therefore uses bounded PDF text extraction
and deterministic parsing. RAG can be added later for semantic search, study-plan
recommendations or finding related questions after approved content has a stable ID.

## Current source profiles

`selikoff-java-8` parses the 23 question chapters and the answer appendix in *OCA/OCP
Java SE 8 Programmer Practice Tests*. It supports question or answer numbers that PDF
extraction places on a line by themselves and ignores numbered Java source lines.

`ingress-exam` parses a single numbered exam. If the PDF has no answer key, every item is
stored as `needs_answer`; the parser never guesses an answer.

Both profiles write a create-only JSON artifact containing the source SHA-256, parser
release, page count, chapter and question numbers, page range, choices, answer,
explanation, parse status and machine-readable issue codes. Reusing a source digest with
changed output requires a parser release bump.

```powershell
uv run python scripts/extract_java_questions.py `
  --profile selikoff-java-8 `
  --input "C:\path\to\book.pdf" `
  --output "tmp\pdfs\book-extraction.json" `
  --source-title "OCA/OCP Java SE 8 Programmer Practice Tests" `
  --authors "Scott Selikoff; Jeanne Boyarsky" `
  --publisher "Sybex/Wiley" `
  --publication-year 2017 `
  --reference-url "https://uat.store.wiley.com/en-us/oca-ocp-java-se-8-programmer-practice-tests-p-9781119363361"

uv run python scripts/extract_java_questions.py `
  --profile ingress-exam `
  --input "C:\path\to\exam.pdf" `
  --output "tmp\pdfs\exam-extraction.json" `
  --source-title "EXAM - 1"
```

## Private database staging

Migration `20260910_0016` adds two operator-only tables:

- `java_question_import_batches` stores source identity, parser provenance, extraction
  counts, report and the independent rights-review decision.
- `java_question_import_candidates` stores private parsed material and its correctness
  review state. It has no public API and is not read by assessment creation.

Apply the release migration to the intended environment, then stage the extraction:

```powershell
cd frontend
npm run bank -- stage ..\tmp\pdfs\book-extraction.json
npm run bank -- stage ..\tmp\pdfs\exam-extraction.json
npm run bank -- staged
```

Staging is transactional and idempotent for `(source_sha256, parser_release)`. It rejects
malformed candidates, invalid page ranges, answer IDs absent from the choices, oversized
artifacts and changed extraction output under the same parser release. Source material
always begins with `rights_status=unverified`.

## Review and publication gate

Before any staged item is rewritten as an original public question revision, a reviewer
must verify:

1. the prompt and all choice text against the recorded source pages;
2. the answer and explanation, including every item marked `needs_answer` or
   `needs_review`;
3. compatibility with the supported Java version and the intended level/topic tags;
4. permission to use or adapt the material and any required attribution; and
5. original wording for the public bank rather than direct source reproduction.

Record a completed source-rights decision with an exact batch UUID:

```powershell
npm run bank -- source-rights <batch-uuid> cleared
# or
npm run bank -- source-rights <batch-uuid> rejected
```

There is deliberately no bulk command from staging to `java_question_bank`. Publication
continues through the existing versioned draft, review and explicit publish workflow.
This prevents a parser result or unverified copyrighted source from becoming live content.

## Verified extraction baseline

On September 10, 2026, parser release `java-pdf-questions-v7` produced:

| Source | Pages | Questions | Answers | Review result |
|---|---:|---:|---:|---|
| OCA/OCP Java SE 8 practice book | 601 | 1,095 | 1,095 | 1,076 complete; 19 visual-review items |
| EXAM - 1 | 31 | 70 | 0 | All 70 need answers |

The book count is also validated per chapter: chapters 1–9 have 50 questions each,
chapter 10 has 80, chapters 11–22 have 40 each, and chapter 23 has 85. These counts
describe extraction completeness, not editorial approval or permission to publish.
