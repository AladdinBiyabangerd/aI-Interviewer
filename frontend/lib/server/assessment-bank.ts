// Original editorial seed. Never import this answer-bearing module into client code.
import type { CompanyContext, Level, PublicQuestion, Reference } from "../assessment.ts";

export type BankQuestion = PublicQuestion & {
  level: Level; correct: string[]; explanation: string; references: Reference[];
  status: "published" | "draft" | "retired";
};
const refs = {
  java: { title: "Oracle: Java language basics", url: "https://dev.java/learn/language-basics/" },
  oop: { title: "Oracle: classes and objects", url: "https://dev.java/learn/classes-objects/" },
  collections: { title: "Oracle: collections framework", url: "https://dev.java/learn/api/collections-framework/" },
  exceptions: { title: "Oracle: exceptions", url: "https://dev.java/learn/exceptions/" },
  spring: { title: "Spring: dependency injection", url: "https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html" },
  rest: { title: "Spring: building a REST service", url: "https://spring.io/guides/gs/rest-service" },
  sql: { title: "PostgreSQL: querying a table", url: "https://www.postgresql.org/docs/current/tutorial-select.html" },
  transactions: { title: "PostgreSQL: transactions", url: "https://www.postgresql.org/docs/current/tutorial-transactions.html" },
  outbox: { title: "Debezium: transactional outbox", url: "https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html" },
  retry: { title: "Resilience4j: bounded retries", url: "https://resilience4j.readme.io/docs/retry" },
  jpa: { title: "Spring: accessing data with JPA", url: "https://spring.io/guides/gs/accessing-data-jpa" },
  testing: { title: "Spring Boot: testing", url: "https://docs.spring.io/spring-boot/reference/testing/index.html" },
  git: { title: "Git tutorial", url: "https://git-scm.com/docs/gittutorial" },
  linux: { title: "GNU: directory listing", url: "https://www.gnu.org/software/coreutils/manual/html_node/ls-invocation.html" },
  maven: { title: "Apache Maven: build lifecycle", url: "https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html" },
  security: { title: "Spring Security: authorization", url: "https://docs.spring.io/spring-security/reference/servlet/authorization/index.html" },
  docker: { title: "Docker: containers", url: "https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/" },
  ci: { title: "GitHub: continuous integration", url: "https://docs.github.com/en/actions/about-github-actions/understanding-github-actions" },
  ai: { title: "Spring AI: concepts", url: "https://docs.spring.io/spring-ai/reference/concepts.html" },
  tools: { title: "Spring AI: tool calling", url: "https://docs.spring.io/spring-ai/reference/api/tools.html" },
  observations: { title: "Spring Boot: observability", url: "https://docs.spring.io/spring-boot/reference/actuator/observability.html" },
  threads: { title: "Oracle: concurrency", url: "https://docs.oracle.com/javase/tutorial/essential/concurrency/" },
  virtual: { title: "Oracle: virtual threads", url: "https://dev.java/learn/new-features/virtual-threads/" },
  kafka: { title: "Apache Kafka: design", url: "https://kafka.apache.org/41/design/design/" },
  gc: { title: "Oracle: garbage collection", url: "https://dev.java/learn/jvm/tool/garbage-collection/" },
  jfr: { title: "Oracle: JDK Flight Recorder", url: "https://dev.java/learn/jvm/jfr/" },
  cache: { title: "Spring: cache abstraction", url: "https://docs.spring.io/spring-framework/reference/integration/cache.html" },
  k8s: { title: "Kubernetes: Pod lifecycle", url: "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/" },
  evaluation: { title: "Spring AI: evaluation testing", url: "https://docs.spring.io/spring-ai/reference/api/testing.html" },
} satisfies Record<string, Reference>;

