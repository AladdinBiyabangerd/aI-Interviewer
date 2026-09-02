# Phase 1B-D2 development corpus preparation record

Date: 2026-09-02

## Outcome

The repository now contains a deterministic 40-fixture Azerbaijani/English CV and job-
description development corpus. It is structurally ready for an authorized provider run:
each primary language/document slice has 10 fixtures, all profile fields have sufficient
gold support, and both required risk slices have 16 fixtures.

This is a synthetic development benchmark. It improves prompt and adapter testing, but it
does not close Phase 1B-D2.2b2 and must not be represented as evidence of production
quality on real candidate or employer documents.

## Rights-reviewed source

Role names, task statements, and in-demand software-skill selections were derived from
downloadable files in the official [O*NET 31.0 Database](https://www.onetcenter.org/database.html).
The database permits copying and adaptation under
[CC BY 4.0](https://www.onetcenter.org/license_db.html) with attribution and modification
notice. The downloaded source files were pinned as follows:

| Official file | SHA-256 |
|---|---|
| `occupation_data.json` | `8eec5d2449c0b96a90fca0f67184b3bf76c15b3549c4f145adb48c3ae55f52f8` |
| `task_statements.json` | `d48d985c2bcf39a8760c9ffac599cd12309d597d564856e4bb3e9759ee948545` |
| `software_skills.json` | `bf4eb584f40e8139763babc50e3b9539b07e59a1df971d812293b307cbad84d1` |

This repository has modified some O*NET information. USDOL/ETA has not approved,
endorsed, or tested these modifications. O*NET® is a trademark of USDOL/ETA.

The ten selected `(O*NET-SOC code, task ID)` coordinates are:

- `(15-1211.00, 20950)`
- `(15-1212.00, 5314)`
- `(15-1242.00, 1299)`
- `(15-1244.00, 1319)`
- `(15-1252.00, 21662)`
- `(15-1253.00, 14642)`
- `(15-1254.00, 14707)`
- `(15-1299.05, 21776)`
- `(15-1299.08, 14666)`
- `(15-2051.00, 21823)`

The English occupation material is combined with explicitly fictional project,
achievement, and seniority statements. Azerbaijani versions are modified translations
that still require an independent Azerbaijani-language reviewer. No name, email, phone,
address, employer identity, or scraped résumé is included.

## Rejected internet source

The commonly mirrored `opensporks/resumes` dataset was not ingested. Its dataset card
states that examples were scraped from LiveCareer while leaving personal/sensitive-data
documentation incomplete. A repository-level CC0 label does not by itself establish that
the upstream page content was lawfully relicensed.

## Reproducible commands

```powershell
uv run ai-interviewer-profile-quality build-development-corpus `
  docs/quality/fixtures/phase-1b-d2-development-corpus.json
uv run ai-interviewer-profile-quality validate-corpus `
  docs/quality/fixtures/phase-1b-d2-development-corpus.json
```

The generated canonical artifact digest is
`58742bc4e2ae0bd86a1ce7582fc2c4aacb2c316456a2791a7ba0689ba4f739c5`.
Generation and validation print only counts, safe identifiers, and digests.

## Remaining D2.2b2 gate

- replace or supplement the synthetic benchmark with an access-controlled corpus whose
  real-document rights and privacy controls have been reviewed;
- obtain exact-corpus external-processing authorization for a newly issued, non-exposed
  OpenAI credential and one immutable model release;
- complete human adjudication, owner outcomes, and error analysis;
- pass every quality threshold and bind four named approvals to the evidence digest.
