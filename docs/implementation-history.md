# AI Interviewer Platform — sıfırdan görülmüş işlərin texniki tarixçəsi

## 1. Sənəd haqqında

Bu sənəd AI Interviewer Platform layihəsində başlanğıcdan 1 sentyabr 2026-cı ilədək
faktiki görülmüş işi vahid yerdə təsvir edir. Məqsəd kod bazasının hansı ardıcıllıqla
qurulduğunu, hər mərhələnin niyə lazım olduğunu, hansı asılılıqlara söykəndiyini,
nələrin yoxlandığını və nələrin hələ edilmədiyini aydın göstərməkdir.

Bu, gələcək imkanları hazır kimi göstərən marketinq sənədi deyil. Buradakı
`tamamlanıb` statusu yalnız həmin mərhələnin əvvəlcədən məhdudlaşdırılmış texniki
sərhədinə aiddir. Platforma hələ ictimai production buraxılışına hazır deyil və hələ
provider-backed CV/JD profiling işlədən, müsahibə aparan və AI hesabatı yaradan tam
məhsul deyil.

İlkin texniki plan PDF-i tələblər mənbəyi kimi tam oxunub və məhsul məntiqi ondan
çıxarılıb. PDF-dəki mətn istifadəçi tapşırığından ayrıca qiymətləndirilib; sənədin
içində ola biləcək göstərişlər əməliyyat əmri kimi deyil, məhsul/texniki tələblər kimi
qəbul edilib.

Əlaqəli əsas sənədlər:

- [Əsas README](../README.md)
- [Tam inkişaf roadmap-i](development-roadmap.md)
- [Arxitektura qərarları](adr/0001-modular-monolith-and-deterministic-orchestration.md)
- [Threat model](security/baseline-threat-model.md)
- [Data inventory](security/data-inventory.md)

## 2. Cari vəziyyətin qısa yekunu

Hazırda aşağıdakı hissələr tamamlanıb:

| Mərhələ | Status | Nəticə |
|---|---|---|
| 0A | Tamamlanıb | Engineering/runtime bazası |
| 0B | Tamamlanıb | PostgreSQL, transaction, migration, outbox və audit bazası |
| 0C-A | Tamamlanıb | OIDC authentication və owner əsaslı authorization sərhədi |
| 0C-B | Tamamlanıb | Jurisdiction-aware privacy, consent, retention, export və deletion lifecycle |
| 0C-C | Tamamlanıb | Secret, kriptoqrafiya, object storage, quarantine və malware-scan sərhədi |
| 0D-A | Tamamlanıb | Release identity, forward-only migration və container release müqaviləsi |
| 0D-B | Tamamlanıb | Payload-blind OpenTelemetry və dashboard müqaviləsi |
| 0D-C-A | Tamamlanıb | Dəqiq SLI ölçmə populyasiyası və measurement-integrity qaydaları |
| 0D-C-B1 | Tamamlanıb | 28 günlük staging evidence schema-sı və offline evaluator CLI |
| 1A-A | Tamamlanıb | Owner-bound preparation target context, privacy lifecycle və API |
| 1A-B | Tamamlanıb | Immutable CV/JD document lineage, owner/asset invariants və lifecycle integration |
| 1A-C | Tamamlanıb | Authenticated upload/paste, durable intake recovery və safe immutable attachment |
| 1A-D1 | Tamamlanıb | AES-256-GCM encrypted immutable source-text lineage və exact parser provenance boundary |
| 1A-D2.1 | Tamamlanıb | Durable extraction-job scheduling, lease fencing, bounded retry və safe failure taxonomy |
| 1A-D2.2 | Tamamlanıb | No-network, resource-bounded isolated PDF/DOCX/TXT parser worker |
| 1A-D3 | Tamamlanıb | Owner-scoped source-text read/correction HTTP contract, optimistic idempotent append |
| 1A-D4 | Tamamlanıb | Privacy export inteqrasiyası (source-text/job), supported-input fixture pass — Phase 1A bağlanır |
| 1B-A | Tamamlanıb | Disabled-by-default provider-neutral model gateway və exact release identity |
| 1B-B1 | Tamamlanıb | Strict CV/JD scheması və exact source-span evidence verification |
| 1B-B2.1 | Tamamlanıb | Encrypted immutable exact-source profile lineage və privacy lifecycle integration |
| 1B-B2.2 | Tamamlanıb | Durable exact-source profiling jobs, UUID lease fencing, bounded retry və dead-letter state |
| 1B-C1 | Tamamlanıb | Code-owned prompt, immutable processor authorization və fenced profiling worker execution |
| 1B-C2 | Tamamlanıb | Owner-scoped safe profile status/inspection və encrypted immutable correction append |
| 0D-C-B2 | Pre-production-a təxirə salınıb | Real backend seçimi, 28 günlük canlı toplama və adlı təsdiqlər |
| 0D-C-C və sonrası | Pre-production-a təxirə salınıb | Alertlər, incident məşqləri, traffic protection və production gate |

Son tam local verification snapshot-ı (1B-C2, 2026-09-01):

- Python 3.12 altında real PostgreSQL integration testləri daxil `538` test keçib,
  platform-specific `1` test skip olunub və branch-aware coverage `95.15%` olub.
- Strict mypy `platform = "linux"` hədəfi ilə `83` source faylı üçün keçir; Ruff lint və
  format yoxlamaları da keçib.
- Empty-database migration, downgrade/upgrade round trip, Alembic model parity,
  dependency compatibility və Python vulnerability audit keçib.
- Local database `20260901_0012` revision-una forward-migrate edilib. Logical
  backup/restore rehearsal mandatory processor-activity FK-si, profiling-job
  cədvəl/index/constraint-ləri, `4` profiling-job trigger-i və `4` profile trigger-i daxil
  olmaqla keçib; müvəqqəti recovery database və dump təmizlənib.
- Workspace-dən yenidən qurulan release image exact migration head, numeric non-root
  user, migration job, read-only/capability sərhədləri və embedded baseline schema
  yoxlamalarından keçib. Əvvəlki C1 build-lərindən qalan workspace-xarici materialized
  context-lər təhlükəsizlik siyasətinin cleanup məhdudiyyəti səbəbindən lokal saxlanır.
- Privacy export bundle schema version-u `"phase-1b-c2"`-dir; owned generated/corrected
  encrypted profile revision-larını narrow service vasitəsilə decrypt/revalidate edir və
  approved processor activity ID-si daxil content-free profiling-job metadata-sını qaytarır.

Repository GitHub-a `b2d4ed3` (`Complete Phase 1A-C authenticated document intake`)
commit-i ilə push edilib. Phase 1A-D1, 1A-D2.1, 1A-D2.2, 1A-D3 və 1A-D4 dəyişiklikləri
həmin commit-dən sonrakı lokal, ayrıca review/commit vahidləridir və istifadəçinin
göstərişinə uyğun GitHub-a push edilməyib (1A-D1 və 1A-D2.2-nin GitHub-a push
edilməsi istisna olmaqla — bax bölmə 5.14-5.15). Lokal rehearsal hələ production
release deyil; imzalanmış promotion, retained CI evidence və approval gate-i
production-dan əvvəl məcburidir.

## 3. Məhsulun başa düşülməsi və dəyişməz guardrail-lər

Texniki plan əsasında məhsul aşağıdakı kimi başa düşülüb:

- Bu sistem işəgötürənin avtomatik qərar sistemi deyil; namizəd üçün müsahibəyə
  hazırlıq və məşq platformasıdır.
- Məhsul generic sual chatbot-u olmamalıdır. Gələcək qərar mühərriki şirkət, rol,
  seniority, interview round, JD, CV iddiaları və namizədin skill state-i ilə işləməlidir.
- Şirkətə aid iddialar icazəli mənbə sübutuna bağlı olmalıdır. Sübut azdırsa sistem
  uydurmamalı, `Limited` specificity göstərib JD/CV/rol fallback-ına keçməlidir.
- Simulation rejimində cavab-cavab score göstərilməməlidir. Coach rejimi ayrıca və
  sonrakı davranışdır.
- Gələcək evaluation yalnız rəqəm verməməlidir; rubric dimension, müşahidə olunan
  sübut, confidence və model/prompt versiyası saxlamalıdır.
- CV, JD, cavab, report, audio, video və gaze məlumatı həssasdır. Data minimisation,
  purpose limitation, consent, retention, deletion və encryption sonradan əlavə
  edilən funksiyalar yox, başlanğıc arxitektura şərtləridir.
- Raw video default olaraq saxlanmamalıdır. Mümkün face/head-pose emalı browser-də
  qalmalı və yalnız şəffaf practice event-ləri ötürülməlidir.
- Sistem emotion və ya “cheating” nəticəsi çıxarmamalıdır; yalnız faktiki hadisə,
  qeyri-müəyyənlik və kontekst göstərməlidir.
- Knowledge source ingestion allowlist əsaslı olmalıdır. Rights, provenance,
  permitted use, retention və attribution təsdiqlənmədən məlumat retrieval-a daxil
  olmamalıdır.
- Coding cavablarında mümkün olduqda sandboxed execution əsas doğrulama olmalıdır;
  LLM tək correctness oracle olmamalıdır.
- Azərbaycan ilkin/home market-dir; Azərbaycan və İngilis dilləri first-class launch
  dilləridir. Privacy və source-rights modeli buna baxmayaraq qlobal və
  jurisdiction-aware saxlanır.
- Employer-facing istifadə scope xaricindədir və ayrıca legal/privacy/product-risk
  assessment tələb edir.

Bu guardrail-lər [development roadmap](development-roadmap.md) sənədində sabitlənib.

## 4. Seçilmiş ümumi arxitektura

### 4.1 Modular monolith

İlkin mərhələlər üçün modular monolith və ayrıca işləyə bilən worker-lər seçilib.
Səbəb erkən mərhələdə naməlum scale üçün microservice mürəkkəbliyi yaratmadan,
domain sərhədlərini aydın saxlamaqdır.

Hazırda fiziki olaraq bir Python package və bir PostgreSQL cluster istifadə olunur,
amma modulların məsuliyyəti ayrıdır:

- `core`: settings, logging, middleware, kriptoqrafiya, secret loading, telemetry və
  reliability contract-ları;
- `api`: health, identity və privacy HTTP contract-ları;
- `persistence`: SQLAlchemy lifecycle, migration contract, outbox və audit;
- `identity`: access-token verification, principal, scope və account mapping;
- `privacy`: policy routing, consent, processing/retention qaydaları və deletion;
- `file_security`: byte validation, object storage, scanner və file lifecycle;
- `reliability`: staging baseline evidence modeli və CLI evaluator.

Gələcək profiling, knowledge, retrieval, blueprint, session, interviewer, evaluator,
skill-state və reporting modulları hələ yaradılmayıb.

### 4.2 Deterministic orchestration prinsipi

Gələcək interview session-da state transition, time/question budget, retry və
idempotency üzərində yeganə authority deterministic orchestrator olacaq. LLM modulları
yalnız schema ilə yoxlanmış təklif və ya evaluation qaytara biləcək; session state-i
özbaşına dəyişə bilməyəcək.

Bu qərar [ADR 0001](adr/0001-modular-monolith-and-deterministic-orchestration.md)
ilə rəsmiləşdirilib.

### 4.3 Texnologiya bazası

- Python `>=3.12,<3.13`
- FastAPI və Uvicorn
- Pydantic Settings
- PostgreSQL 17
- SQLAlchemy 2 async və psycopg 3
- Alembic
- PyJWT və `cryptography`
- Boto3 ilə S3-compatible object-store adapter-i
- OpenTelemetry SDK və OTLP/HTTP protobuf exporter-ləri
- `uv` və commit edilən `uv.lock`
- pytest, branch coverage, strict mypy və Ruff
- Multi-stage Alpine OCI image

Əsas CLI-lər:

```text
ai-interviewer-api
ai-interviewer-migrate
ai-interviewer-baseline
```

## 5. Mərhələ-mərhələ görülmüş iş

## 5.1 Phase 0A — Engineering foundation

**Tarix:** 23 avqust 2026  
**Asılılıq:** yoxdur  
**Məqsəd:** product logic yazılmazdan əvvəl təhlükəsiz, reproducible və test edilən
runtime/repository bazası yaratmaq.

### Görülən iş

- `src/ai_interviewer` altında install edilən typed Python package quruldu.
- Python 3.12, FastAPI application factory və Uvicorn runner yaradıldı.
- `uv.lock` ilə reproducible dependency həlli quruldu.
- Environment dəyişənlərini typed şəkildə oxuyan, hosted mühitdə unsafe setting-ləri
  rədd edən `Settings` modeli yaradıldı.
- `GET /api/v1/health/live` process liveness contract-ı yaradıldı.
- `GET /api/v1/health/ready` dependency-aware readiness contract-ı yaradıldı.
- Client request ID yalnız canonical UUID olduqda qəbul edilir; digər dəyər server
  tərəfindən yenisi ilə əvəzlənir.
- Structured JSON request və lifecycle logging yaradıldı.
- Daxili exception detalları client-ə açılmayan problem response-lar tətbiq olundu.
- Validation error-ları sanitise edilərək sabit HTTP problem formatına çevrildi.
- Trusted-host middleware və təhlükəsizlik response header-ləri əlavə edildi.
- Production üçün HSTS və docs/debug/host fail-closed qaydaları qoyuldu.
- CI daxilində lock, lint, format, type, test, coverage, dependency audit, image build və
  scan gate-ləri yaradıldı.
- Multi-stage Alpine container yaradıldı; build toolchain runtime layer-dən çıxarıldı
  və process numeric `10001:10001` ilə işlədildi.
- Dependency update automation, roadmap, ilkin ADR-lər və threat model yaradıldı.

### Review zamanı tapılıb düzəldilən problemlər

1. İlk verification script native command uğursuz olduqda davam edirdi; fail-fast
   davranışına keçirildi.
2. Format pozuntuları, `py.typed` çatışmazlığı və yanlış test düzəldildi.
3. İlk dev dependency dəstində məlum pytest zəifliyi tapıldı; fixed major versiyaya
   yüksəldilib bütün suite yenidən işlədildi.
4. İlk Debian runtime image scan-də `53` high/critical OS finding verdi; image Alpine
   multi-stage olaraq yenidən quruldu və nəticə `0` oldu.

### Exit verification

- `18` test keçdi.
- Branch coverage `97.70%` oldu.
- Strict mypy `10` source faylı üçün keçdi.
- Lock, lint, format və Python vulnerability audit keçdi.
- Container production-mode smoke testdə HTTP 200 readiness verdi.
- Runtime UID/GID `10001:10001` faktiki yoxlandı.
- Image ölçüsü həmin gate-də `30,649,033` byte idi.

Ətraflı sübut: [Phase 0A completion record](status/phase-0a-engineering-foundation.md).

## 5.2 Phase 0B — Persistence və transaction foundation

**Tarix:** 23 avqust 2026  
**Asılılıq:** 0A  
**Məqsəd:** hər hansı namizəd datasından əvvəl durable state, transaction və migration
qaydalarını qurmaq.

### Görülən iş

- Digest-pinned PostgreSQL `17.11` local environment yaradıldı.
- PostgreSQL container non-root, read-only root filesystem, bütün capability-lər
  drop edilmiş və `no-new-privileges` ilə sərtləşdirildi.
- Database URL, TLS mode, pool size/overflow, pool timeout/recycle, connect timeout,
  statement timeout və readiness timeout typed settings oldu.
- SQLAlchemy 2 async engine/session lifecycle quruldu.
- Explicit atomic transaction context yaradıldı.
- Alembic naming convention və migration graph quruldu.
- Empty database upgrade, downgrade/upgrade rehearsal və model/migration drift check
  mexanizmi yaradıldı.
