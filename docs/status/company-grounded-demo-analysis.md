# Company-grounded demo analysis

## Scope

The frontend demo now has a server-only analysis route that researches the requested
company before preparing likely interview questions. It is an MVP product path and does
not replace the production question-intelligence, corpus-quality, privacy, or deployment
gates documented in the main roadmap.

## Grounding contract

- The supplied company, role, vacancy text, interview stage, and optional job URL form
  the research target.
- OpenAI web search is restricted by instruction to official company, careers, product,
  engineering, and reputable public business or technical sources.
- Similar company names must be disambiguated before a source is used.
- A question receives the `Company evidence` label only when at least one URL supplied
  with that question matches a source returned or cited by the research response.
- A company-grounded question must mention a concrete verified signal in the question
  itself. A citation alone must not promote a generic role question to company-specific.
- Unsupported questions remain explicitly labeled as vacancy or role-pattern questions.
- The UI exposes the researched signals, overall source list, and per-question evidence
  as clickable links.

These are evidence-grounded likely questions. The system does not claim access to a
company's private question bank and does not use leaked or confidential question dumps.

## CV boundary

An optional PDF or DOCX CV is processed in a separate Responses API request without web
search. This keeps CV contents out of search queries. The CV request is limited to two
role-relevant questions and is instructed not to repeat contact or sensitive personal
details.

## Failure behavior

The OpenAI key stays on the server. The route rejects malformed or oversized input,
limits requests per client for the demo, disables response storage, and returns no
provider payload on failure. When same-origin live research is unavailable, the client
uses an honestly labeled local preview instead of fabricating company evidence.
