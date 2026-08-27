# Phase 0C-B unresolved legal questions

## Status and use

This register is an engineering handoff for qualified counsel and privacy operations. It is not legal advice and does not claim compliance. The application deliberately fails closed until approved policy, purpose, retention, consent, and processor records exist.

The register was reviewed on 2026-08-24. Laws, regulations, regulator guidance, adequacy findings, and commencement dates can change; each production policy version needs a dated legal approval and source record.

## Decisions required for every launch

1. Identify the controller/legal entity, establishments, target users, and territorial scope.
2. Determine all simultaneously applicable national, state/provincial, sector, employment, consumer, AI, biometric, communications, and data-broker rules.
3. Approve a legal basis for every purpose/category combination, including core service, fraud/security, analytics, model improvement, research, marketing, and future community contributions.
4. Approve notice and consent wording, bundling rules, proof requirements, withdrawal consequences, and whether re-consent is needed after a material version change.
5. Define identity-verification, authorized-agent/representative, refusal, extension, fee, appeal, and response-deadline rules for each request type.
6. Approve minimum and maximum retention, legal holds, dispute/fraud evidence, account re-registration, anonymization standards, and audit-evidence retention.
7. Approve backup horizons, deletion-manifest control-plane location, integrity/signing, restore-gate ownership, and evidence that restored data cannot reappear.
8. Review every processor/subprocessor, processing and storage region, onward transfer, contract/DPA, transfer mechanism, government-access risk, deletion API, and SLA.
9. Decide whether interview answers, CV data, voice, video, inferred skill state, accessibility data, or future integrity events are sensitive/special-category/biometric data.
10. Determine DPIA/impact-assessment, DPO/representative, registration, records-of-processing, breach-notification, localization, certification, and regulator-contact obligations.
11. Validate that an 18+ product gate is legally and operationally sufficient and define handling for false attestation or an account later identified as underage.
12. Approve whether de-identified/aggregated data may survive account deletion, the technical anonymization test, and how provenance-based derived data is withdrawn.

## Initial jurisdiction review queue

| Jurisdiction family | Questions that remain unresolved before enablement | Primary starting source |
|---|---|---|
| Azerbaijan | Information-system registration/certification scope; consent proof; confidential-data transfer; cross-border restrictions; localization/security rules; request/deletion procedure and deadlines. | [Azerbaijan Law on Personal Data](https://frameworks.e-qanun.az/19/f_19675.html) |
| EU/EEA | Controller establishment and territorial reach; Article 6/9 bases; consent granularity; DSAR deadlines/exceptions; DPIA; DPO/representative; SCC/adequacy/transfer-impact measures; anonymization threshold; AI Act interaction. | [GDPR official text](https://eur-lex.europa.eu/eli/reg/2016/679/2016-05-04/eng) |
| United Kingdom | UK GDPR/Data Protection Act scope; changes under the Data (Use and Access) Act; request extensions/refusals; UK IDTA/Addendum and data-protection test; UK representative/DPO questions. ICO guidance was under revision at review time. | [ICO erasure guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/), [ICO international transfers](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/international-transfers/) |
| United States | Federal sector laws plus a maintained state-law applicability matrix; California and other state thresholds/exemptions; access/deletion/correction/portability; authorized agents; opt-out preference signals; sale/share/targeted advertising; sensitive data; profiling; data-broker duties. | [California Privacy Protection Agency laws and regulations](https://cppa.ca.gov/regulations/) |
| Canada | PIPEDA versus substantially similar provincial laws; Quebec/Alberta/BC requirements; meaningful consent; access timeline; cross-border transparency/accountability; privacy impact and breach duties; pending legislative change. | [OPC PIPEDA requirements](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/pipeda_brief/), [OPC consent guidance](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/principles/p_consent/) |
| Turkey | KVKK legal bases and explicit-consent scope; special-category handling; current international-transfer mechanisms; VERBIS/representative duties; deletion/destruction/anonymization policy and periodic-destruction requirements. | [KVKK Personal Data Protection Law](https://www.kvkk.gov.tr/Icerik/6649/Personal-Data-Protection-Law) |
| Brazil | LGPD controller/operator roles and bases; data-subject request procedure; DPO and records; sensitive data; ANPD international-transfer regulation, clauses, adequacy, and assessment; anonymization standard. | [LGPD official text](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), [ANPD international-transfer regulation](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/regulation-on-international-transfer-of-personal-data.pdf) |
| India | Exact commencement schedule and rules in force at launch; notice/consent and Consent Manager use; “certain legitimate uses”; erasure/access/grievance procedure; Significant Data Fiduciary designation; cross-border restrictions. The Act defines a child as under 18, consistent with the product gate but not a substitute for age-control review. | [Digital Personal Data Protection Act 2023](https://www.meity.gov.in/static/uploads/2024/02/Digital-Personal-Data-Protection-Act-2023.pdf) |
| Australia | Privacy Act/APP applicability and small-business exceptions; reform status; access/correction rather than a universal erasure assumption; destruction/de-identification; APP 8 accountability and overseas disclosure; consent quality for sensitive data. | [OAIC Australian Privacy Principles](https://www.oaic.gov.au/privacy/australian-privacy-principles/read-the-australian-privacy-principles) |
| Singapore | PDPA deemed/express consent; withdrawal effects; access/use/disclosure lookback; retention limitation; transfer-comparability evidence; data-intermediary allocation; breach duties; confirm whether data portability is in force because PDPC states it takes effect when regulations are issued. | [PDPC data-protection obligations](https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act/data-protection-obligations) |
| UAE | Federal PDPL territorial scope and executive instruments; UAE Data Office guidance; consent/exceptions; cross-border requirements; distinguish federal regime from DIFC, ADGM, health, free-zone, and emirate-specific rules. | [UAE Government data-protection laws](https://u.ae/en/about-the-uae/digital-uae/data/data-protection-laws.) |

## Deferred jurisdictions

Japan, South Korea, Switzerland, Saudi Arabia, New Zealand, and South Africa currently resolve only to `GLOBAL_BASELINE` and therefore cannot be enabled for personal-data processing. Each requires a versioned routing module, approved privacy policy, purpose/legal-basis rules, retention rules, request procedure, and processor/transfer review. Adding those modules must not change interview-domain code.