- Application-generated UUIDv7 ID convention-u tətbiq edildi.
- Bütün zamanlar timezone-aware UTC saxlanılır.
- Mutable aggregate-lər üçün optimistic concurrency `version` convention-u yaradıldı.
- Future user-owned aggregate-lər üçün non-null owner convention-u müəyyən edildi.
- Transactional outbox yaradıldı:
  - aggregate dəyişikliklə eyni transaction-da enqueue;
  - competing worker-lər üçün `FOR UPDATE SKIP LOCKED`;
  - bounded batch;
  - lease və stale lease recovery;
  - retry metadata;
  - ownership yoxlamalı publish.
- Append-only audit event modeli yaradıldı.
- Database trigger-ləri audit row-larının `UPDATE`, `DELETE` və `TRUNCATE` edilməsini
  rədd edir.
- Audit/outbox operational metadata-sı üçün candidate content və credential key-ləri
  recursive şəkildə bloklayan guard yazıldı.
- Real PostgreSQL integration test infrastrukturu quruldu.
- Ayrı temporary recovery database ilə backup/restore rehearsal script-i yaradıldı.
- Windows async psycopg uyğunluğu üçün API, migration və test runner-ləri düzəldildi.

### İlk migration

`20260823_0001` revision-u aşağıdakı əsas cədvəlləri gətirdi:

- `outbox_events`
- `audit_events`

### Review zamanı düzəldilən problemlər

1. Windows Proactor event loop psycopg ilə uyğun deyildi; uyğun loop selection əlavə
   edildi və regression test yazıldı.
2. Alembic check-constraint adları naming convention-dan iki dəfə keçirdi; resolved
   adlar tətbiq edildi və drift sıfırlandı.
3. Restore script mövcud audit row-u fərz edir və Alpine-da unsupported uzun `rm`
   parametrindən istifadə edirdi; isolated probe və exact cleanup ilə düzəldildi.
4. Official PostgreSQL image-də istifadə edilməyən `gosu` binary-sində yüksək riskli
   Go finding-ləri var idi; derivative image birbaşa UID/GID 70 ilə başladıldı və
   `gosu` çıxarıldı.
5. Cross-platform runner üçün birbaşa testlər əlavə edildi.

### Exit verification

- `47` test real disposable PostgreSQL ilə keçdi.
- Coverage `98.35%` oldu.
- Strict mypy `16` source faylı üçün keçdi.
- Rollback, competing outbox workers, lease retry, stale write və audit immutability
  yoxlandı.
- Restore rehearsal `20260823_0001` revision-da keçdi.
- API və PostgreSQL image scan nəticəsi `0 HIGH/CRITICAL` oldu.

Ətraflı sübut: [Phase 0B completion record](status/phase-0b-persistence-foundation.md)
və [ADR 0003](adr/0003-postgresql-persistence-contract.md).

## 5.3 Phase 0C-A — Identity və access foundation

**Tarix:** 23 avqust 2026  
**Asılılıq:** 0B  
**Məqsəd:** candidate data yaranmazdan əvvəl standards-based authentication və
deny-by-default owner sərhədi yaratmaq.

### Görülən iş

- API OAuth 2.0 resource server kimi quruldu; local password database yaradılmadı.
- Yalnız operator-configured OIDC issuer və exact API audience qəbul edilir.
- ID token access token yerinə qəbul edilmir.
- RFC 9068 JWT access-token contract-ı tətbiq edildi:
  - fixed asymmetric algorithm allowlist;
  - `RS256` interoperability baseline məcburidir;
  - symmetric algorithm və `none` qadağandır;
  - header-də bounded `kid` və exact `at+jwt` type;
  - signature, issuer, audience, `exp`, `iat`, `sub`, `client_id`, `jti` və scope
    validation;
  - bounded token length və maximum token age;
  - clock skew siyasəti.
- JWKS fetch timeout-u, in-process cache və unknown-key refresh davranışı quruldu.
- Auth/JWKS xətaları opaque şəkildə fail closed edir.
- Bearer error-ları RFC-compatible `WWW-Authenticate` header-i qaytarır.
- Authorization scope-first, owner-second qaydasına əsaslanır.
- Cross-owner lookup resource enumeration-ı azaltmaq üçün `not found` kimi davranır.
- İlk uğurlu login-də issuer/subject cütlüyü local opaque account-a map edilir.
- Concurrent first-login unique constraint və transaction sayəsində bir account və bir
  audit event yaradır.
- Local account yalnız UUIDv7 ID, issuer, subject, status, version və UTC timestamp
  saxlayır; email, ad, avatar, token və bütün claim-lər saxlanmır.
- Disabled və deletion-pending account-lar fail closed edir.
- `GET /api/v1/identity/me` yalnız `profile:read` scope ilə opaque account ID qaytarır.

### Migration

`20260823_0002` revision-u `accounts` cədvəlini əlavə etdi.

### Review zamanı düzəldilən problemlər

1. `client_id` və `jti` əvvəl mandatory deyildi; tələb və invalid-token testləri əlavə
   edildi.
2. `scope` claim-i list qəbul edirdi; standard space-delimited string məcburi edildi.
   Provider `scp` list-i ayrıca bounded formatda saxlanıldı və ambiguous claims rədd
   edildi.
3. Algorithm configuration `RS256`-nı buraxa bilirdi; indi daxil etməlidir və token
   header-i algorithm seçim mənbəyi deyil.
4. Verifier/network exception detail leakage sabit problem response-la bağlandı.
5. Restore rehearsal account schema və constraint-lərlə genişləndirildi.

### Exit verification

- `93` test keçdi.
- Coverage `99.02%` oldu.
- Strict mypy `23` source faylı üçün keçdi.
- Valid və adversarial token ssenariləri, concurrent account provisioning, disabled
  account, insufficient scope və cross-owner denial yoxlandı.
- Migration və restore `20260823_0002` revision-da keçdi.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.

Ətraflı sübut: [Phase 0C-A completion record](status/phase-0c-a-identity-access-foundation.md)
və [ADR 0004](adr/0004-oidc-resource-server-and-local-identity.md).

## 5.4 Phase 0C-B — Privacy lifecycle

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0C-A və privacy/legal policy sərhədləri  
**Məqsəd:** consent, purpose limitation, retention, data-subject request və deletion
prosesini ölkə qanununu kodda uydurmadan qurmaq.

### Jurisdiction və policy routing

- ISO country/subdivision input-dan ordered policy layer-lərinə gedən kiçik
  `JurisdictionPolicyRegistry` yaradıldı.
- Azərbaycan, EU/EEA, UK, US federal, Kanada, Türkiyə, Braziliya, Hindistan,
  Avstraliya, Sinqapur və BƏƏ üçün routing modulları var.
- Bu modullar hüquqi uyğunluq iddiası deyil; hamısı legal review tələb edən routing
  metadata-sıdır.
- Global fail-closed baseline həmişə son layer-dir.
- Migration heç bir policy və consent text-i seed etmir.
- Yalnız hüquqi baxış statusu `approved`, lifecycle statusu `active` olan policy
  production processing üçün seçilə bilər.
- Privacy profile residence country/subdivision, ordered jurisdiction/version snapshot,
  storage region, 18+ attestation və seçilmiş policy version saxlayır.

### Consent və processing decision

- Consent notice policy version, notice key/version, purpose, data category, document
  URI və content SHA-256 ilə immutable meaning daşıyır.
- Grant idempotentdir; eyni notice üçün birdən çox aktiv consent yaranmır.
- Withdrawal ayrıca timestamp ilə saxlanır və consent-based processing-i dərhal
  dayandırır.
- Processing rule policy/jurisdiction/category/purpose üzrə narrow allow/deny qərarıdır.
- Missing rule fail closed edir.
- Legal basis və consent requirement qərarın içində saxlanır.

### Retention

- Retention rule category və purpose üzrə duration/action (`delete` və ya `anonymize`)
  müəyyən edir.
- Qərar istifadə anında lifecycle record-a snapshot edilir; sonrakı policy dəyişikliyi
  keçmiş retention evidence-ı səssiz dəyişmir.
- Expiry sweeper delete və anonymize nəticələrini tətbiq edir.
- Privacy audit evidence `retain_until` vaxtına qədər database səviyyəsində immutable
  saxlanır.

### Access, export və deletion request-ləri

- Authenticated self-service `access`, `export` və `deletion` request lifecycle quruldu.
- Hər request növü ayrıca OAuth scope tələb edir.
- `Idempotency-Key` plaintext saxlanmır; hash olunur.
- Request status-ları `received`, `verified`, `processing` və terminal state-lərdir.
- Phase 0C-B machine-readable export bundle yalnız həmin mərhələdə mövcud məlumatı
  qaytarır.
- Deletion əvvəl account access-i bağlayır, local data-nı silir/unlink edir, external
  processor task-lərini yaradır və yalnız bütün work tamamlananda request-i bağlayır.

### Processor və backup deletion

- Processor inventory vendor identity-ni approved activity-dən ayırır.
- Activity category, purpose, policy, processing/storage region, cross-border status,
  transfer mechanism, deletion method və SLA metadata-sı saxlayır.
- Vendor locator Phase 0C-C-də AES-GCM ilə şifrələnəcək şəkildə contract-a salınıb.
- Processor deletion task-lərində lease, bounded exponential retry, escalation və
  manual requeue var.
- Outbox external deletion connector-a durable handoff təmin edir.
- Deletion üçün raw issuer/subject əvəzinə keyed subject fingerprint və cutoff marker
  yaradılır.
- Backup restore isolated qalır; backup tarixindən sonrakı signed deletion manifest-lər
  replay edilmədən readiness verilmir.
- Replay account ID, keyed fingerprint və creation time/cutoff uyğunluğunu yoxlayır,
  real post-deletion re-registration-ı səhvən silmir.

### Migration və API

`20260824_0003` revision-u privacy cədvəllərini əlavə etdi. Aşağıdakı endpoint-lər
yaradıldı:

- `PUT /api/v1/privacy/profile`
- `GET /api/v1/privacy/consents`
- `POST /api/v1/privacy/consents/{consent_notice_id}`
- `DELETE /api/v1/privacy/consents/{consent_record_id}`
- `POST /api/v1/privacy/requests`
- `GET /api/v1/privacy/requests/{privacy_request_id}`

### Exit verification

- `125` test keçdi.
- Coverage `95.38%` oldu.
- Strict mypy `33` source faylı üçün keçdi.
- Real PostgreSQL-də consent withdrawal, processing denial, idempotency, deletion,
  restore replay, processor retry/escalation/outbox və retention testləri keçdi.
- Restore rehearsal `20260824_0003` revision-da `8.08s` ərzində keçdi.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.

### Hüquqi sərhəd

Bu implementasiya heç bir ölkə üçün hüquqi uyğunluq təsdiqi vermir. Deployment-dan
əvvəl real legal reviewer policy, processing, retention, consent və processor activity
record-larını publish etməlidir. Açıq suallar
[legal review register](legal/phase-0c-b-unresolved-legal-questions.md)-də saxlanır.

Ətraflı sübut: [Phase 0C-B completion record](status/phase-0c-b-privacy-lifecycle.md)
və [ADR 0005](adr/0005-jurisdiction-aware-privacy-lifecycle.md).

## 5.5 Phase 0C-C — File və secret security

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0C-A identity, 0C-B data classification və retention  
**Məqsəd:** public upload API-dən əvvəl təhlükəsiz secret, encrypted storage,
quarantine, scan, release və deletion contract-ı yaratmaq.

### Secret delivery və kriptoqrafiya

- Hosted mühitdə database URL və privacy keyring absolute orchestrator-mounted secret
  fayllarından yalnız startup zamanı oxunur.
- Secret file regular file, UTF-8, maximum `65,536` byte, whitespace/NUL və POSIX
  permission qaydaları ilə yoxlanır.
- Xəta mesajı secret value və path detail-i sızdırmır.
- Versioned JSON application keyring yaradıldı.
- Purpose-lər ayrı 256-bit key-lər istifadə edir:
  - `subject_hmac`;
  - `field_encryption`;
  - `manifest_hmac`.
- Hər purpose üçün active key ID var; rotation zamanı referenced köhnə key-lər verify
  və decrypt üçün qala bilir.
- Processor locator AES-256-GCM ilə şifrələnir.
- Additional authenticated data ciphertext-i account və processor ID-yə bağlayır.
- Keyed digest plaintext locator saxlamadan idempotency təmin edir.
- Deletion manifest canonical JSON və versioned HMAC ilə imzalanır.

### Object storage adapter-i

- Production üçün S3-compatible private bucket adapter-i yaradıldı.
- Readiness aşağıdakıları yoxlayır:
  - versioning aktivdir;
  - dörd public-access block aktivdir;
  - default SSE-KMS aktivdir.
- Hər quarantine upload approved KMS key və SHA-256 checksum tələb edir.
- Provider-dən version ID alınması məcburidir.
- Download zamanı byte length, SSE-KMS metadata və application SHA-256 yenidən
  yoxlanır.
- Clean promotion version-pinned server-side copy ilə `quarantine/` opaque key-dən
  `released/` opaque key-ə edilir.
- Delete əməliyyatı yalnız delete marker yaratmır; exact object key üçün bütün version
  və delete marker-ləri bütün səhifələr üzrə enumerate edib ayrıca silir.
- Partial provider delete error tamamlanmış deletion kimi qəbul edilmir.

### Fayl validation-u

HTTP filename və content-type etibarlı sayılmır; byte səviyyəsində yoxlama edilir.
Hazır contract yalnız bounded PDF, DOCX və UTF-8 text üçündür.

PDF üçün:

- byte signature;
- ölçü limiti;
- düzgün termination;
- bounded struktur yoxlamaları.

DOCX/ZIP üçün:

- entry count və expanded size limiti;
- path traversal qadağası;
- duplicate entry qadağası;
- encrypted member qadağası;
- executable/script/active content qadağası;
- required DOCX part-lar;
- CRC, compression ratio və malformed archive yoxlamaları.

Text üçün:

- strict UTF-8 decode;
- bounded byte ölçüsü;
- binary/uyğunsuz content fail-closed davranışı.

### Malware scanning

- Bounded ClamAV `INSTREAM` adapter-i yaradıldı.
- Production yalnız isolated clamd sidecar-a absolute local Unix socket qəbul edir.
- Development üçün bounded TCP seçimi var.
- Connect/read timeout, maximum stream bytes və maximum response ölçüsü tətbiq edilir.
- Yalnız exact clean/infected/error verdict parse olunur.
- Scanner engine version, signature version və signature timestamp evidence kimi
  saxlanır.
- Signature freshness maksimum yaşdan böyükdürsə readiness və release fail closed edir.
- Malware adı plaintext saxlanmır; bounded signature string-in SHA-256 digest-i qalır.

### File lifecycle

Authoritative state machine:

```text
upload_pending -> quarantined -> clean -> released
                        |          |
                        v          v
                   scan_failed  deletion_pending
```

- Processing authorization və retention resolution storage-dan əvvəl edilir.
- Exactly one active, approved, scan-required parser release policy tələb olunur.
- Infected və scan-error content parser-ə heç vaxt verilmir.
- Parser read zamanı ownership, released object key/version/hash, policy status,
  approval time, exact adapter/version və isolation profile yenidən yoxlanır.
- Actual parser bu mərhələdə yoxdur; Phase 1A exact policy-yə uyğun no-network,
  read-only və resource-bounded parser gətirməlidir.
- Upload failure, infection, retention expiry, privacy deletion və restore replay
  durable file deletion task yaradır.