type Seed = [string, string[], number[], string, keyof typeof refs, string?];
// Every question has a stable ID and revision. Changes to wording, keys or explanations
// require a version bump; existing sessions keep their immutable question snapshots.
function group(topic: string, level: Level, difficulties: number[], seeds: Seed[]): BankQuestion[] {
  return seeds.map(([prompt, options, correct, explanation, ref, tag], index) => ({
    id: `${topic}-${index + 1}`, version: 1, topic, level,
    tags: [topic, ...(tag ? [tag] : [])], complexity: difficulties[index],
    type: correct.length === 1 ? "single" : "multiple", prompt,
    options: options.map((text, i) => ({ id: String.fromCharCode(97 + i), text })),
    correct: correct.map((i) => String.fromCharCode(97 + i)), explanation,
    source: { title: `Original question · Reference: ${refs[ref].title}`, url: refs[ref].url },
    references: [refs[ref]], companyContexts: [] as CompanyContext[], status: "published",
  }));
}

export const questionBank: BankQuestion[] = [
  ...group("core-java", "Junior", [0, 2, 4], [
    ["What is an object in Java?", ["An instance of a class", "A source-code folder", "A compiler option", "A database table"], [0], "A class describes a type; an object is an instance with its own state.", "oop", "oop"],
    ["Which choices support encapsulation? Select all that apply.", ["Keep internal fields private", "Expose every field publicly", "Validate changes through methods", "Put unrelated classes in one file"], [0, 2], "Encapsulation controls access to state so the object can preserve its rules.", "oop", "oop"],
    ["Two different String objects contain the same text. How should you compare their contents?", ["Use ==", "Use equals()", "Compare their memory addresses", "Convert both to Object and use =="], [1], "equals() compares String contents. == compares whether references point to the same object.", "java"],
  ]),
  ...group("collections", "Junior", [1, 2, 4], [
    ["You need to look up a user by a unique ID. Which collection best expresses this?", ["List of unrelated values", "Set of user names", "Map from ID to user", "Queue of events"], [2], "A Map associates a key with a value and supports lookup by that key.", "collections"],
    ["Which statements describe a Set? Select all that apply.", ["It rejects duplicate elements according to its equality rules", "Every Set keeps insertion order", "It is useful for tracking unique values", "It always supports access by numeric index"], [0, 2], "Sets model uniqueness. Ordering depends on the implementation; numeric indexing is a List concept.", "collections"],
    ["A file operation can fail. Which approach makes the failure easiest for callers to handle?", ["Catch the exception and silently return success", "Remove all error handling", "Return random data", "Handle it meaningfully or propagate an informative exception"], [3], "A caller needs an honest failure signal. Handle an error where recovery is possible, otherwise preserve useful context.", "exceptions"],
  ]),
  ...group("spring", "Junior", [1, 2, 4], [
    ["What is the main purpose of dependency injection?", ["Let an object receive the collaborators it needs", "Turn Java into SQL", "Remove the need for tests", "Make every object global"], [0], "Supplying dependencies separates construction from use and makes collaborators easier to replace in tests.", "spring"],
    ["Which practices suit a REST endpoint that creates a resource? Select all that apply.", ["Change data through a GET request", "Validate the request", "Return a meaningful HTTP status", "Always return success, even on failure"], [1, 2], "Validate inputs and communicate the outcome through HTTP semantics, such as 201 for successful creation.", "rest"],
    ["A service needs a repository. Why is constructor injection useful?", ["It makes the repository a database table", "It exposes required dependencies and allows test substitutes", "It eliminates all runtime errors", "It automatically commits every transaction"], [1], "The constructor makes required collaborators explicit. Tests can provide a fake or mock repository.", "spring"],
  ]),
  ...group("data", "Junior", [1, 2, 4], [
    ["Which SQL clause filters individual rows by a condition?", ["ORDER BY", "SELECT", "WHERE", "LIMIT"], [2], "WHERE filters rows. ORDER BY sorts them and LIMIT bounds the result size.", "sql"],
    ["What does a transaction help achieve when two related updates must succeed together?", ["Both updates commit, or neither takes effect", "Every query becomes faster", "No constraints are needed", "Data is permanently kept in memory"], [0], "Atomicity treats related changes as one unit: commit them together or roll them back.", "transactions"],
    ["Which statements about JPA are correct? Select all that apply.", ["JPA removes the need to understand SQL", "Entities represent persisted application data", "Database constraints no longer matter", "Repositories can provide common persistence operations"], [1, 3], "JPA maps application objects to relational data. SQL behavior, transactions and database constraints still matter.", "jpa", "jpa"],
  ]),
  ...group("testing", "Junior", [1, 2, 4], [
    ["What does a focused unit test usually check?", ["The entire deployed system at once", "A small behavior in isolation", "Only the source-code formatting", "Whether a developer memorized syntax"], [1], "Unit tests provide fast feedback about a small behavior, with external dependencies controlled.", "testing"],
    ["An AI assistant generates a service method. What should you do before accepting it? Select all that apply.", ["Review its behavior against the requirements", "Accept it because it compiles", "Check failure cases with tests", "Assume its dependencies are always valid"], [0, 2], "Treat generated code as a proposal: understand it and test intended behavior and failures.", "testing", "responsible-ai"],
    ["A mocked repository test passes, but the real query fails. Which test would best expose this?", ["A screenshot of the IDE", "The same mocked test repeated", "An integration test against a representative database", "A test that only checks method names"], [2], "Integration tests exercise boundaries such as real SQL, mappings and constraints that mocks do not verify.", "testing"],
  ]),
  ...group("tools", "Junior", [1, 2, 4], [
    ["In a Linux terminal, what does ls normally do?", ["List directory contents", "Delete the current directory", "Create a Git commit", "Compile Java"], [0], "ls lists files and directories. It is a basic navigation and inspection tool.", "linux", "linux"],
    ["Which Git actions help you prepare a deliberate commit? Select all that apply.", ["Inspect changes with git diff", "Delete the repository history", "Check staged and unstaged changes with git status", "Commit secrets so collaborators can use them"], [0, 2], "Review the diff and status before staging and committing a coherent change.", "git", "git"],
    ["Why use Maven or Gradle in a Java project?", ["To replace the JVM", "To manage dependencies and repeatable build tasks", "To automatically solve every production failure", "To avoid version control"], [1], "Build tools coordinate compilation, dependencies, tests and packaging so the process is repeatable.", "maven", "build-tools"],
  ]),
  ...group("security", "Mid", [2, 4, 7], [
    ["What is the difference between authentication and authorization?", ["They are always identical", "Authentication identifies a caller; authorization decides allowed actions", "Authorization only encrypts traffic", "Authentication grants every permission"], [1], "Knowing who made a request does not by itself establish permission to access a resource.", "security"],
    ["A signed-in user requests another user's private order by ID. What should the API do?", ["Allow access because the user signed in", "Trust that the ID was hidden in the UI", "Check permission to access that specific order", "Only check whether the ID is numeric"], [2], "Enforce access to the requested resource on the server, including ownership or an explicit permission.", "security"],
    ["Which measures help protect a sensitive API? Select all that apply.", ["Enforce least privilege", "Rely exclusively on hidden frontend buttons", "Check authorization on every protected operation", "Treat possession of any valid token as unrestricted access"], [0, 2], "Apply narrowly scoped permissions at the server boundary. Client UI controls are not an authorization boundary.", "security"],
  ]),
  ...group("delivery", "Mid", [2, 4, 7], [
    ["What does a container package for an application?", ["Only a screenshot", "The host computer's entire physical hardware", "The application and its runtime dependencies", "Every production secret by default"], [2], "Containers package an application environment and isolate its processes while sharing the host kernel.", "docker"],
    ["Which checks belong in a useful CI pipeline? Select all that apply.", ["Build the application", "Run automated tests", "Skip checks on pull requests", "Publish credentials into build logs"], [0, 1], "Automated builds and tests expose regressions early and make integration repeatable.", "ci", "ci-cd"],
    ["A containerized service passes unit tests. What gives stronger confidence before deployment?", ["Rebuild until the image is smaller", "An integration test using the image and representative dependencies", "Rename the image tag to stable", "Remove health checks"], [1], "Testing the deployable image with its dependencies checks configuration and integration beyond isolated code.", "docker"],
  ]),
  ...group("ai", "Mid", [2, 4, 7], [
    ["What does retrieval-augmented generation (RAG) add to a model request?", ["Relevant retrieved information", "A guarantee of perfect accuracy", "Unlimited context", "Automatic retraining of all model weights"], [0], "RAG supplies relevant material at request time. It improves grounding but still needs evaluation.", "ai", "rag"],
    ["What are embeddings useful for in a retrieval system?", ["Encrypting private documents", "Replacing access controls", "Representing content so semantic similarity can be compared", "Guaranteeing that every answer is correct"], [2], "Embeddings encode features into vectors that can support similarity search.", "ai", "embeddings"],
    ["A model proposes a tool call in a Java service. Which responsibilities remain with the application? Select all that apply.", ["Validate the arguments", "Execute every proposal without checks", "Authorize the requested action", "Trust model text as executable code"], [0, 2], "The application controls execution. Validate and authorize a proposed call before allowing effects.", "tools", "tool-calling"],
  ]),
  ...group("observability", "Mid", [2, 4, 7], [
    ["Which signal is best for tracking the rate of failed HTTP requests over time?", ["A metric", "A method name", "A Git branch", "A source file's length"], [0], "Metrics summarize numeric behavior over time, including request counts and error rates.", "observations"],
    ["A request travels through several services and becomes slow. What helps locate the delay?", ["A larger application logo", "Distributed traces with correlated spans", "Removing all timestamps", "Only counting source-code lines"], [1], "A trace follows work across boundaries; span durations reveal where time is spent.", "observations"],
    ["Which observability practices are useful? Select all that apply.", ["Include raw passwords in logs", "Correlate logs with trace identifiers", "Use an unbounded user ID label on every metric", "Track latency distributions and error rates"], [1, 3], "Correlated signals support diagnosis. Protect sensitive data and avoid unbounded metric label cardinality.", "observations"],
  ]),
  ...group("concurrency", "Senior", [3, 6, 9], [
    ["Two threads update shared mutable state without coordination. What risk does this introduce?", ["Automatic serialization", "A race condition", "Guaranteed faster execution", "Compile-time deadlock detection"], [1], "Interleaved operations can violate assumptions about reads and writes to shared state.", "threads", "multithreading"],
    ["Which approaches can reduce shared-state concurrency bugs? Select all that apply.", ["Prefer immutable values where practical", "Assume reads and writes always happen in order", "Use appropriate synchronization or atomic operations", "Add arbitrary sleeps as a correctness guarantee"], [0, 2], "Reduce shared mutation and coordinate the state that must remain shared. Timing delays are not synchronization.", "threads"],
    ["A Java service performs many blocking network calls. What is a reasonable expectation of virtual threads?", ["They make CPU-bound calculations inherently faster", "They remove downstream capacity limits", "They can support many waiting tasks, while downstream concurrency still needs bounds", "They eliminate the need for timeouts"], [2], "Virtual threads reduce the cost of waiting tasks. They do not create CPU or database capacity; keep timeouts and limits.", "virtual"],
  ]),
  ...group("distributed", "Senior", [3, 6, 10], [
    ["A consumer may receive the same event more than once. What property helps it process safely?", ["Idempotency", "Longer variable names", "No error handling", "Random partition keys"], [0], "An idempotent handler prevents a repeated event from causing a repeated business effect.", "kafka", "idempotency"],
    ["Which statements about Kafka ordering and consumption are correct? Select all that apply.", ["Ordering is defined within a partition", "All partitions provide one global order", "Retries or replay can require duplicate-safe processing", "A consumer can ignore failure recovery"], [0, 2], "Partitioning defines ordering boundaries. Consumers must account for replay and their delivery guarantees.", "kafka"],
    ["An order service must update its database and reliably publish an event. What does a transactional outbox address?", ["It makes all remote calls one local transaction", "It records the change and pending event atomically, then relays with duplicate handling", "It removes the need for consumers", "It guarantees every external side effect happens exactly once"], [1], "A local transaction records both state and an event to relay. Relay retries still need idempotent consumers.", "outbox", "outbox"],
  ]),
  ...group("performance", "Senior", [3, 6, 9], [
    ["What does Java garbage collection primarily reclaim?", ["All files on disk", "Memory occupied by unreachable objects", "Every object after each method call", "Open database transactions"], [1], "GC reclaims heap memory from unreachable objects. It does not replace explicit management of external resources.", "gc", "garbage-collector"],
    ["Which questions matter before caching a frequently read value? Select all that apply.", ["How stale the value may be", "Whether cache keys have the correct scope", "Whether caching makes authorization unnecessary", "Whether the cache has infinite memory"], [0, 1], "Define freshness and key boundaries. Caches consume finite resources and must preserve isolation.", "cache"],
    ["A Java service slows down under load. What is the best first step before changing GC settings?", ["Choose random JVM flags", "Disable all monitoring", "Measure CPU, allocations, GC and dependency latency under representative load", "Rewrite every class"], [2], "Profile first to distinguish CPU, allocation, GC and external bottlenecks. Tune against observed evidence.", "jfr", "jvm"],
  ]),
  ...group("operations", "Senior", [3, 6, 9], [
    ["What does a readiness probe communicate to Kubernetes?", ["Whether a container image was free", "Whether a Pod should receive service traffic", "Whether all database migrations are reversible", "Whether developers are logged in"], [1], "Readiness controls participation in Service traffic; a running process may not yet be ready.", "k8s"],
    ["Which choices improve resilience when a downstream service is slow? Select all that apply.", ["Bound request time with timeouts", "Retry instantly forever", "Use bounded retries with backoff where the operation is safe to retry", "Allow an unlimited queue of pending requests"], [0, 2], "Bound waiting and retries to prevent overload. Retried operations must account for duplicate effects.", "retry"],
    ["A shared database briefly fails. Why can restarting every API Pod on a dependency-based liveness failure be harmful?", ["It automatically repairs the database", "It guarantees no requests are lost", "It can create restart storms without repairing the dependency", "It makes readiness probes unnecessary"], [2], "Liveness restarts should target recoverable local failure. Shared dependency outages can otherwise cascade into restart storms.", "k8s"],
  ]),
  ...group("agents", "Senior", [3, 6, 10], [
    ["What is an evaluation set useful for when changing an AI application?", ["Comparing behavior on representative cases", "Proving it can never fail", "Replacing all access controls", "Making every model response identical"], [0], "A stable set of representative tasks lets you compare quality and regressions across changes.", "evaluation"],
    ["Which controls are useful for an agent that calls tools repeatedly? Select all that apply.", ["A bounded number of steps and cost budget", "Unlimited retries until the model stops", "Per-tool authorization and argument validation", "Allowing tools to bypass application permissions"], [0, 2], "Bound execution and enforce permissions at every tool boundary, including when using MCP-connected tools.", "tools", "mcp"],
    ["A cheaper model reduces cost but fails more important tasks. How should you assess the change?", ["Ship based only on price per token", "Ignore latency and retry costs", "Compare task success, safety, end-to-end latency and total cost on representative workloads", "Measure only response length"], [2], "Evaluate the whole system: retries, tool use, task outcomes, latency and cost. A cheaper call may make a task more expensive.", "evaluation"],
  ]),
];
