# NightShift: 3 Public Postmortems for Stretch Benchmark Replays

**Author:** Person B (Brain & Trust)  
**Task:** Day 1 Task B4  
**Purpose:** Deep technical analysis of three historic real-world production outages used to design, benchmark, and evaluate NightShift's root-cause analysis (RCA) and autonomous remediation capabilities on complex stretch faults (Faults 21, 22, and 23).

---

## Postmortem 1: Cloudflare Global Outage (July 2, 2019)
**Category:** Stretch Code / Regex CPU Exhaustion  
**Mapped NightShift Fault:** `fault_021_cloudflare_regex_cpu`  
**Official Reference:** [Cloudflare Outage Postmortem (July 2, 2019)](https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/)

### 1. Incident Summary
At 13:42 UTC on July 2, 2019, an automated deployment of a new Web Application Firewall (WAF) managed rule aimed at detecting Cross-Site Scripting (XSS) deployed an unanchored regular expression containing nested repetitions. The regex caused catastrophic backtracking ($O(2^n)$ time complexity) on incoming HTTP request headers. CPU utilization spiked to 100% across all edge proxies globally, dropping Cloudflare's served traffic by ~82% for 27 minutes.

### 2. Root Cause & Technical Mechanism
The offending regular expression was:
```regex
(?:(?:\"|'|\]|\}|\\d|(?:true|false|null)|[a-z#_\\-\\$:|]+)\\s*\\+?\\s*)+
```
- **Flaw:** Nested quantifier patterns `(...)+` operating over overlapping character sets without boundary anchoring.
- When evaluated against input containing unclosed strings or malformed syntax, the NFA regex engine explored exponential permutation branches, starving proxy worker threads of CPU cycles.
- Because the regex was evaluated in the core HTTP request parsing pipeline (Lua/Nginx), the entire gateway proxy became unresponsive, triggering cascade timeouts upstream and downstream.

### 3. Symptoms & Telemetry Profile
- **CPU Metrics:** Core CPU utilization jumped instantaneously from 25% baseline to 100% across all cores.
- **Latency Metrics:** p95 and p99 latency spiked from 15ms to 30,000ms (timeout threshold).
- **HTTP Status:** Edge proxies returned HTTP 502 Bad Gateway; gateway upstream error rate reached 82%.
- **Logs:** Thread starvation warnings and gateway timeout error logs: `upstream timed out (110: Connection timed out) while reading response header from upstream`.

### 4. NightShift Microservice Reproduction
- **Target Component:** `target-app/services/gateway`
- **Injection:** Deploy a routing filter / authorization header validator with nested backtracking regex:
  ```python
  import re
  TOKEN_REGEX = re.compile(r"([a-zA-Z0-9]+_?)+$")
  ```
- **Symptom:** Gateway event loop hangs; CPU pegged at 100%; incoming client requests return 504 / 502.
- **NightShift Diagnosis Expectations:**
  1. Detect CPU saturation via `query_metrics("process_cpu_seconds_total")`.
  2. Identify the culprit deploy in `list_changes` within the last 15 minutes.
  3. Inspect `git_diff` highlighting the unanchored regex pattern.
  4. Formulate top-1 hypothesis: `category="code"`, citing CPU metric and regex diff evidence.
  5. Propose fix: Rollback deploy (T1) or replace with anchored, non-backtracking regex (T2).

---