- Privacy request file deletion tamamlanmadan completed ola bilmir.
- File task-lərində lease, retry, escalation və manual requeue var.

### Migration

`20260824_0004` revision-u aşağıdakıları əlavə etdi:

- `parser_release_policies`
- `file_assets`
- `file_scan_attempts`
- `file_deletion_tasks`

### Review zamanı düzəldilən əsas məsələ

İlkin image scan `cryptography 46.0.7` paketində üç HIGH finding göstərdi. Lock
`cryptography 50.0.0`-a yüksəldildi, bütün testlər yenidən işlədildi və rebuilt image
təmiz scan verdi.

### Exit verification

- `210` test keçdi; həmin gate-də `24` real PostgreSQL integration testi var idi.
- Coverage `95.34%` oldu.
- Strict mypy `41` source faylı üçün keçdi.
- Secret/keyring, PDF/DOCX/text, S3 version/pagination/partial-delete, ClamAV protocol,
  lifecycle, privacy deletion və manifest tamper ssenariləri yoxlandı.
- Restore rehearsal `20` required table, `18` index, `29` constraint və `2` audit
  trigger-i doğruladı.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.

Ətraflı sübut: [Phase 0C-C completion record](status/phase-0c-c-file-secret-security.md),
[ADR 0006](adr/0006-file-secret-security.md) və
[secure file runbook](runbooks/secure-file-operations.md).

## 5.6 Phase 0D-A — Release və deployment foundation

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0A–0C  
**Məqsəd:** eyni artifact-i təhlükəsiz şəkildə mühitlər arasında promote etmək və
schema/app uyğunluğunu fail closed yoxlamaq.

### Görülən iş

- Staging və production üçün eyni hosted safety validator tətbiq edildi.
- Hosted runtime non-default release ID və full 40-character source revision tələb
  edir.
- Release ID/revision settings-də freeze olunur və yalnız safe lifecycle log-larında
  istifadə edilir.
- OCI image version, revision və created label-ləri daşıyır.
- Application və onun exact Alembic graph-ı eyni immutable image-ə daxil edilir.
- `ai-interviewer-migrate` ayrıca, dar release entrypoint-dir:
  - `check-artifact` database olmadan migration artifact-i yoxlayır;
  - `upgrade` yalnız forward migration edir;
  - release CLI-də downgrade əmri yoxdur.
- Migration job app secret-lərini tələb etmir; yalnız release/database coordinates
  oxuyur.
- Alembic başlamazdan əvvəl graph-da exactly one head olduğu və compiled API schema
  revision-u ilə eyni olduğu yoxlanır.
- Stable PostgreSQL session advisory lock concurrent migration job-larını serial edir.
- Lock acquisition bounded timeout ilədir.
- Alembic lock-u saxlayan eyni connection-dan istifadə edir.
- Migration sonunda `alembic_version` exact compiled revision-a bərabər olmalıdır.
- Failure log yalnız exception type və bounded metadata verir; DSN, SQL və exception
  text vermir.
- API readiness database connection-la yanaşı exact schema compatibility tələb edir.
- CI third-party action-ları full commit SHA ilə pin edilir.
- CI image labels, embedded schema, numeric non-root user, vulnerability scan və
  CycloneDX SBOM retention-u yoxlayır.
- Release ordering və forward-fix/compatibility rollback qaydası yazıldı.

Release ardıcıllığı:

```text
build once
  -> test və scan
  -> immutable digest
  -> staging migration
  -> staging rollout/readiness
  -> production migration
  -> production rollout/readiness
```

### Exit verification

- `228` test keçdi; `27` real PostgreSQL integration testi idi.
- Coverage `95.15%` oldu.
- Strict mypy `43` source faylı üçün keçdi.
- Advisory-lock exclusion/timeout və mismatched schema readiness testləri keçdi.
- Image-owned migration və read-only hardened API smoke test keçdi.
- CycloneDX rehearsal SBOM-u həmin gate-də `80` komponentdən ibarət idi.
- Restore rehearsal bütün `13` tracked table count-u və audit trigger-lərini yoxladı.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.

Provider seçilmədiyi üçün Kubernetes/ECS/IAM/network/bucket/KMS manifest-ləri
uydurulmayıb.

Ətraflı sübut: [Phase 0D-A completion record](status/phase-0d-a-release-deployment-foundation.md),
[ADR 0007](adr/0007-release-and-migration-contract.md) və
[release runbook](runbooks/release-and-rollback.md).

## 5.7 Phase 0D-B — Telemetry baseline

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0D-A  
**Məqsəd:** xarici istifadəçidən əvvəl failure-ləri diaqnoz edilə bilən etmək, amma
telemetry-yə həssas payload sızdırmamaq.

### Görülən iş

- Vendor-neutral OpenTelemetry metric və trace provider-ləri yaradıldı.
- OTLP/HTTP protobuf export fixed `/v1/metrics` və `/v1/traces` endpoint-lərinə edilir.
- Hosted non-loopback collector HTTPS olmalıdır; loopback sidecar/agent üçün HTTP
  mümkündür.
- Credential-bearing collector endpoint configuration qadağandır.
- Parent-based ratio trace sampling tətbiq edildi.
- Bounded span queue, batch, schedule delay, metric interval və export timeout settings
  yaradıldı.
- Exporter network xətası application request-i, readiness-i və durable worker işini
  sındırmır.
- Resource metadata aşağıdakılarla məhduddur:
  - service name;
  - environment;
  - release ID;
  - source revision;
  - random process instance ID.
- W3C `traceparent` və `tracestate` propagation var.
- Baggage, authorization, request body və arbitrary request metadata span-a daşınmır.

### HTTP telemetry

- Stable `http.server.request.duration` histogram-u explicit bucket-lərlə emit olunur.
- `http.server.active_requests` concurrency ölçür.
- Metric attribute-ları yalnız bounded method, scheme, route template, status və error
  type-dır.
- Raw path, query, host, client address, headers, body və ID-lər qadağandır.

Histogram bucket-ləri saniyə ilə:

```text
0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25,
0.5, 0.75, 1, 2.5, 5, 7.5, 10, +Inf
```

### Log təhlükəsizliyi

- Application log-u stdout-a hər sətirdə bir JSON object kimi yazılır.
- Yalnız application-owned constant message-lər saxlanır.
- Third-party və parameterized log message-lər suppress olunur.
- Credential, token, URL və email pattern-ləri redaktə edən test edilmiş filter var.
- Exception yalnız type və bounded frame basename/function/line verir.
- Exception text, local variable və full path loglanmır.
- Valid trace/span ID və canonical UUID request ID correlation təmin edir, amma metric
  label olmur.

### Dependency və operational telemetry

Yaradılan əsas instrument-lər:

- `ai_interviewer.dependency.operation.duration`
- `ai_interviewer.database.pool.connections`
- `ai_interviewer.database.pool.limit`
- `ai_interviewer.file.scan.attempts`
- `ai_interviewer.deletion.task.transitions`
- `ai_interviewer.deletion.queue.tasks`
- `ai_interviewer.deletion.queue.oldest_age`

Object store, scanner, database və deletion operation-ları payload-blind decorator-lə
instrument edilib. Durable deletion queue snapshot-ı PostgreSQL database time-dan
hesablanır və owner/task/object ID çıxarmır.

### Exit verification

- `248` test keçdi; integration suite `28` testə çatdı.
- Coverage `95.27%` oldu.
- Strict mypy `46` source faylı üçün keçdi.
- Remote W3C parent continuity, route/method normalization, payload exclusion,
  trace/log correlation, exporter isolation və real PostgreSQL snapshot testləri keçdi.
- Local OTLP stub real protobuf metric və trace request-i aldı.
- Hardened release image smoke və query-string canary absence yoxlaması keçdi.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.
- CycloneDX rehearsal SBOM-u `91` komponent oldu.

Ətraflı sübut: [Phase 0D-B completion record](status/phase-0d-b-telemetry-baseline.md),
[ADR 0008](adr/0008-payload-blind-opentelemetry.md),
[telemetry runbook](runbooks/telemetry-operations.md) və
[dashboard specification](operations/telemetry-dashboard-spec.md).

## 5.8 Phase 0D-C-A — SLI measurement contract və integrity

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0D-B  
**Məqsəd:** real data olmadan rəqəm uydurmaq əvəzinə əvvəlcə nəyi və necə ölçdüyümüzü
dəqiq sabitləmək.

### Route population-ları

`ai_interviewer.request.population` yalnız üç bounded dəyər alır:

- `product`: review edilmiş identity/privacy API route template-ləri;
- `operations`: liveness/readiness;
- `other`: docs, unmatched və hələ review edilməmiş route-lar.

Yeni və unknown route default olaraq `other` olur; product SLI-ni süni yaxşılaşdıra
bilməz. OpenAPI route-ları ilə code-owned population set-in eyni qalmasını regression
test qoruyur.

### Availability candidate

İlkin server-side availability göstəricisi occurrence count əsaslıdır:

```text
total = population=product olan bütün tamamlanmış request-lər
bad   = HTTP 500–599
good  = total - bad
availability = good / total
```

- `4xx` availability üçün good sayılır, amma ayrıca göstərilir.
- `total = 0` olduqda nəticə `no data`-dır, `100%` deyil.
- Health request-ləri denominator-a daxil deyil.
- Bu yalnız indiki identity/privacy API üçün server-side proxy-dir; interview journey
  SLO-su deyil.

### Latency və diagnostic indicator-lar

- Latency eyni product population histogram-u üzərində p50/p95/p99 distribution kimi
  ölçülür.
- User-relevant threshold hələ seçilmədiyi üçün numeric latency SLO yaradılmayıb.
- Dependency operation success, scan execution, deletion work, snapshot integrity və
  database pool saturation diagnostic-dir; product availability error budget-i deyil.

### Measurement freshness

Əlavə instrument-lər:

- `ai_interviewer.operational.snapshot.attempts`
- `ai_interviewer.operational.snapshot.last_success_age`

İlk uğurlu snapshot-dan əvvəl age series mövcud deyil. Sonrakı snapshot fail etdikdə
köhnə queue gauge-lərinin stale olduğu görünür.

### 28 günlük gate

Objective proposal yalnız aşağıdakılardan sonra review edilə bilər:

- continuous 28 UTC day staging window;
- synthetic-only traffic;
- exact environment/service/release cohort;
- total/good/5xx/4xx counts;
- exact histogram bucket counts;
- gap, restart, counter reset, deployment və collector issue evidence;
- per-route və aggregate view;
- low traffic disclosure;
- sensitive canary absence və cardinality review;
- product, engineering və operations şəxslərinin adlı təsdiqi.

### Exit verification

- `250` test keçdi; `28` real PostgreSQL integration testi.
- Coverage `95.31%` oldu.
- Strict mypy `47` source faylı üçün keçdi.
- Unknown-route fail-closed classification, exact route sync, snapshot error/no-data/
  recovery və bounded attribute testləri keçdi.
- Image migration/readiness smoke, security scan və `91`-component SBOM keçdi.

Ətraflı sübut: [Phase 0D-C-A completion record](status/phase-0d-c-a-sli-measurement.md),
[ADR 0009](adr/0009-measure-before-objective.md) və
[SLI contract](reliability/sli-measurement-contract.md).

## 5.9 Phase 0D-C-B1 — Baseline evidence tooling

**Tarix:** 24 avqust 2026  
**Asılılıq:** 0D-C-A  
**Məqsəd:** gələcək monitoring backend export-unu provider-neutral, payload-free və
fail-closed şəkildə yoxlayan release-owned alət yaratmaq.

### Strict evidence modeli

Pydantic modelləri `strict`, `frozen` və `extra=forbid` qaydası ilə yaradılıb. Input:

- schema version `1`;
- contract version `0d-c-a-v1`;
- service exact `ai-interviewer-api`;
- environment exact `staging`;
- `synthetic_only=true`;
- exact 28 ordered, unique, contiguous UTC date;
- exclusive window end;
- product route set-in SHA-256 digest-i;
- backend/collector bounded name və version-u;
- delta və ya cumulative temporality;
- export və monitor interval-ları;
- query və raw export SHA-256 digest-ləri;
- unique immutable release ID və full lowercase 40-char revision cohort-ları;
- gündəlik eligible/5xx/4xx count-ları;
- all və non-5xx fixed histogram bucket count-ları;
- gap, canary, unexpected attribute, snapshot, restart, reset və deployment count-ları
  qəbul edir.

Schema sərbəst text, path, URL, trace, log, request event, user/file/task ID, SQL,
object key, exception text, CV/JD və credential field qəbul etmir.

### Cross-field validation

- `server_error_requests <= eligible_requests` olmalıdır.
- `client_error_requests` non-5xx count-u keçə bilməz.
- All-request histogram count-u eligible request count-u ilə eyni olmalıdır.
- Non-5xx histogram count-u good request count-u ilə eyni olmalıdır.
- Snapshot success yoxdursa max age olmamalıdır.
- Snapshot success varsa max age mütləq olmalıdır.
- Window exact 28 gün və day-lər contiguous olmalıdır.
- Release cohort duplicate ola bilməz.
- Histogram runtime-la ortaq exact bucket contract istifadə edir.

### Deterministic hesablamalar

Evaluator aşağıdakı safe summary-ni yaradır:

- total eligible request;
- good request;
- server error və client error count;
- availability ratio və no-data state;
- average/min/max daily volume;
- traffic olmayan gün sayı;
- all və non-5xx p50/p95/p99 upper-bucket estimate;
- telemetry gap;
- snapshot success/error və maximum age;
- restart, reset və deployment count.

Quantile ən böyük finite bucket-dən kənara düşürsə alət latency uydurmur:

```json
{"upper_bound_seconds": null, "overflow": true}
```

### Review eligibility

Bu reason-lardan hər hansı biri varsa status `incomplete` olur:

- `no_eligible_requests`
- `operational_snapshot_incomplete`
- `route_contract_mismatch`
- `sensitive_canary_detected`
- `telemetry_gap`
- `unexpected_metric_attributes`

`eligible_for_review` SLO approval demək deyil; yalnız input-un human review üçün
struktur baxımından yetərli olduğunu bildirir.

### CLI contract

```powershell
uv run ai-interviewer-baseline schema
uv run ai-interviewer-baseline evaluate <evidence.json>
```

Exit code-lar:

- `0`: valid və human review üçün eligible;
- `2`: unreadable, oversized və ya schema-invalid input;
- `3`: valid, amma incomplete evidence.

Input maximum `2 MiB`-dir. Error output yalnız fixed `status` və exception type verir;
path, validation detail və content göstərmir.

Real-looking fake evidence faylı qəsdən repository-yə əlavə edilməyib.

### Exit verification

- Suite `262` testə çatdı; `28` real PostgreSQL integration testi.
- Branch coverage `95.55%`; yeni baseline modulu `99%` branch coverage.
- Strict mypy `50` source faylı üçün keçdi.
- Valid aggregation, exact math, quantile, no-data, bütün eligibility reason-ları,
  overflow, 28-day structure, relationship-lər, extra field rejection, bounded read,
  safe CLI error və exit class-lar test edildi.
- Release image-dən extra-forbid JSON schema uğurla çıxarıldı.
- `ai-interviewer-platform:phase0d-c-b1` local Linux/amd64 manifest-i
  `sha256:37b2286b5c3dcfdcbb24808c244292daa6aca649a433043e681b4d9b4c1e4bf6`
  oldu.
- Image-owned migration/readiness smoke hardened runtime ilə keçdi.
- API/PostgreSQL scan nəticəsi `0 HIGH/CRITICAL` oldu.
- CycloneDX rehearsal SBOM `91` komponent oldu.

Ətraflı sübut:
[Phase 0D-C-B1 completion record](status/phase-0d-c-b1-baseline-evidence-tooling.md)
və [evidence format](reliability/baseline-evidence-format.md).

## 5.10 Phase 1A-A — Preparation target context

**Məqsəd:** CV/JD document lifecycle-na keçməzdən əvvəl namizədin hansı şirkət,
rol, seniority, ölkə/ofis, müsahibə round-u və dildə hazırlaşdığını owner-bound,
privacy-authorized aggregate kimi saxlamaq.

Bu hissə qəsdən yalnız mətn context-idir. Document bytes, upload/paste, parser,
extracted text və model invocation bu gate-ə daxil deyil.

### Model və invariant-lər

- `candidate_preparations` cədvəli owner FK, UUIDv7 ID, UTC timestamps və optimistic
  `version` daşıyır.
- Role family, seniority, interview round, AZ/EN language və `draft/archived` status
  controlled code-lardır. `other` seçimi yalnız ayrıca, bounded fallback text ilə
  birlikdə etibarlıdır.
- User text NFKC-normalize edilir, trim olunur, uzunluğu məhduddur və Unicode
  control/format/surrogate kateqoriyalarını rədd edir. Ölkə kodu exact iki ASCII
  hərfidir və uppercase saxlanır.
- Hər record exact privacy policy, jurisdiction, legal basis, retention rule/action
  və `retain_until` snapshot-ı saxlayır. Bu category üçün yalnız `delete` action qəbul
  olunur; missing/deny/anonymize qərarları fail closed edir.
- Raw `Idempotency-Key` saxlanmır; owner-scoped SHA-256 digest və unique constraint
  duplicate create-i transaction daxilində idarə edir. Eyni key + fərqli normalized
  input conflict verir.

### Service və API davranışı

- Create, bounded UUIDv7 keyset list, owned detail, full replacement və archive
  command-ları ayrı service boundary-dədir.
- Cross-owner və mövcud olmayan resource eyni opaque `404` davranışı verir.
- `PUT` və archive strong quoted positive `If-Match` tələb edir: missing `428`,
  malformed `400`, stale version `412` verir.
- Create yeni record üçün `201`, exact idempotent retry üçün `200` qaytarır; bütün
  detail mutation/read response-larında ETag version verilir.
- Audit və outbox yalnız canonical code/status, opaque resource ID və version saxlayır;
  company, role title, office və fallback text bu kanallara düşmür.

### Privacy lifecycle

- Export schema `phase-1a-a.1` versiyasına keçib və owner-in preparation context-lərini
  daxil edir.
- Account deletion initiation və backup deletion-ledger replay local preparation
  record-larını dərhal silir; bu iş xarici processor/file acknowledgement gözləmir.
- Stored delete-only retention deadline keçəndə bounded retention command record-u
  silir.

### Verification nəticəsi

- Yeni modul üçün unit/API testləri normalization, fallback consistency, scopes,
  header contract-ları, opaque errors və fail-closed service construction-u əhatə edir.
- Real PostgreSQL integration testləri idempotent concurrent-safe create, isolation,
  keyset list, ETag replacement/archive, content-free audit/outbox, privacy
  export/erasure və due retention-u yoxlayır.
- Migration empty database-də işləyib və `alembic check` yeni əməliyyat tapmayıb.
- Bütün suite `282` test, `33` PostgreSQL integration testi və `95.64%` branch-aware
  coverage ilə keçib; strict mypy `54` source faylı üçün təmizdir.

Ətraflı sübut:
[Phase 1A-A completion record](status/phase-1a-a-preparation-target-context.md).

## 5.11 Phase 1A-B — Immutable candidate document versions

**Məqsəd:** hər preparation üçün CV və job description-un stabil logical identity-sini
və sonrakı extraction/evaluation nəticələrinin exact mənbəyə bağlana biləcəyi immutable
version lineage yaratmaq. Bu hissə 0C-C file-security asset contract-ını yenidən
implement etmir; yalnız artıq clean scan-dən keçib released olmuş asset-ə istinad edir.

Public upload/paste, parser execution, extracted text və AI invocation bu gate-ə qəsdən
daxil deyil.

### Model və database invariant-ləri

- `candidate_documents` hər preparation və `cv`/`job_description` tipi üçün maksimum
  bir logical aggregate saxlayır. UUIDv7 identity, owner, latest ordinal, UTC timestamps
  və optimistic aggregate version mövcuddur.
- `candidate_document_versions` exact bir released file asset-ə bağlanır və source kind,
  media type, byte length, SHA-256, parser-release policy, privacy policy, jurisdiction,
  legal basis və delete-only retention snapshot-ını saxlayır.
- Composite foreign key-lər preparation → document → version → file asset boyunca owner
  uyğunluğunu database səviyyəsində məcbur edir. Bir asset yalnız bir document version-a,
  bir ordinal isə yalnız öz document aggregate-inə aid ola bilər.
- PostgreSQL trigger document-version `UPDATE` əməliyyatlarını SQLSTATE `55000` ilə rədd
  edir. Privacy və retention öhdəlikləri üçün explicit `DELETE` mümkündür; immutability
  hüquqi silinməni bloklamaq demək deyil.

### Service, API və lifecycle davranışı

- Internal attach command account → preparation → asset → document lock ardıcıllığı ilə
  işləyir; yalnız active owner, draft preparation, exact owner asset, released object
  metadata, approved parser policy, uyğun purpose/category və cari privacy qərarı qəbul
  edilir.
- Eyni asset-in eyni target-a retry-si idempotentdir. Başqa document/type/source-a reuse
  conflict verir; yeni asset isə aggregate-də növbəti immutable ordinal yaradır.
- Audit/outbox yalnız canonical type/source/media, ordinal və opaque resource/file ID
  saxlayır; company/role text-i, document digest-i, object key və bytes operational
  kanallara yazılmır.
- `GET /preparations/{preparation_id}/documents` və owned detail route-u yalnız metadata
  verir; detail aggregate version-dan strong ETag yaradır. Cross-owner access opaque 404,
  disabled boundary isə 503 qaytarır.
- Privacy export schema `phase-1a-b.1` oldu. Account erasure document lineage-i
  preparation context-dən əvvəl silir ki, explicit deletion count itirilməsin.
- File deletion worker product reference-i file-asset row-u ilə eyni transaction-da
  əvvəlcə azad edir. Son version silinirsə logical document də silinir; qalan lineage
  varsa latest ordinal yenidən hesablanır.

### Migration və verification nəticəsi

- `20260827_0006` revision-u iki document cədvəli, owner-matching composite FK-lər,
  unique/check/index contract-ları və immutable-update trigger-i əlavə etdi.
- Unit/API testləri scope, owned metadata response, ETag, opaque error mapping,
  fail-closed runtime və database access-dən əvvəl code validation-u yoxlayır.
- Real PostgreSQL testləri multi-version append, exact retry, owner isolation, DB trigger,
  unreleased/archived rejection, retention-before-asset-delete və privacy export/deletion
  axınlarını sübut edir.
- Bütün suite `290` test, `37` PostgreSQL integration testi və `95.47%` branch-aware
  coverage ilə keçib; strict mypy `57` source faylı üçün təmizdir.
- Clean migration və `alembic check`, dependency compatibility/audit, backup→restore
  rehearsal, release-image artifact contract və refreshed Trivy DB ilə API/PostgreSQL
  `0 HIGH/CRITICAL` scan nəticəsi keçib.

Ətraflı qərar və sübut:
[ADR 0011](adr/0011-immutable-candidate-document-lineage.md) və
[Phase 1A-B completion record](status/phase-1a-b-immutable-candidate-document-versions.md).

## 5.12 Phase 1A-C — Authenticated upload və paste intake

**Məqsəd:** owner-bound CV/JD bytes və pasted text-i public API-də təhlükəsiz qəbul
etmək, 0C-C quarantine/scan/release lifecycle-dan keçirmək və 1A-B immutable lineage-ə
exact bir dəfə bağlamaq. Proses timeout, scanner/storage xətası və worker dayanmasından
sonra eyni request ilə bərpa olunmalıdır.

Parser, extracted text, PII redaction, user correction və AI invocation bu gate-ə daxil
edilməyib.

### HTTP və validation contract-ı

- Upload və paste raw body qəbul edir; multipart field və filename qəsdən toplanmır.
  Upload yalnız PDF, DOCX və UTF-8 text allowlist-i, paste isə exact UTF-8 `text/plain`
  qəbul edir.
- `Content-Encoding` rədd olunur. `Content-Length` və faktiki stream ayrıca bounded-dir;
  proxy declared length-i ötürməsə də oversized body yaddaşda limitsiz yığılmır.
- Hər mutation `preparation:write` və 8-128 simvolluq `Idempotency-Key` tələb edir.
  Status read `preparation:read` tələb edir və owner/preparation predicate-i ilə opaque
  not-found verir.
- HTTP nəticəsi durable state-ə bağlıdır: yeni completion `201`, completed replay `200`,
  active/retryable state `202 + Retry-After`, rejected input `422`, conflicting key/state
  `409`. Status URI, ETag və `Cache-Control: no-store` verilir.

### Durable saga və database invariant-ləri

- `candidate_document_intakes` raw key əvəzinə owner-scoped SHA-256 saxlayır. Ayrı
  request digest preparation, type, source, normalized media və content digest-i bağlayır;
  eyni key-in fərqli request üçün istifadəsi conflict-dir.
- Saga `processing`, `scan_failed`, `rejected`, `completed` state-lərindən ibarətdir.
  Processing state exact beş dəqiqəlik lease və opaque token tələb edir. Active retry
  pipeline-i ikinci dəfə işə salmır; expired lease yeni token və increment edilmiş attempt
  ilə recover olunur.
- Claim xarici storage-dan əvvəl UUIDv7 asset ID reserve edir. File staging həmin exact
  ID-ni yalnız owner, policy, category/purpose, media, length, digest, parser policy,
  retention və state tam uyğun olduqda resume edir.
- Object-store write xətası köhnə asset-i durable deletion path-ə qoyur və retry-də
  reservation rotate olunur. Scanner/read xətası eyni quarantined asset-i saxlayır.
  Released asset-dən sonra və ya document attach commit-dən sonra xəta baş verirsə retry
  eyni asset-i və mövcud immutable version-u reuse edir; duplicate version yaranmır.
- Database check/unique/composite FK-ləri state/error/completion, lease/token,
  reservation/current asset, preparation owner, delete-only retention, idempotency,
  asset və document-version uniqueness invariant-lərini service-dən kənarda da qoruyur.

### Privacy, deletion və operational metadata

- Export schema `phase-1a-c.1` safe intake metadata əlavə edir. Raw key, request/content
  digest, bytes, filename, object/KMS location, processing token və internal policy ID
  export olunmur.
- Account erasure intake → document lineage → preparation ardıcıllığı ilə gedir. File
  worker asset-i silməzdən əvvəl intake və immutable-version referenslərini eyni
  transaction-da azad edir. Status-only rejected saga due retention ilə silinə bilir.
- Audit/outbox yalnız controlled document/source/status/error, attempt və opaque intake
  ID saxlayır. Candidate content və idempotency key operational kanallara daxil olmur.
- Yeni upload, paste və status route template-ləri product SLI allowlist-inə explicit
  əlavə olunub; body, header, identifier və error detail telemetry attribute deyil.

### Testdə tapılıb düzəldilən problemlər

- Real PostgreSQL update-dən sonra server-generated/expired ORM sahəsi cavab qurularkən
  async implicit I/O yaradırdı. Terminal/claim flush-dan sonra explicit row refresh əlavə
  edildi.
- İlk retry dizaynı bütün internal dependency xətalarında reservation rotate edirdi. Bu,
  document attach commit olub cavab itməsində ikinci asset/version riski yaradırdı.
  Error phase-aware edildi: yalnız pre-stage storage failure rotate edir, downstream
  recovery eyni released asset və idempotent attach nəticəsini istifadə edir.

### Migration və verification nəticəsi

- `20260827_0007` revision-u intake table, üç indeks və bütün saga/owner/privacy/retention
  constraint-lərini əlavə etdi. Clean upgrade və `alembic check` keçdi.
- Real PostgreSQL testləri exact replay/conflict, upload→paste replacement, scanner retry,
  storage rotation, infected/corrupt rejection, worker cancellation/expired lease,
  post-attachment recovery, privacy export/deletion, retention və asset-reference release
  axınlarını yoxladı.
- Bütün suite `318` test, `45` PostgreSQL integration testi və `95.43%` branch-aware
  coverage ilə keçdi; strict mypy `61` source faylı üçün təmizdir.
- Backup→restore rehearsal `0007` revision, tracked row counts, `24` table, `25` selected
  index, `57` critical constraint, audit/document triggers və readiness ilə keçdi.
- Lokal `ai-interviewer-platform:phase1a-c` image contract-i embedded `0007`, baseline
  schema və numeric `10001:10001` runtime identity ilə keçdi. Synthetic rehearsal SHA
  istifadə olunduğu üçün bu image promotable production release deyil.

Ətraflı qərar və sübut:
[ADR 0012](adr/0012-durable-authenticated-document-intake.md) və
[Phase 1A-C completion record](status/phase-1a-c-authenticated-document-intake.md).

## 5.13 Phase 1A-D1 — Encrypted immutable source-text domain

### Məqsəd və sərhəd

Parser kitabxanası və untrusted document execution-u əlavə etməzdən əvvəl extracted
text-in təhlükəsiz, owner-bound və reproducible persistence sərhədi quruldu. Bu alt
mərhələ qəsdən parser işə salmır, HTTP source-text endpoint-i vermir və AI çağırmır.

### Data modeli və kriptoqrafiya

- `candidate_source_texts` exact bir `candidate_document_versions` sətri üçün maksimum
  bir stable aggregate saxlayır. Composite FK owner-in document lineage boyunca eyni
  qalmasını təmin edir.
- `candidate_source_text_versions` append-only revision-lardır. Birinci revision yalnız
  `parser_extraction`, sonrakılar yalnız sequential `user_correction` ola bilər.
- Mətn PostgreSQL-ə plaintext yazılmır. AES-256-GCM ciphertext, 12-byte nonce və exact
  field-encryption key ID saxlanır.
- AAD owner, document/source/version ID-ləri, revision/origin/predecessor, parser policy,
  adapter/version/isolation, count-lar, digest və key ID-ləri bağlayır. Metadata və ya
  ciphertext başqa sətrə köçürülsə decryption fail closed edir.
- Global SHA-256 əvəzinə owner/document kontekstli subject-HMAC və rotation key ID
  saxlanır. Bu exact retry/integrity verir, amma common JD/CV text equality oracle
  yaratmır.

### Processing guard-ləri

- Store zamanı account active, preparation draft və unexpired, target document version
  latest, asset isə exact owner-matched `released` vəziyyətdə olmalıdır.
- Asset media/byte length/SHA-256/parser policy/privacy/jurisdiction/retention snapshot-u
  immutable document version-la yenidən müqayisə edilir.
- Cari purpose authorization eyni privacy policy, jurisdiction, legal basis, retention
  rule və delete-only action qaytarmalıdır.
- Parser policy active və approved olmalı; ID, adapter, version, isolation, media,
  maximum bytes, malware-scan flag, category, purpose və privacy policy tam uyğun
  gəlməlidir.
- Mətn 500,000 character və 2,000,000 UTF-8 byte ilə bounded-dir, yalnız LF newline
  qəbul edir, NUL/CR/Unicode format-control/surrogate-ləri rədd edir. Etibarlı
  multilingual text səssiz normalization olmadan round-trip edir.