## Postmortem 2: AWS DynamoDB US-East-1 Outage (September 20, 2015)
**Category:** Stretch Resource / Cascading Lease Expiration & Metadata Storm  
**Mapped NightShift Fault:** `fault_022_aws_dynamodb_lease_split_brain`  
**Official Reference:** [AWS DynamoDB Incident Report (September 20, 2015)](https://aws.amazon.com/message/5463/)

### 1. Incident Summary
On September 20, 2015, Amazon DynamoDB experienced a severe multi-hour degradation in US-East-1 impacting EC2, S3, and hundreds of downstream AWS services. The failure originated in the DynamoDB storage cluster's internal partition membership and lease renewal system.

### 2. Root Cause & Technical Mechanism
- Storage nodes continuously maintain partition ownership leases with an internal metadata service.
- Transient network packet loss increased the latency of lease renewal transactions.
- Storage nodes failed to renew their leases before their timeouts elapsed, prompting them to drop partition ownership.
- All storage nodes simultaneously re-requested partition memberships from the metadata service in an unbounded retry storm.
- The metadata service's connection pool became completely saturated (pool exhaustion), preventing any node from renewing leases and leading to widespread cluster unavailability.

### 3. Symptoms & Telemetry Profile
- **Connection Metrics:** Storage connection pool active connections pinned at 100% capacity; queue depth surged.
- **HTTP Status:** Surge in HTTP 503 Service Unavailable and 500 Internal Errors.
- **Logs:** Continuous timeouts waiting for database connection pool acquisition:
  `ConnectionTimeout: Timeout waiting for connection from pool after 5000ms`.
- **System Health:** CPU utilization remained moderate, but request queue length grew unbounded until memory was exhausted.

### 4. NightShift Microservice Reproduction
- **Target Component:** `target-app/services/orders` + `target_db` (Postgres / SQLite)
- **Injection:** Simulate metadata lease timeout storm by setting connection pool acquisition timeout to 100ms with unbounded retry loops in `target-app/services/orders/db.py`:
  ```python
  POOL_SIZE = 2
  ACQUISITION_TIMEOUT = 0.1
  ```
- **Symptom:** Orders API throws `PoolAcquisitionTimeoutError`; HTTP 500 / 503 error rate reaches 45%.
- **NightShift Diagnosis Expectations:**
  1. Query error logs highlighting `connection acquisition timeout`.
  2. Inspect connection pool saturation metrics (`db_connection_pool_active`).
  3. Recognize that database process is alive, but client connection queue is bottlenecked.
  4. Propose remediation: Exponential backoff with jitter on retries (T1/T2) and expanding connection pool limit.

---

## Postmortem 3: GitLab.com Database Outage (January 31, 2017)
**Category:** Stretch Cross-Service / Replication Desynchronization & Stale Failover  
**Mapped NightShift Fault:** `fault_023_repeated_incident_memory` (and replication failover)  
**Official Reference:** [GitLab 2017 Postmortem on Database Outage](https://about.gitlab.com/blog/2017/02/01/gitlab-dot-com-database-incident/)

### 1. Incident Summary
On January 31, 2017, GitLab.com suffered an 18-hour outage resulting in the loss of 6 hours of production database data. Under heavy spam traffic, PostgreSQL replication between the primary and secondary nodes desynchronized. Efforts to resynchronize the cluster encountered locks, stale state, and manual human error during recovery.

### 2. Root Cause & Technical Mechanism
- Secondary database node fell substantially behind the primary in write-ahead log (WAL) replication due to sudden write spike.
- Replication lag crossed the threshold where streaming replication aborted.
- Primary node accumulated transaction locks and WAL segments, degrading write throughput.
- When an engineer attempted to clean up the secondary node and resynchronize using `pg_basebackup`, confusion around configuration paths led to an irreversible directory removal on the active primary node.
- Backup validation mechanisms had not been tested against production data volume.

### 3. Symptoms & Telemetry Profile
- **Replication Lag Metric:** `pg_stat_replication.byte_lag` exceeded 10 GB.
- **API Status:** Write operations (`POST /projects`, `POST /issues`) failed with 500 and 504 gateway timeouts.
- **Logs:** `FATAL: terminating connection due to conflict with recovery` and `canceling statement due to lock timeout`.

### 4. NightShift Microservice Reproduction
- **Target Component:** `target-app/services/orders` and `orders_db`
- **Injection:** Simulate replication lag or read-only replica desynchronization where read queries succeed but transactional order commits hang on exclusive lock timeouts:
  ```python
  # Simulates stale exclusive lock holding table during order placement
  db.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
  ```
- **Symptom:** Orders creation hangs until gateway times out (504); read endpoints continue returning 200 OK.
- **NightShift Diagnosis Expectations:**
  1. Cross-service analysis: identify that Gateway 504 is caused by Orders service transaction hang, not gateway bugs.
  2. Differentiate between read health (200 OK) and write health (timeout).
  3. Query `search_past_incidents` to retrieve identical lock-contention pattern from NightShift institutional memory.
  4. Propose remediation: Terminate blocking lock query or rollback uncommitted transaction without manual destructive actions.

---

## Benchmark Evaluation Matrix for Stretch Replays

| Outage Replay | NightShift Fault ID | Ground-Truth Category | Key Symptom | Required Evidence | Minimal Fix Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cloudflare 2019** | `fault_021_cloudflare_regex_cpu` | `code` | 100% CPU, 502 Bad Gateway | `[ev_metric_cpu]`, `[ev_diff_regex]` | Rollback deploy `dep_waf_v1` (T1) |
| **AWS DynamoDB 2015** | `fault_022_aws_dynamodb_lease_split_brain` | `resource` | 503 Pool Exhaustion, Timeout | `[ev_log_timeout]`, `[ev_metric_pool]` | Expand pool & add jitter (T1) |
| **GitLab 2017** | `fault_023_repeated_incident_memory` | `cross_service` | 504 Write Hang, Lock Conflict | `[ev_log_lock]`, `[ev_past_incident]` | Release stale lock query (T2) |