### Immutability, retry və lifecycle

- Owner səviyyəsində lock və document-version unique constraint parallel exact retry-ni
  bir result-a endirir. Eyni content/provenance idempotent-dir; fərqli nəticə conflict
  verir və heç nə overwrite etmir.
- DB trigger stable source identity-ni dəyişməyə və source version update-ə icazə
  vermir. Ayrı trigger correction predecessor-in məhz əvvəlki ordinal olduğunu yoxlayır.
- Exact document version account erasure və ya file retention zamanı silinəndə bütün
  encrypted text lineage cascade olunur.
- Encrypted data varkən `0008` downgrade fail closed edir.
- Eyni transaction-da content-free audit və outbox evidence yaranır. Plaintext,
  ciphertext, nonce, HMAC, document digest, object key və count-lar bu metadata-ya
  düşmür.

### Qəsdən növbəti gate-lərə saxlanılanlar

- D2.2: isolated PDF/DOCX/TXT parser worker (D2.1 durable job contract artıq tamamlanıb);
- D3: authenticated owner inspection və immutable correction append API-si;
- D4: extracted-text access export, tam retention/recovery/audit və Phase 1A exit gate.

Ətraflı qərar və sübut:
[ADR 0013](adr/0013-encrypted-immutable-candidate-source-text.md) və
[Phase 1A-D1 completion record](status/phase-1a-d1-encrypted-source-text-domain.md).

## 5.14 Phase 1A-D2.1 — Durable extraction-job contract

### Məqsəd və sərhəd

Encrypted D1 source-text sərhədindən əvvəl untrusted parser üçün durable asynchronous
iş müqaviləsi yaradıldı. Bu alt-mərhələ parser kitabxanası işə salmır, object bytes oxumur
və extracted text yazmır; yalnız exact document version üçün job lifecycle-i qoruyur.

### Job modeli və lease fencing

- `candidate_extraction_jobs` hər exact `candidate_document_versions` sətri üçün bir
  owner-bound job saxlayır. Document/file/policy/privacy/retention snapshot-ları
  immutable-dir və database trigger ilə qorunur.
- `pending -> processing -> retry/succeeded/failed` status-ları state constraint ilə
  lock token, error code, source-text ID və completion timestamp ilə uyğunlaşdırılır.
- Claim `FOR UPDATE SKIP LOCKED`, 5 dəqiqəlik lease, UUID fencing token və maksimum 5
  attempt istifadə edir. Worker ID və lease token olmadan completion/failure qəbul edilmir.
- Yalnız bounded failure taxonomy qəbul olunur. Transient parser/source xətaları capped
  exponential retry alır; unsupported/corrupt/encrypted/empty/policy xətaları automatic
  replay etmir.

### Operational və privacy sərhədi

- Schedule və transition əməliyyatları yalnız opaque ID, parser metadata, status, attempt
  və safe error code-ları audit/outbox-a yazır. Bytes, object key, filename, raw exception
  və source text heç bir operational metadata-ya düşmür.
- Composite owner FK-lər, exact snapshot yoxlamaları və `ON DELETE CASCADE` document
  lineage silinməsi zamanı pending/retry job-ları da təmizləyir.
- Runtime privacy, file-security və application keyring konfiqurasiyası olmadan fail
  closed olur; worker və public route hələ mövcud deyil.

### Verification və növbəti gate

- D2.1 unit tests, Ruff lint/format, strict mypy, Python compile və Alembic offline SQL
  generation keçib. PostgreSQL migration parity, lease concurrency, stale-worker
  fencing və restore rehearsal Docker Desktop əlçatan olduqda yenidən ölçülməlidir.
- Növbəti düzgün hissə `1A-D2.2`-dir: `read_for_parser` üzərindən yalnız exact released
  asset-i oxuyan, no-network/read-only/non-root resource-bounded PDF/DOCX/TXT worker.

Ətraflı qərar və sübut: [ADR 0014](adr/0014-durable-candidate-extraction-jobs.md) və
[Phase 1A-D2.1 completion record](status/phase-1a-d2-1-extraction-job-contract.md).

## 5.15 Phase 1A-D2.2 — Isolated parser worker

### Məqsəd və sərhəd

D2.1-in yaratdığı fenced job müqaviləsi üzərində real parser icrası əlavə edildi:
exact released asset bytes-ı `read_for_parser` sərhədindən oxuyub, no-network və
resource-bounded uşaq prosesdə parse edib, nəticəni D1 encrypted source-text
sərhədindən keçirib D2.1 job-unu bağlamaq. Heç bir yeni cədvəl və ya sütun əlavə
olunmayıb.

### Yeni `extraction_runtime` paketi

- `ai_interviewer.extraction_runtime` `candidate_inputs`-dan tam asılı olmayan yeni
  top-level paketdir. Bu paketin import edilməsi SQLAlchemy, boto3, kriptoqrafiya və ya
  FastAPI-ni yükləmir — isolated uşaq proses yalnız interpreter, `pypdf` və
  `python-docx` yükləyir.
- Bu ayrılma həm performans, həm təhlükəsizlik üçündür: hər spawn zamanı bütün
  `candidate_inputs` paketinin (SQLAlchemy engine, boto3 client class-ları, kriptoqrafiya
  daxil olmaqla) yenidən import edilməsinin qarşısını alır və isolated prosesin real
  attack surface-ini azaldır.

### Adapter-lər

- `isolated-pdf-parser`, `isolated-docx-parser`, `isolated-text-parser` (versiya `1`)
  bytes-dan sanitised Unicode text qaytaran pure funksiyalardır.
- Çıxış D1-in tam content müqaviləsinə (LF newline, control/format/surrogate
  simvolların qadağan olunması, 500,000 simvol limiti) uyğunlaşdırılır.
- Encrypted PDF, invalid UTF-8, corrupt container və boş extracted text closed bir
  error taxonomy-yə (`input_unsupported`, `input_corrupt`, `input_encrypted`,
  `input_empty`, `resource_exceeded`) map olunur.

### İzolyasiya sərhədi

- `run_isolated_extraction` adapter-i `multiprocessing` `spawn` uşaq prosesində
  işlədir — `fork` yox, çünki `spawn` valideyn prosesin açıq socket, database
  connection və thread-lərini uşağa ötürmür.
- Valideyn wall-clock timeout tətbiq edir; gözlənilməz exit `parser_crashed`,
  signal-la öldürülmüş exit (yalnız POSIX) `resource_exceeded` kimi təsnif olunur.
- Uşaq proses adapter kodu işə düşməzdən əvvəl CPU/memory/file-size resource
  limit-lərini aşağı salır (yalnız POSIX; production hədəfi Linux container-dir),
  socket modulunu deaktiv edir və root kimi işləyirsə davam etməkdən imtina edir.
- Process sərhədini keçən nəticə ya sanitised text, ya da bir fixed string code-dur —
  heç vaxt raw exception, traceback və ya qismən content deyil.

### Worker

- `CandidateExtractionWorker` mövcud üç sərhədi (`claim_jobs`, `read_for_parser`,
  `store_parser_extraction`) bir exact claimed job üçün zəncirləyir və nəticəni
  `mark_succeeded`/`mark_failed`-ə cari lease token ilə ötürür.
- Release-boundary xətası `source_unavailable`-a, isolation xətası öz kodu ilə, D1
  persistence-dəki stale-policy conflict-i `policy_unavailable`-a map olunur.
- Worker özü heç vaxt object storage-a sorğu vermir və ya source text-i birbaşa yazmır.

### mypy platform hədəfi

- `[tool.mypy]` konfiqurasiyasına `platform = "linux"` əlavə olundu, çünki production
  hədəfi yalnız Linux container-dir. Bu, `resource` və `os.getuid` kimi POSIX-only
  standard library davranışının Windows-da development zamanı da düzgün yoxlanmasını
  təmin edir.

### Deliberately not implemented

- Worker-i davamlı işlədən supervisor proses və ya CLI hələ yoxdur; `claim_deletion_tasks`
  üçün də hələ belə bir runner olmadığı üçün bu, mövcud presedentə uyğundur.
- Owner-un source text-i görməsi/düzəlişi və product route hələ D3/D4-dür.
- Kernel-səviyyəli sandboxing (seccomp, network namespace, cgroup) tətbiq olunmayıb;
  izolyasiya ayrı `spawn` prosesi, resource limit və deaktiv socket modulu ilə
  təmin olunur. Daha güclü OS-səviyyəli izolyasiya container runtime-ın operational
  qərarıdır, tətbiq kodu qərarı deyil.

### Verification

- `not integration` filtri ilə `324` test keçib, `1`-i (POSIX-only signal-kill
  ssenarisi) Windows-da skip olunub.
- Strict mypy `platform = "linux"` hədəfi ilə `69` source faylı üçün keçir.
- Ruff lint və format yoxlamaları keçib.
- İki yeni integration test (`tests/integration/test_extraction_worker.py`) real
  database, file-security və source-text sərhədləri ilə end-to-end success (text
  document) və end-to-end failure (corrupt synthetic PDF) ssenarilərini yoxlayır.
  Docker Desktop bu handoff zamanı əlçatan olmadığı üçün bunlar hazırda lokal skip
  olunur; D2.1-in özü də eyni PostgreSQL-bağlı boşluğu qeyd etmişdi.
- Yeni `pypdf` və `python-docx` asılılıqları `uv add` ilə lock-landı; heç bir yeni
  Alembic migration tələb olunmadı (schema revision `20260828_0009` olaraq qalır).

### Next part

Phase 1A-D3 (owner inspection və correction) bu müqavilə qəbul olunduqdan sonra
başlaya bilər: authenticated owner-scoped source-text oxunuşu, safe display/download
müqaviləsi və optimistic/idempotent immutable correction append. Owner-visible source
text hazır olmadan heç bir AI processing başlaya bilməz.

Ətraflı qərar və sübut: [ADR 0015](adr/0015-isolated-parser-worker.md) və
[Phase 1A-D2.2 completion record](status/phase-1a-d2-2-isolated-parser-worker.md).

## 5.16 Phase 1A-D3 — Owner source-text inspection və correction

### Məqsəd və sərhəd

D1-in yaratdığı encrypted source-text lineage-ni və D2.2-nin yaratdığı real parser
nəticəsini owner-ə göstərmək və düzəliş imkanı vermək. Heç bir yeni cədvəl və ya sütun
əlavə olunmayıb — D1 artıq `user_correction` revision şəklini dəstəkləyirdi.

### Service dəyişiklikləri

- `get_source_text` indi `account_id -> preparation_id -> document_version_id`
  ownership zəncirini tam yoxlayır (əvvəllər yalnız `account_id -> document_version_id`
  idi) — preparations/documents/document-intakes-də artıq mövcud olan konvensiyaya
  uyğunlaşdırılıb. `store_parser_extraction` (yalnız worker üçündür, heç vaxt HTTP-ə
  açılmır) qəsdən dəyişməz saxlanılıb.
- Yeni `append_correction` metodu eyni ownership zəncirini və document/preparation
  eligibility qaydasını (draft, expired olmayan, uyğun privacy snapshot, yalnız son
  document version) yoxlayır, canlı privacy qərarını yenidən təsdiqləyir və yeni
  `CandidateSourceTextVersion` (`origin="user_correction"`, bütün `parser_*` sahələri
  `NULL`, `previous_version_id` əvvəlki son versiyaya bağlı) əlavə edir.
- Optimistic concurrency mövcud aggregate `version` sütunundan (artıq başqa
  resurslarda ETag mənbəyi kimi istifadə olunur) istifadə edir: stale `If-Match` `412`
  qaytarır. Eyni `If-Match` və content ilə təkrar sorğu — artıq tətbiq olunmuş
  correction-u aşkarlayıb (decrypt edib müqayisə edərək) heç bir duplicate yaratmadan
  cari state-i qaytarır.
- Yeni `CandidateSourceTextPreconditionError` (`412`) `CandidateSourceTextConflictError`
  (`409`)-dan ayrıdır — biri stale ETag, digəri document/policy state konflikti üçündür.

### HTTP contract

```text
GET/PUT /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/source-text
```

- Scope: GET → `preparation:read`, PUT → `preparation:write`.
- Route `document-intakes/{intake_id}` konvensiyasına uyğun olaraq preparation altında
  flat saxlanılır (documents resource-u vasitəsilə nest olunmur).
- GET tam decrypted version lineage-i (content daxil) bir cavabda qaytarır — ayrıca
  raw-download content-type-ə ehtiyac yoxdur.
- PUT strong quoted `If-Match` tələb edir (`428` yoxdursa, `400` səhvdirsə, `412`
  stale-dirsə) və `{"content": str}` body-ni 500,000 simvola qədər qəbul edir.
- Yeni route `core/reliability.py`-dəki reviewed SLI product-route populyasiyasına
  əlavə olundu; mövcud route-drift regression testi bunu qoruyur.

### Deliberately not implemented

- Ayrıca `text/plain` raw-download endpoint-i yoxdur; JSON cavabı artıq tam content
  daşıyır.
- Correction history diff/rollback UI müqaviləsi yoxdur — GET artıq immutable version
  siyahısını qaytarır, bundan artıq UI-specific funksionallıq bu fazanın işi deyil.
- Bu yeni yazma yolu üçün ayrıca export/deletion/audit review keçirilmədi; D1-in
  cascade erasure və privacy-audit inteqrasiyası strukturca artıq buranı əhatə edir,
  amma tam Phase 1A lifecycle sign-off D4-ün işidir.
- Heç bir AI processing bu mətni hələ oxumur.

### Verification

- `not integration` filtri ilə `331` test keçib, `1`-i (POSIX-only) Windows-da skip
  olunub, `0` uğursuz.
- Strict mypy `platform = "linux"` hədəfi ilə `70` source faylı üçün keçir.
- Ruff lint və format yoxlamaları keçib.
- Yeni integration testlər (`tests/integration/test_candidate_source_texts.py`):
  end-to-end correction append, idempotent retry, stale-version və future-version
  precondition, wrong-preparation/wrong-owner rejection, ardıcıl ikinci correction-un
  `previous_version_id` zəncirini düzgün saxlaması. Docker Desktop əlçatan olmadığı
  üçün bunlar hazırda lokal skip olunur.
- Yeni HTTP-səviyyəli testlər (`tests/test_source_texts_api.py`): scope enforcement,
  ETag round-trip, `428`/`400`/`412` If-Match handling, `404`/`503`/`409` error
  mapping (daxili exception mətni sızmadan) və boş correction content üçün `422`.
- Heç bir yeni Alembic migration tələb olunmadı.

### Next part

Phase 1A-D4 (lifecycle və phase gate) Phase 1A-nı bağlayır: D1-D3-də yaranan
source-text/correction data üçün privacy access/export inteqrasiya review-u, Docker
əlçatan olduqda concurrency/security/migration/restore verification, və Phase 1B
(CV/JD profiling) başlamazdan əvvəl tam 1A flow üzrə supported-input fixture pass-ı.

Ətraflı qərar və sübut: [ADR 0016](adr/0016-owner-source-text-inspection-and-correction.md)
və [Phase 1A-D3 completion record](status/phase-1a-d3-owner-inspection-and-correction.md).

Stop here until the next explicit continuation request.

## 5.17 Phase 1A-D4 - lifecycle and phase gate

This follow-up supersedes the earlier D4 handoff snapshot. Docker-backed verification is
complete: `./scripts/verify.ps1` passed with `407` tests, one platform-specific skip,
and `95.02%` branch-aware coverage. Ruff, strict mypy, migration upgrade/round-trip and
model parity, dependency compatibility, and the Python vulnerability audit passed.

The local database was forward-migrated to `20260828_0009`. Logical backup/recovery
rehearsal passed with matching row counts and audit/document/source-text/extraction-job
trigger counts of `2/1/3/2`; it cleaned up the temporary recovery database and dump.
The release image also passed its non-root, embedded-migration, and baseline-schema
checks. Phase 1A is therefore locally release-verified. At that gate snapshot, Phase 1B
was next and still required a model-gateway contract.

## 5.18 Phase 1B-A - provider-neutral model gateway

The first Phase 1B dependency is implemented without selecting or contacting a model
vendor. A new `model_gateway` package defines exact model and prompt/schema release
identities, a provider protocol, strict structured-output models, payload-safe request
and response envelopes, and a disabled fail-closed runtime. Application composition
exposes the gateway but requires an explicit provider adapter when execution is enabled.

The gateway sends an application-owned JSON schema and validates the returned JSON
again with frozen, strict, extra-forbid Pydantic models. It rejects model-release drift,
filtering, truncation, excessive output, malformed JSON, type coercion, and unknown
fields. Transient failures use bounded per-attempt timeouts and exponential retry;
terminal failures expose only a closed safe code. Successful results carry exact
model/prompt coordinates plus canonical instruction and schema SHA-256 identities.

No provider SDK, endpoint, API key, outbound model call, CV/JD profile schema, durable
profiling job, derived-data table, or product route was added. Phase 1B-B adds exact
source-span profile contracts and owner/privacy/source-bound durable persistence before
any external adapter can receive candidate text.

## 5.19 Phase 1B-B1 - evidence-linked profile contracts

Application-owned `CvProfileOutput` and `JobDescriptionProfileOutput` contracts now
define the only structured shapes allowed across the model gateway. CV claims cover
skills, projects, responsibilities, career claims, and seniority hints; JD claims split
must-have and nice-to-have requirements and also cover responsibilities and seniority.
Direct identity/contact fields are absent.

Every item requires a unique bounded claim ID, a strict derived statement, an
explicit/inferred marker, and one to five exact `[start,end)` Unicode source spans with
the cited substring. The separate verifier checks the profile document type, source
bounds, and exact quote equality before returning a payload-safe verified result.
Collections, Unicode, duplicate evidence/skills/requirements, and AZ/EN language shape
are bounded and fail closed. Schema IDs begin at version `1.0.0`.

This phase makes no model call and adds no table or migration. Encrypted immutable
profile persistence, fenced jobs, dead-letter handling, privacy lifecycle integration,
and the reviewed provider worker remain Phase 1B-B2/C.

Repository-wide verification passed with `470` tests, one platform-specific skip, and
`95.35%` branch-aware coverage. Ruff, strict mypy for `76` source files, migration/model
parity, dependency compatibility, and the vulnerability audit also passed; schema
revision `20260828_0009` is unchanged.

## 5.20 Phase 1B-B2.1 - encrypted immutable profile persistence

`candidate_profiles` exact latest corrected-source revision üçün stable owner-bound
aggregate, `candidate_profile_versions` isə append-only encrypted revision lineage-i
yaradır. Aggregate exact document/source identity-si ilə yanaşı privacy policy,
jurisdiction, legal basis, delete-only retention rule və deadline snapshot-larını
saxlayır. İlk `model_generation` revision-u exact model/provider/version,
prompt/version, schema ID/version, instruction/schema SHA-256, attempt və content-free
evidence saylarını qeyd edir.

Strict canonical profile JSON PostgreSQL-də yalnız AES-256-GCM ciphertext kimi
saxlanır. Metadata-bound AAD bütün owner/profile/version, source/document,
model/prompt/schema, privacy/retention, count, digest və key identity field-lərini
bağlayır; ayrıca context-bound HMAC substitution-u aşkarlayır. Read/export zamanı
decryption, schema, digest və evidence count-ları yenidən yoxlanır və uyğunsuzluq fail
closed edir.

Persistence transaction-ı active account, draft/unexpired preparation, latest document
version, latest source revision və processing rule-u lock/re-authorize edir, exact
source revision-u decrypt edir və B1 exact span verifier-ini yenidən işlədir. Eyni exact
result retry-si idempotent-dir; dəyişən profile və ya release identity-si immutable
history-ni overwrite etmək əvəzinə conflict verir. Composite FK-lər, constraints və
dörd DB trigger-i identity/snapshot reassignment, version update və yanlış chain-i
application-dan asılı olmayaraq rədd edir.

Privacy export schema-sı `phase-1b-b2.1`-ə keçib və owned profile-ları narrow service
vasitəsilə decrypt edir; account/document/source cascade-ləri aggregate və revision-ları
silir. Provider adapter, outbound call, profiling job, public profile route və correction
command əlavə edilməyib.

Repository-wide verification `484` passed, bir platform-specific skip və `95.09%`
branch-aware coverage ilə tamamlanıb. Ruff, strict mypy (`78` source faylı), migration
round-trip/model parity, dependency və vulnerability gate-ləri keçib. Schema head
`20260831_0010`-dur; logical restore rehearsal və release-image verification də profile
cədvəl/constraint/trigger-ləri daxil olmaqla uğurla tamamlanıb.

## 5.21 Phase 1B-B2.2 - durable fenced profiling jobs

`candidate_profiling_jobs` hər exact immutable source revision üçün bir owner-bound,
idempotent execution stream yaradır. Schedule transaction-ı active owner, draft/unexpired
preparation, latest document/source lineage və privacy processing qərarını yenidən
yoxlayır; owner/preparation/document/source/revision identity-si, document type, privacy,
legal basis, delete-only retention, exact provider/model, prompt, schema,
instruction/schema digest-ləri və maximum output token limitini immutable snapshot kimi
saxlayır. Eyni exact request retry-si eyni job-u qaytarır, hər hansı snapshot drift-i
conflict verir.

Worker coordination `FOR UPDATE SKIP LOCKED`, database time və fresh UUID lease token-i
ilə işləyir. Beş dəqiqəlik claim bitəndə job recover oluna bilir, amma stale və competing
worker heç bir state dəyişikliyi edə bilmir. Maximum beş attempt, 60 saniyədən başlayıb
3600 saniyədə cap olunan exponential backoff, closed retryable failure taxonomy və
explicit `dead_letter` terminal state crash/retry sərhədini bağlayır.

`succeeded` yalnız eyni owner, document/source revision və exact model/prompt/schema
release-i üçün artıq encrypted persistence service-dən keçmiş profile-a bağlana bilər.
Dörd DB trigger-i insert snapshot-larını, immutable field-ləri, transition-ları və
successful result linkage-i application kodundan asılı olmayaraq yoxlayır. Audit/outbox
yalnız opaque ID, status/code, attempt və document type saxlayır; candidate text, prompt,
model output, quote, profile JSON/ciphertext, nonce, digest və raw provider error heç bir
operational payload-a düşmür.

Privacy export schema-sı `phase-1b-b2.2`-yə keçib və content-free owned profiling-job
metadata-sını qaytarır; account/preparation/document/source cascade-ləri job-ları silir.
Provider adapter, outbound call, profiling worker, public profile route və correction
command əlavə edilməyib.

Repository-wide verification `500` passed, bir platform-specific skip və `95.09%`
branch-aware coverage ilə tamamlanıb. Ruff, strict mypy (`80` source faylı), migration
round-trip/model parity, dependency və vulnerability gate-ləri keçib. Schema head
`20260901_0011`-dir; logical restore rehearsal bütün dörd profiling-job trigger-i ilə,
release-image verification isə exact embedded head ilə uğurla tamamlanıb.

## 5.22 Phase 1B-C1 - policy-gated profiling worker

CV və job-description üçün ayrıca code-owned prompt release-ləri yaradılıb. Hər prompt
exact ID/version, schema ID/version, canonical instruction/schema SHA-256 və fixed output
token limitinə bağlıdır; source document bütövlükdə untrusted data sayılır, içindəki
command/role/tool tələbləri rədd edilir, direct identity/contact output qadağandır və hər
claim exact Unicode source span tələb edir.

Real xarici çağırışdan əvvəl çatışmayan processor gate-i schema-ya əlavə olunub. Hər yeni
`candidate_profiling_jobs` row-u non-null `processor_activity_id` snapshot-ı saxlayır.
Schedule active processor/activity status-u, processor key ilə model provider uyğunluğunu,
privacy policy-ni, `candidate_document/interview_preparation` purpose/category-ni və
owner storage/origin region-unu yoxlayır. `20260901_0012` migration-u mövcud job-lara
icazə uydurmur, ambiguous row varsa fail edir; FK restrictive, snapshot trigger-i isə
activity ID-ni immutable saxlayır.

Job UUID həm də provider request/idempotency/deletion reference-dir və model gateway-dən
adapter-ə ötürülür. Worker source text-i provider-ə verməzdən dərhal əvvəl həmin processor
activity-ni privacy lifecycle ilə yenidən authorise edir və job UUID locator-unu keyed
digest + AES-256-GCM ciphertext kimi `processor_usages`-a idempotent qeyd edir. Suspended
processor və ya policy drift provider çağırışından əvvəl `policy_unavailable` dead-letter
verir.

`CandidateProfilingWorker` job-u claim edir, code-owned prompt və configured model release-i
immutable snapshot-la müqayisə edir, yalnız exact latest source revision-u decrypt edir,
strict gateway-i çağırır, exact-evidence verifier-i yenidən işlədir, nəticəni encrypted
profile service-dən keçirir və yalnız eyni live UUID lease token ilə success yazır. Stale
lease state-i dəyişmir; retry eyni provider request locator və idempotent profile lineage-i
istifadə edir. Safe gateway code-ları mövcud retry taxonomy-yə map olunur, unexpected
error `internal_failure` olur, cancellation false failure yazmadan propagate edilir.

Execution ayrıca `AI_INTERVIEWER_PROFILING_WORKER_ENABLED=false` gate-i ilə bağlıdır.
Enable etmək model gateway, privacy və file-security sərhədlərini, explicit injected
adapter-i və beş dəqiqəlik job lease daxilində maksimum 240 saniyəlik gateway retry budget-i
tələb edir. Concrete provider SDK/credential/endpoint, automatic supervisor, public profile
route və correction command əlavə edilməyib.

Repository-wide verification `524` passed, bir platform-specific skip və `95.09%`
branch-aware coverage ilə tamamlanıb. Ruff, strict mypy (`82` source faylı), migration
round-trip/model parity, dependency və vulnerability gate-ləri keçib. Schema head
`20260901_0012`-dir; logical restore rehearsal processor FK-si ilə, release-image
verification isə exact embedded head və numeric non-root runtime ilə uğurla tamamlanıb.

## 5.23 Phase 1B-C2 - owner profile inspection and immutable correction

Exact preparation/document/source revision üçün authenticated profil resursu əlavə edilib:
`GET` safe profiling-job status-u və yalnız fenced `succeeded` nəticədən sonra decrypted
immutable profil tarixçəsini qaytarır; `PUT` isə owner correction append edir. Read
`preparation:read`, write `preparation:write` tələb edir və hər lookup account,
preparation, document version və source-text version-u birlikdə yoxlayır. Cross-owner və
olmayan resurslar eyni opaque `404` davranışını verir.

Status response worker ID, lease token, processor activity/locator, digest və raw provider
detail göstərmir. Pending/processing/retry state-lərində profil expose edilmir və
`Retry-After` qaytarılır; completed history `Cache-Control: no-store` və aggregate
version-dan strong ETag alır. Beləliklə profile ciphertext yazılıb job success hələ
fence-lənməmiş qısa interval user-visible final nəticə sayılmır.

Correction strong quoted `If-Match` tələb edir. Command strict CV/JD schema-sını,
document type-ı, active owner/draft/latest lineage-i, privacy/legal/delete-only retention
qərarını və bütün exact Unicode evidence span-lərini retained source revision-a qarşı
transaction daxilində yenidən yoxlayır. Stale state `412` verir; yalnız aggregate bir
addım irəliləyib latest decrypted correction request-lə eynidirsə retry idempotent sayılır.

Yeni revision `user_correction` origin-i, exact schema ID/version, immutable predecessor,
recomputed evidence counts, context-bound HMAC və AES-256-GCM ciphertext ilə append olunur.
Model/provider/prompt provenance null qalır; generated revision və əvvəlki correction-lar
heç vaxt update edilmir. Mövcud DB constraint/trigger-ləri bu shape və chain-i artıq
qoruduğu üçün schema head `20260901_0012` olaraq qalır və yeni migration lazım olmayıb.

Audit/outbox yalnız opaque IDs, origin/schema və bounded evidence counts saxlayır; owner
audit actor-dur. Profile JSON, source quote/text, ciphertext, nonce və digest operational
payload-lara düşmür. Privacy export `phase-1b-c2`-yə keçib və bütün generated/corrected
revision-ları narrow decrypt/revalidation boundary-dən qaytarır; mövcud cascade erasure
tam lineage-i silir. Route reviewed product SLI population-a əlavə edilib.

Concrete provider adapter/credential/outbound call, public scheduling command və continuous
worker supervisor yenə shipped deyil. Növbəti local gate Phase 1B-D labeled AZ/EN profile
quality evaluation və regression approval-dur.

Repository-wide verification `538` passed, bir platform-specific skip və `95.15%`
branch-aware coverage ilə tamamlanıb. Ruff, strict mypy (`83` source faylı), migration
round-trip/model parity, dependency compatibility və vulnerability gate-ləri keçib. Schema
head dəyişmədən `20260901_0012`-dir. Restore rehearsal exact constraint/trigger inventarı
ilə keçib; release image C2 kodu ilə yenidən build olunaraq non-root, embedded-head,
migration-job və hardened runtime contract-larından keçib.

## 6. Hazırda mövcud HTTP API contract-ı

| Method və route | Məqsəd | Scope/şərt |
|---|---|---|
| `GET /api/v1/health/live` | Process yaşayırmı | Public operational route |
| `GET /api/v1/health/ready` | DB/schema/file-security dependency hazırdırmı | Public operational route |
| `GET /api/v1/identity/me` | Opaque local account ID | `profile:read` |
| `PUT /api/v1/privacy/profile` | Residence/policy/storage/18+ profile | `privacy:write` |
| `GET /api/v1/privacy/consents` | Consent history | `privacy:read` |
| `POST /api/v1/privacy/consents/{consent_notice_id}` | Exact notice grant | `privacy:write` |
| `DELETE /api/v1/privacy/consents/{consent_record_id}` | Consent withdrawal | `privacy:write` |
| `POST /api/v1/privacy/requests` | Access/export/deletion request | Növə görə scope + `Idempotency-Key` |
| `GET /api/v1/privacy/requests/{privacy_request_id}` | Owned request status/result | `privacy:read` |
| `POST /api/v1/preparations` | Preparation target yaratmaq | `preparation:write` + `Idempotency-Key` |
| `GET /api/v1/preparations` | Owned preparation-ları keyset ilə siyahılamaq | `preparation:read` |
| `GET /api/v1/preparations/{preparation_id}` | Owned preparation detail | `preparation:read` |
| `PUT /api/v1/preparations/{preparation_id}` | Full context replacement | `preparation:write` + strong `If-Match` |
| `POST /api/v1/preparations/{preparation_id}/archive` | Preparation archive | `preparation:write` + strong `If-Match` |
| `GET /api/v1/preparations/{preparation_id}/documents` | Owned CV/JD lineage siyahısı | `preparation:read` |
| `GET /api/v1/preparations/{preparation_id}/documents/{document_id}` | Immutable version metadata və aggregate ETag | `preparation:read` |
| `POST /api/v1/preparations/{preparation_id}/documents/{document_type}/upload` | Raw PDF/DOCX/text-i validate, scan və attach etmək | `preparation:write` + `Idempotency-Key` |
| `POST /api/v1/preparations/{preparation_id}/documents/{document_type}/paste` | UTF-8 text-i validate, scan və attach etmək | `preparation:write` + `Idempotency-Key` |
| `GET /api/v1/preparations/{preparation_id}/document-intakes/{intake_id}` | Owned durable intake status-u | `preparation:read` |
| `GET /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/source-text` | Decrypted source-text lineage və aggregate ETag | `preparation:read` |
| `PUT /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/source-text` | Owner correction append | `preparation:write` + strong `If-Match` |
| `GET /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/profiles/{source_text_version_id}` | Safe job status və completed immutable profile history | `preparation:read` |
| `PUT /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/profiles/{source_text_version_id}` | Evidence-revalidated encrypted profile correction append | `preparation:write` + strong `If-Match` |

`POST /privacy/requests` scope mapping-i:

- `access` -> `privacy:read`
- `export` -> `privacy:export`
- `deletion` -> `privacy:delete`

API hələ aşağıdakı endpoint-ləri vermir:

- extraction job-un manual trigger/cancel route-u;
- interview blueprint/session/answer;
- model invocation;
- scoring/evaluation/report;
- knowledge/RAG;
- audio/video.

## 7. Database schema inventory

Hazırda `26` application table və Alembic-in `alembic_version` cədvəli var.

| Cədvəl | Mərhələ | Məsuliyyət və əsas invariant |
|---|---|---|
| `outbox_events` | 0B | Atomic domain-event handoff, lease/retry/publish metadata |
| `audit_events` | 0B | Append-only security/lifecycle evidence; DB trigger mutation-u bloklayır |
| `accounts` | 0C-A | Pseudonymous issuer/subject mapping; unique cütlük, status və version |
| `privacy_policy_versions` | 0C-B | Versioned policy; active status legal approval tələb edir |
| `privacy_profiles` | 0C-B | Account residence/jurisdiction/storage/policy snapshot |
| `consent_notices` | 0C-B | Exact immutable notice identity və content digest |
| `consent_records` | 0C-B | Grant/withdrawal və retention evidence; bir active notice |
| `processing_rules` | 0C-B | Policy/jurisdiction/category/purpose allow/deny və legal basis |
| `retention_rules` | 0C-B | Category/purpose duration və delete/anonymize action |
| `privacy_requests` | 0C-B | Access/export/deletion state, due/completion və idempotency digest |
| `processors` | 0C-B | Vendor inventory və lifecycle status |
| `processor_activities` | 0C-B | Approved purpose/category/region/transfer/deletion contract |
| `processor_usages` | 0C-B | Account-vendor usage və encrypted locator metadata |
| `processor_deletion_tasks` | 0C-B | Durable vendor delete lease/retry/escalation/completion |
| `backup_deletion_markers` | 0C-B | Keyed fingerprint/cutoff restore replay evidence |
| `parser_release_policies` | 0C-C | Exact media/size/scanner/parser/isolation approval |
| `file_assets` | 0C-C | Authoritative quarantine/release/deletion saga state |
| `file_scan_attempts` | 0C-C | Bounded scanner evidence, no plaintext malware name |
| `file_deletion_tasks` | 0C-C | Exact version-aware object deletion work |
| `candidate_preparations` | 1A-A | Owner-bound preparation target, privacy/retention snapshot və version |
| `candidate_documents` | 1A-B | Stable per-preparation CV/JD aggregate və latest ordinal |
| `candidate_document_versions` | 1A-B | DB-trigger immutable released-asset/privacy/retention snapshot |
| `candidate_document_intakes` | 1A-C | Hashed-idempotent lease/retry/status və exact asset/version coordination |
| `candidate_source_texts` | 1A-D1 | Exact document version üçün owner-bound encrypted text aggregate |
| `candidate_source_text_versions` | 1A-D1 | AES-GCM encrypted immutable parser/correction revision və provenance |
| `candidate_extraction_jobs` | 1A-D2.1 | Durable exact-version extraction status, lease fencing, retry və safe errors |
| `candidate_profiles` | 1B-B2.1 | Exact source revision üçün owner/privacy-bound encrypted profile aggregate |
| `candidate_profile_versions` | 1B-B2.1 | AES-GCM encrypted append-only profile və model/prompt/schema provenance |
| `candidate_profiling_jobs` | 1B-B2.2/C1 | Exact-source durable status, immutable release/privacy/processor snapshots, UUID lease fencing və dead-letter state |
| `alembic_version` | Alembic | Database-in cari schema revision-u |

Migration chain:

```text
20260823_0001 persistence foundation
  -> 20260823_0002 identity foundation
  -> 20260824_0003 privacy lifecycle
  -> 20260824_0004 file/secret security
  -> 20260826_0005 candidate preparation context
  -> 20260827_0006 immutable candidate document versions
  -> 20260827_0007 authenticated document intakes
  -> 20260827_0008 encrypted candidate source text
  -> 20260828_0009 durable candidate extraction jobs
  -> 20260831_0010 encrypted immutable candidate profiles
  -> 20260901_0011 durable fenced candidate profiling jobs
  -> 20260901_0012 profiling processor-activity authorization gate
```

API readiness exact `20260901_0012` revision-u tələb edir. Connected, amma başqa
revision-da olan database traffic üçün hazır sayılmır.

## 8. Security və privacy posture

### 8.1 Hazırda qorunan sərhədlər

- Hosted environment unsafe/disabled auth, privacy və file-security ilə start etmir.
- Hosted database secret-i environment plaintext əvəzinə mounted file-dan alınır.
- Hosted database TLS tələb edir.
- OIDC issuer/JWKS və remote storage endpoint HTTPS olmalıdır.
- Access token bütöv şəkildə heç bir log/database/audit field-ə yazılmır.
- Scope və owner check fail closed edir.
- Cross-user resource existence açıqlanmır.
- Preparation create owner-scoped hashed idempotency, replacement/archive isə strong
  version precondition ilə qorunur.
- Preparation user text-i Unicode-normalized və bounded-dir; canonical code-lar user
  fallback text-dən ayrıdır.
- Audit/outbox detail-ləri candidate content və credential field-lərini rədd edir.
- Telemetry raw request/response, URL/query, ID, SQL və object key saxlamır.
- Object bytes parser-dən əvvəl validate və malware scan edilir.
- Quarantine object parser-ə verilmir.
- Storage encryption SSE-KMS metadata və checksum ilə verify edilir.
- S3 versioned object delete bütün version/delete marker-ləri silmədən tamamlanmır.
- Privacy deletion processor və file task-ləri bitmədən completed olmur.
- Backup restore deletion-ledger replay olmadan public readiness ala bilməz.
- Application runtime və local database container-ləri least-privilege qaydaları ilə
  sərtləşdirilib.

### 8.2 Qəsdən saxlanmayan məlumatlar

Repository-də real istifadəçi datası seed edilməyib. Məhsul işlədildikdə original
document bytes private storage-da, source text və strict profile JSON isə yalnız
encrypted formada saxlanır; aşağıdakılar hələ saxlanmır:

- password;
- email, ad, avatar və geniş identity profile;
- access/refresh token;
- PostgreSQL-də plaintext CV/JD, extracted source text və profile JSON;
- interview answer/transcript;
- evaluation/report;
- embedding və knowledge content;
- raw audio/video;
- face, gaze və emotion data.

### 8.3 Production-dan əvvəl açıq qalan risk/gate-lər

- Country-specific legal approval yoxdur.
- Real policy/consent/retention/processor records seed edilməyib.
- Cloud secret manager, IAM/workload identity, bucket/KMS və scanner sidecar provision
  edilməyib.
- Monitoring backend və access/retention enforcement seçilməyib.
- Pager/on-call route və incident drill yoxdur.
- Rate limiting, quota, overload və cost ceiling yoxdur.
- Provider-specific network policy, IaC, PITR/failover rehearsal yoxdur.

## 9. Test, quality və release mexanizmi

### 9.1 Lokal verification

Əsas command:

```powershell
uv sync --frozen
./scripts/verify.ps1
```

Script:

1. lock consistency-ni yoxlayır;
2. Ruff lint və format check işlədir;
3. strict mypy işlədir;
4. lazım olduqda project PostgreSQL service-ni başladır;
5. unique disposable integration database yaradır;
6. unit və real PostgreSQL integration suite-ni branch coverage ilə işlədir;
7. empty database migration və Alembic drift yoxlamalarını işlədir;
8. temporary database-i silir və əvvəlki environment-i bərpa edir;
9. dependency compatibility və vulnerability audit işlədir.

Development database destructive migration testləri üçün istifadə edilmir.

### 9.2 Phase exit test artımı

Bu cədvəldəki saylar hər mərhələ bitəndə bütün suite-in ümumi snapshot-ıdır:

| Gate | Test sayı | Coverage | Mypy source sayı |
|---|---:|---:|---:|
| 0A | 18 | 97.70% | 10 |
| 0B | 47 | 98.35% | 16 |
| 0C-A | 93 | 99.02% | 23 |
| 0C-B | 125 | 95.38% | 33 |
| 0C-C | 210 | 95.34% | 41 |
| 0D-A | 228 | 95.15% | 43 |
| 0D-B | 248 | 95.27% | 46 |
| 0D-C-A | 250 | 95.31% | 47 |
| 0D-C-B1 | 262 | 95.55% | 50 |
| 1A-A | 282 | 95.64% | 54 |
| 1A-B | 290 | 95.47% | 57 |
| 1A-C | 318 | 95.43% | 61 |
| 1B-B1 | 470 | 95.35% | 76 |
| 1B-B2.1 | 484 | 95.09% | 78 |
| 1B-B2.2 | 500 | 95.09% | 80 |
| 1B-C1 | 524 | 95.09% | 82 |
| 1B-C2 | 538 | 95.15% | 83 |

### 9.3 Container/release verification

```powershell
docker build --tag ai-interviewer-platform:local .
./scripts/verify-release-image.ps1
```

Release verification aşağıdakıları yoxlayır:

- OCI version/revision/created labels;
- embedded migration graph və exact head;
- baseline JSON schema-nın image daxilində mövcudluğu;
- numeric non-root runtime user;
- image-owned migration job;
- read-only root filesystem;
- all capabilities dropped;
- `no-new-privileges`;
- exact DB readiness;
- query-string canary-nin loglara düşməməsi;
- API və PostgreSQL `HIGH/CRITICAL` vulnerability gate;
- CycloneDX SBOM.

### 9.4 Backup/restore

[Backup/restore runbook](runbooks/database-backup-restore.md) və
`scripts/rehearse-database-restore.ps1` aşağıdakıları yoxlayır:

- isolated custom-format backup və restore;
- exact schema revision;
- tracked row counts;
- required table/index/constraint/trigger-lər;
- audit immutability;
- API readiness;
- privacy deletion marker replay sərhədi;
- temporary database və dump cleanup.

## 10. Architecture Decision Records

| ADR | Qərar | Cari nəticə |
|---|---|---|
| [0001](adr/0001-modular-monolith-and-deterministic-orchestration.md) | Modular monolith + deterministic orchestrator | Qəbul edilib |
| [0002](adr/0002-python-api-runtime.md) | Python 3.12/FastAPI/uv/Alpine runtime | Qəbul edilib |
| [0003](adr/0003-postgresql-persistence-contract.md) | PostgreSQL, async SQLAlchemy, outbox və immutable audit | Qəbul edilib |
| [0004](adr/0004-oidc-resource-server-and-local-identity.md) | OIDC resource server və minimal local identity | Qəbul edilib |
| [0005](adr/0005-jurisdiction-aware-privacy-lifecycle.md) | Layered privacy policy və lifecycle | Qəbul edilib, legal certification deyil |
| [0006](adr/0006-file-secret-security.md) | Secret/keyring, storage, scan və file lifecycle | Qəbul edilib |
| [0007](adr/0007-release-and-migration-contract.md) | Build-once, exact schema və forward-only release | Qəbul edilib |
| [0008](adr/0008-payload-blind-opentelemetry.md) | Payload-blind metric/trace/log contract | Qəbul edilib |
| [0009](adr/0009-measure-before-objective.md) | Əvvəl ölç, sonra SLO seç | Qəbul edilib |
| [0010](adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md) | Feature-stable text MVP-dən sonra hosted reliability baseline | Qəbul edilib; production gate-ləri ləğv etmir |
| [0011](adr/0011-immutable-candidate-document-lineage.md) | Released file asset üzərində immutable CV/JD lineage | Qəbul edilib |
| [0012](adr/0012-durable-authenticated-document-intake.md) | Hashed-idempotent, lease-based upload/paste saga və exact asset recovery | Qəbul edilib |
| [0013](adr/0013-encrypted-immutable-candidate-source-text.md) | AES-256-GCM encrypted immutable source-text lineage və parser provenance | Qəbul edilib |
| [0014](adr/0014-durable-candidate-extraction-jobs.md) | Exact-version extraction job, lease fencing və bounded retry contract | Qəbul edilib |
| [0015](adr/0015-isolated-parser-worker.md) | No-network resource-bounded parser worker | Qəbul edilib |
| [0016](adr/0016-owner-source-text-inspection-and-correction.md) | Owner-scoped source inspection və immutable correction | Qəbul edilib |
| [0017](adr/0017-phase-1a-lifecycle-and-phase-gate.md) | Phase 1A privacy lifecycle və fixture gate | Qəbul edilib |
| [0018](adr/0018-provider-neutral-model-gateway.md) | Disabled-by-default provider-neutral model execution boundary | Qəbul edilib |
| [0019](adr/0019-evidence-linked-profile-contracts.md) | Strict exact-evidence CV/JD profile contract-ları | Qəbul edilib |
| [0020](adr/0020-encrypted-candidate-profile-persistence.md) | Exact-source encrypted immutable candidate profiles | Qəbul edilib |
| [0021](adr/0021-durable-fenced-profiling-jobs.md) | Exact-source idempotent jobs, UUID lease fencing və bounded dead-letter handling | Qəbul edilib |
| [0022](adr/0022-policy-gated-profiling-execution.md) | Code-owned prompts, immutable processor authorization və fenced execution | Qəbul edilib |
| [0023](adr/0023-owner-profile-inspection-and-correction.md) | Owner-only safe status/inspection və immutable evidence-revalidated profile correction | Qəbul edilib |

## 11. Repository xəritəsi

```text
.
|-- .github/workflows/          CI quality/security/release gate
|-- docker/postgres/            Hardened local PostgreSQL derivative image
|-- docs/
|   |-- adr/                    Architecture Decision Records
|   |-- legal/                  Açıq legal qərarlar
|   |-- operations/             Dashboard specification
|   |-- reliability/            SLI və evidence contract-ları
|   |-- runbooks/               Backup, release, file və telemetry əməliyyatları
|   |-- security/               Threat model və data inventory
|   `-- status/                 Hər tamamlanmış mərhələnin exit record-u
|-- migrations/versions/        On iki forward schema revision-u
|-- scripts/                    Verification və restore rehearsal
|-- src/ai_interviewer/
|   |-- api/                    HTTP route/error contract-ları
|   |-- candidate_inputs/       Preparation, document lineage və durable intake lifecycle
|   |-- core/                   Config, log, middleware, crypto, telemetry, SLI
|   |-- file_security/          Validation, store, scanner və lifecycle
|   |-- identity/               JWT, principal, scope, account
|   |-- persistence/            DB, schema, migrations, outbox, audit
|   |-- privacy/                Policy, consent, retention, processor, deletion
|   |-- model_gateway/          Provider-neutral execution contract və release identity
|   |-- profiling/              Evidence schemas, encrypted profiles/jobs və owner correction
|   `-- reliability/            Baseline evidence və CLI
|-- tests/                      Unit və integration suite
|-- Dockerfile                  API/migration/baseline release image
|-- compose.yaml                Hardened local PostgreSQL service
|-- pyproject.toml              Package, dependencies və quality config
`-- uv.lock                     Reproducible dependency lock
```

Bu sənəd yazılan anda:

- `87` Python source faylı;
- `49` Python test faylı;
- `12` Alembic revision faylı;
- `67` Markdown sənədi;
- `4` operational PowerShell/Python script mövcuddur.

## 12. Qəsdən hələ edilməyənlər

Aşağıdakılar yarımçıq və ya placeholder kimi yazılmayıb; uyğun gate gələnədək ümumiyyətlə
başlanmayıb:

- frontend və candidate onboarding UI;
- provider credential/supervisor və real-provider profile quality approval;
- company/role/round knowledge base;
- global source policy registry və ingestion connector-ları;
- embeddings, `pgvector`, hybrid retrieval və RAG;
- interview blueprint;
- deterministic interview session state machine;
- interviewer/evaluator execution workflow;
- skill state və adaptive policy;
- final report;
- voice/STT/TTS;
- video/avatar/WebRTC;
- practice-only integrity events;
- employer-facing workflow.

Bu yanaşma ona görə seçilib ki, file upload auth/privacy/deployment sərhədlərindən əvvəl,
SLO ölçüdən əvvəl, alert isə owner və target-dən əvvəl yaradılmasın.

## 13. Cari stop point

Cari tamamlanmış məhsul vahidi `1B-D2.2b1`-dir. Phase 1A exact document/source lifecycle-i,
1B-A model execution port-u, 1B-B1 strict exact-evidence CV/JD contract-ları, B2 encrypted
profile/job contract-ını, C1 isə code-owned prompt, immutable processor authorization,
encrypted usage registration və lease-fenced worker execution-u qurub. C2 authenticated
owner status/inspection, strong ETag/`If-Match` və encrypted immutable correction append-i
əlavə edib. D1 deterministic offline quality evaluator-u, fixed field/slice/span/review
threshold-larını, synthetic AZ/EN CV/JD seed-i və evidence digest-ə bağlı ayrıca dörd
reviewer rolunu əlavə edib. D2.1 disabled-by-default OpenAI Responses adapter-i əlavə
edib. D2.2a exact corpus/prompt/model/time-window authorization-na və ayrıca operator
confirmation-na bağlı private offline prediction runner-i və bilərəkdən unadjudicated
review draft-ı əlavə edib; credential və real corpus saxlanmayıb, verification zamanı
outbound model call edilməyib. D2.2b1 completed review-u exact corpus və prediction run-a
yenidən bağlayan, immutable content drift-i və natamam human review-u rədd edən create-only
evidence finalizer-i əlavə edib.

Hazırkı düzgün dayanacaq real provider corpus-u və named approval üçün `1B-D2.2b2` gate-indədir.
İstifadəçinin təsdiq etdiyi
[ADR 0010](adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md) qərarına
görə hosted 28 günlük baseline və ondan asılı 0D production gate-ləri text MVP-nin
route/query/contract səthi feature-stable olana qədər təxirə salınıb. Onlar ləğv
edilməyib və production-dan əvvəl mütləq tamamlanmalıdır.

## 14. Düzgün növbəti ardıcıllıq

### 1B-D2 — Reviewed release quality evidence and approval

**Dependencies:** tamamlanmış 1A exact owner/source lifecycle və 1B-A-dan 1B-C2-yə qədər
model/profile execution, persistence, status və correction contract-ları.
**Hazırdır (D1):** strict labeled evidence/adjudication schema-sı, fixture
rights/provenance contract-ı, field-level precision/recall, exact span coverage,
correction-rate, dil/document/adversarial slice ölçüləri, fixed threshold policy,
payload-safe CLI və evidence digest-ə bağlı ayrıca approval schema-sı.
**Hazırdır (D2.1):** reviewed, disabled-by-default OpenAI Responses adapter-i; strict
non-stored structured output; exact response-model yoxlaması; server-only secret delivery;
mock-transport verification. **Hazırdır (D2.2a):** exact digest/time-window authorization,
explicit external-processing confirmation, private prediction artifact və unadjudicated
review draft tooling-i. **Hazırdır (D2.2b1):** exact review finalization, immutable
corpus/prediction/provenance/order drift rejection, exhaustive adjudication və owner-review
completion checks. **Qalıb (D2.2b2):** rights-cleared tam corpus üzərində approved
exact OpenAI release run-u; exhaustive human adjudication; recorded error analysis; bütün
threshold-ların keçməsi; product, engineering, AZ language və EN language rollarının
named approval-u. Concrete provider activation və continuous supervisor ayrıca reviewed
gate olaraq qalır.

### Təxirə salınmış mandatory pre-production gate-lər

Text MVP feature-stable olduqdan sonra ardıcıllıq yenidən `0D-C-B2 -> 0D-C-C ->
0D-C-D -> 0D-D -> 0D-E` olur. 28 günlük real synthetic staging evidence, named
approvals, alert routing, incident drills, rate/resource protection, IaC, workload
identity, PITR və launch sign-off olmadan production buraxılışı edilə bilməz.

## 15. Sonrakı məhsul roadmap-i

Qalan əsas inkişaf ardıcıllığı:

```text
1A-D sandboxed extraction/correction
  -> 1B CV/JD profiling
  -> 1C interview blueprint
  -> 1D deterministic text session
  -> 1E evaluator/report
  -> 1F MVP experience/launch gate
  -> 2A source policy/taxonomy
  -> 2B compliant ingestion
  -> 2C hybrid retrieval/RAG
  -> 2D company specificity
  -> 3A planner/role-separated models
  -> 3B skill state
  -> 3C adaptive policy və Simulation/Coach
  -> 3D evaluator calibration
  -> deferred 0D-C-B2/0D-C-C/0D-C-D/0D-D/0D-E pre-production gates
```

Sonrakı parallel/conditional mərhələlər:

- Phase 4: privacy və rights gate-lərindən sonra structured contribution flywheel;
- Phase 5: text engine və evaluator keyfiyyəti sübut ediləndən sonra voice/video;
- Phase 6: yalnız real demand və bottleneck ölçülərindən sonra global scale.

Tam purpose, dependency, module və completion criteria-ları
[development roadmap](development-roadmap.md)-də verilib.

## 16. Yekun

Sıfırdan qurulan hazır hissə görünən AI demo-su deyil, gələcək məhsulun production
foundation-ıdır: reproducible runtime, PostgreSQL transaction/migration, OIDC owner
sərhədi, privacy lifecycle, encrypted/quarantined file contract, hardened release,
payload-blind telemetry, sübuta bağlı reliability measurement tooling və ilk
owner-bound preparation target aggregate-i, immutable CV/JD metadata lineage-i və
recoverable authenticated upload/paste saga-sı, encrypted immutable source-text
lineage-i, durable extraction-job contract-ı, exact-release model gateway-i, strict
evidence-linked CV/JD contract-ları və encrypted immutable profile lineage-i.

Bu foundation-a durable exact-source profiling job contract-ı, UUID lease fencing,
bounded retry, explicit dead-letter state, code-owned prompt release-ləri, immutable
processor authorization ilə policy-gated worker və owner-only immutable profile correction
də daxildir. D1 offline deterministic profile-quality evaluator-u, fixed threshold-ları,
synthetic AZ/EN CV/JD seed-i və separate digest-bound approval contract-ını da qurub.

Ən vacib prinsip qorunub: sonrakı mərhələnin funksiyası əvvəlki gate tamamlanmadan
kod bazasına gətirilməyib. Hazırkı düzgün dayanacaq D2.2b1 exact review finalizer-dan sonra,
real-provider corpus və named regression approval gate-i olan D2.2b2-dədir.
Hosted reliability işi daha gec ediləcək, amma production gate kimi roadmap və ADR-də
açıq qalır.

## 17. Phase 1B-D2.1 OpenAI Responses adapter

OpenAI was selected as the first concrete provider for the Phase 1B quality run. The
repository now includes a disabled-by-default Responses API adapter behind the existing
provider-neutral gateway. It sends strict JSON Schema output requests to the fixed OpenAI
endpoint with `store=false`, `background=false`, `truncation=disabled`, no tools, and the
durable job UUID as `X-Client-Request-Id`. The response-reported model release is checked
by the existing gateway before output is accepted.

Schema defaults are removed for provider compatibility, every object property becomes
required, and `additionalProperties=false` is enforced recursively. The original strict
application schema and exact-source evidence checks remain the final authorities. HTTP,
timeout, network, refusal, incomplete, malformed, oversized, and model-drift outcomes
fail closed through payload-free codes.

OpenAI credentials are server-only `SecretStr` values. Development can use an ignored
local environment secret; hosted environments require an absolute orchestrator-mounted
secret file. The adapter, gateway, and profiling worker remain disabled by default. All
adapter tests use a local mock transport, so no credential, candidate data, billing event,
or external call was produced in D2.1.

The remaining Phase 1B-D2.2 work is the rights-cleared full AZ/EN CV/JD corpus, approved
processor activity and exact model release, prediction capture, exhaustive human
adjudication, slice/error analysis, all fixed threshold passes, and four named
evidence-digest-bound approvals. Product activation and continuous supervision are still
separate reviewed gates.

## 18. Phase 1B-D2.2a authorized offline quality runner

D2.1 transport-u real corpus-a qoşmazdan əvvəl ayrıca operator/governance sərhədi əlavə
edildi. Strict corpus gold profile və exact source evidence-ni doğrulayır. Ayrı approval
artifact-i canonical corpus SHA-256, dataset/version, current prompt digest, exact OpenAI
release, processor/data-control references, approver və active aware time window-a bağlanır.

`generate` yalnız `--confirm-external-processing` ilə işləyir; mismatch/expiry provider
çağırışından əvvəl bağlanır. Maximum 200 fixture sequential icra olunur, request UUID-ləri
deterministikdir, nəticə strict prediction və ya safe failure-dır. Output yalnız bütün run
bitəndən sonra yeni private fayl kimi yaradılır və content-free digest/count summary verir.

`prepare-review` exact corpus/run join edir, amma human qərarı uydurmur: adjudication boş,
owner review isə `not_reviewed` qalır. Buna görə draft final evidence schema-sını keçmir.
Unit test-lər in-memory provider istifadə edir; real API call, billing, credential, corpus,
prediction, adjudication və approval yaradılmayıb. Qalan D2.2b2 işi approved full corpus
run-u, human review/error analysis, bütün threshold-lar və dörd named approval-dur.

Tam `./scripts/verify.ps1` nəticəsi: `608 passed, 1 skipped`, `95.53%` combined branch
coverage, Ruff check/format `217` fayl, strict mypy `87` source fayl, sıfırdan `12`
PostgreSQL migration, dependency compatibility və vulnerability audit uğurludur.

## 19. Phase 1B-D2.2b1 exact human-review finalization

`finalize-review` original corpus, exact prediction run və human tərəfindən tamamlanmış
review artifact-ını birlikdə tələb edir. Tool canonical unreviewed draft-ı yenidən qurur
və reviewer-in yalnız `adjudications` və `owner_review_outcome` sahələrini dəyişməsinə
icazə verir. Source text, rights provenance, risk slice, expected profile, prediction,
model/prompt coordinate və fixture order dəyişərsə finalization fail-closed olur.

Hər fixture üçün owner review məcburidir. Strict `LabeledProfileFixture` contract-ı hər
gold və predicted claim-in exact bir dəfə, eyni field daxilində adjudicate edilməsini
tələb edir. Uğurlu nəticə overwrite etmədən private `ProfileQualityEvidence` yaradır və
stdout-a yalnız artifact/evidence digest-i, fixture count və safe status yazır. Provider
çağırışı və automatic approval yoxdur.

[ADR 0027](adr/0027-exact-human-review-finalization.md) bu keçidi ayrıca local security
boundary kimi qəbul edir. Real rights-cleared corpus, approved OpenAI run, qualified human
review/error analysis, threshold success və dörd named approval hələ D2.2b2-də qalır.

Tam `./scripts/verify.ps1` nəticəsi: `610 passed, 1 skipped`, `95.57%` combined branch
coverage, Ruff check/format `220` fayl, strict mypy `87` source fayl, sıfırdan `12`
PostgreSQL migration, dependency compatibility və vulnerability audit uğurludur.

## 20. Disabled-by-default worker supervision runtime

Mövcud durable extraction və profiling job-ları üçün ayrıca process entrypoint əlavə
edildi. Extraction worker application composition-a qoşuldu, amma həm extraction, həm
profiling worker default olaraq disabled qalır. API lifespan background job başlatmır;
operator və ya orchestrator ayrıca `ai-interviewer-workers` process-ini işə salmalıdır.

Supervisor hər sweep-də bounded batch istifadə edir, enabled worker-ləri müstəqil icra
edir və bir runtime failure-ın digər queue-nu bloklamasına imkan vermir. Boş queue üçün
bounded polling, runtime failure üçün ayrıca backoff, cancellation propagation və normal
database/telemetry cleanup mövcuddur. `--once` bir operator sweep-i edib dayanır.

Extraction success/failure transition zamanı lease itirilərsə worker artıq process-i
crash etdirmir; nəticə payload-free `fenced/lease_expired` olur və durable winner
authoritative qalır. Log-larda yalnız bounded status count-ları və exception class adı
var; candidate content, identifier, path, object key, provider body və exception message
yoxdur.

[ADR 0028](adr/0028-disabled-by-default-worker-supervision.md) process separation və
activation boundary-ni sabitləyir. Bu dəyişiklik D2.2b2 quality gate-ni keçmir: real
rights-cleared corpus, human adjudication/error analysis, threshold success və dörd named
approval hələ tələb olunur. Credential, schema migration və real provider call əlavə
edilməyib.

Tam `./scripts/verify.ps1` nəticəsi: `629 passed, 1 skipped`, `95.63%` combined branch
coverage, Ruff check/format `226` fayl, strict mypy `89` source fayl, sıfırdan `12`
PostgreSQL migration, dependency compatibility və vulnerability audit uğurludur.

## 21. Provider-free quality authorization preflight

D2.2b2 üçün real corpus workspace-də olmadığına görə gate saxta data ilə keçilmədi və
asılı `1C` mərhələsinə başlanmadı. Bunun əvəzinə mövcud D2.2a external-processing sərhədi
provider-free `preflight` command-i ilə sərtləşdirildi.

`preflight <corpus> <authorization>` strict private artifact-ləri oxuyur və canonical
corpus digest, current prompt contract, dataset/version, authorization digest, active
approval window və exact OpenAI release binding-lərini yoxlayır. Gateway qurmur, API key
oxumur və network call etmir. Uğurlu output yalnız safe model coordinates, timestamp,
fixture count və digest-lərdir; corpus path-i, approver, processor/data-control reference,
source text, gold profile və secret-lər çıxışdan kənardır. Invalid input isə əvvəlki kimi
yalnız bounded error type/status qaytarır.

Real prediction evidence, exhaustive human adjudication/error analysis, threshold pass və
dörd named approval hələ D2.2b2-də qalır.

Tam `./scripts/verify.ps1` nəticəsi: `632 passed, 1 skipped`, `95.64%` combined branch
coverage, Ruff check/format `226` fayl, strict mypy `89` source fayl, sıfırdan `12`
PostgreSQL migration, dependency compatibility və vulnerability audit uğurludur.
