# NightShift Fault Catalogue (25 Benchmark Faults)

**Document Version:** 1.0.0  
**Owner:** Person B (Brain & Trust)  
**Reviewer:** Person A (Systems & Proof)  
**Standard:** AI On-Call Engineer Architecture and 12-Day Execution Plan (Section 8 & Section 14, Task B2)

---

## 1. Executive Summary & Distribution

This catalogue defines the 25 benchmark incident scenarios for the NightShift autonomous on-call engineering system. Every scenario has **exactly one unambiguous ground-truth root cause**, a verifiable observable symptom, and a designated minimal fix with an assigned risk tier (`T0`, `T1`, `T2`, `T3`).

### Category Distribution
| Category | ID Range | Target Count | Description |
| :--- | :--- | :--- | :--- |
| **Code Bug in Deploy** | `fault_001` - `fault_008` | 8 | Real code defects introduced in deployments (null pointer, off-by-one, bad parser, unhandled exceptions) |
| **Config & Environment** | `fault_009` - `fault_012` | 4 | Misconfigured environment variables, bad pool parameters, expired credentials, broken flags |
| **Resource & Infrastructure** | `fault_013` - `fault_016` | 4 | Resource exhaustion: connection pool leaks, memory leaks, disk saturation, missing database index |
| **Cross-Service Cascade** | `fault_017` - `fault_020` | 4 | Multi-hop incidents: symptom appears in Gateway, root cause lies 2 hops downstream in Payments or DB |
| **Stretch & Postmortem Replays** | `fault_021` - `fault_025` | 5 | Real-world postmortem replays (Cloudflare regex, circuit breaker flapping, repeated incident for memory test) |
| **Total** | | **25** | **100% Ground Truth Specification** |

### Risk Tiers
- **T0 (Read-Only):** Safe non-destructive diagnostic actions (logs, metrics, git, service map).
- **T1 (Low Risk - Automated):** Config reverts, rollback of latest deployment, service restart.
- **T2 (Medium Risk - Automated with Canary):** Targeted code patch in worktree with isolated unit tests and canary verification.
- **T3 (High Risk - Human Approval Required):** Database schema alterations, infrastructure migrations, persistent data resets.

---

## 2. Category I: Code Bugs in Deployment (Faults 001 - 008)

### `fault_001_bad_deploy`
- **Title:** Unhandled null pointer in orders checkout VIP discount handler
- **Category:** `code`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261122_v1.0.1` (commit `c0ffee14a`)
- **Visible Symptoms:**
  - `POST /orders` error rate spikes from 0% to >30% within 30 seconds of deployment.
  - Gateway returns HTTP 500 / 502 for checkout requests.
  - Orders log shows `TypeError: 'NoneType' object is not subscriptable` at `discount['code']`.
- **Root Cause:** In `create_order()`, developer accessed `discount["code"]` assuming `discount` is always a dictionary, but normal orders without promo codes have `discount=None`.
- **Expected Fix:** Add defensive null check: `discount_code = discount.get("code") if isinstance(discount, dict) else None` or rollback to `v1.0.0`.
- **Expected Fix Type:** `patch` (or `rollback`)
- **Risk Tier:** `T2`

### `fault_002_off_by_one`
- **Title:** Off-by-one index error in orders history pagination
- **Category:** `code`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.2` (commit `a2b4c6e8`)
- **Visible Symptoms:**
  - `GET /orders?page=N` returns HTTP 500 when requesting the last page of customer order history.
  - Orders log shows `IndexError: list index out of range` in `paginate_records()`.
- **Root Cause:** Pagination slicing used `orders[start:end+1]` with inclusive boundary math that exceeded array bounds on boundary conditions.
- **Expected Fix:** Correct pagination slice bounds to `orders[start:end]` and check `if start >= len(orders)`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_003_wrong_status_code`
- **Title:** Payments service returns HTTP 200 with error body instead of HTTP 400/402
- **Category:** `code`
- **Target Service:** `payments`
- **Difficulty:** `medium`
- **Culprit Change:** `dep_20261123_v1.0.3` (commit `c3d5e7f9`)
- **Visible Symptoms:**
  - Orders service falsely marks failed transactions as `CONFIRMED`.
  - Financial reconciliation mismatch between Gateway and Payments ledger.
  - Prometheus shows 0% payment errors despite failing credit card charges.
- **Root Cause:** Payments handler caught card decline exceptions and returned HTTP 200 with `{"status": "DECLINED"}` rather than HTTP 402/400.
- **Expected Fix:** Return appropriate HTTP 400/402 status code and error schema when card is declined.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_004_bad_parsing`
- **Title:** Strict ISO datetime parser crashes on trailing 'Z' timestamps
- **Category:** `code`
- **Target Service:** `gateway`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.4` (commit `e4f6a8b0`)
- **Visible Symptoms:**
  - Gateway returns HTTP 400 / 500 on valid client checkout requests from mobile clients sending `2026-11-23T09:00:00Z`.
  - Gateway log shows `ValueError: time data '...' does not match format '%Y-%m-%dT%H:%M:%S%z'`.
- **Root Cause:** Replaced lenient ISO 8601 parsing (`datetime.fromisoformat()`) with a rigid `strptime` string format that rejects standard `Z` Zulu timezone designators.
- **Expected Fix:** Use `datetime.fromisoformat(ts.replace("Z", "+00:00"))` or Pydantic standard datetime coercion.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_005_unhandled_exception`
- **Title:** Uncaught ZeroDivisionError in bulk order discount calculator
- **Category:** `code`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.5` (commit `b5c7d9e1`)
- **Visible Symptoms:**
  - `POST /orders` fails with HTTP 500 when request contains promotional item with zero total item count.
  - Orders log records `ZeroDivisionError: division by zero` in `calculate_unit_discount()`.
- **Root Cause:** Calculated `discount_per_unit = total_discount / total_items` without guarding against `total_items == 0`.
- **Expected Fix:** Add guard clause: `discount_per_unit = (total_discount / total_items) if total_items > 0 else 0.0`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_006_wrong_timeout_value`
- **Title:** Microsecond timeout misconfiguration in downstream payments client
- **Category:** `code`
- **Target Service:** `orders`
- **Difficulty:** `medium`
- **Culprit Change:** `dep_20261123_v1.0.6` (commit `d6e8f0a2`)
- **Visible Symptoms:**
  - Orders service throws `httpx.TimeoutException` on 100% of payment attempts.
  - Orders latency drops to 5ms while error rate jumps to 100%.
  - Gateway logs HTTP 503 Service Unavailable for all orders.
- **Root Cause:** Developer configured `httpx.AsyncClient(timeout=0.005)` intended as 5 seconds, but httpx interprets raw floats as seconds, creating an impossible 5ms deadline.
- **Expected Fix:** Correct timeout parameter to `timeout=5.0`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_007_bad_sql_query`
- **Title:** SQL syntax error in customer order retrieval query
- **Category:** `code`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.7` (commit `f7a9b1c3`)
- **Visible Symptoms:**
  - `GET /orders` endpoint fails with HTTP 500 on all queries.
  - Postgres log reports `syntax error at or near "FORM"`.
- **Root Cause:** Raw SQL query string typo: `SELECT * FORM orders WHERE customer_id = %s`.
- **Expected Fix:** Correct typo from `FORM` to `FROM`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_008_broken_serialization`
- **Title:** Non-serializable Decimal object in payments audit log
- **Category:** `code`
- **Target Service:** `payments`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.8` (commit `a8b0c2d4`)
- **Visible Symptoms:**
  - `POST /process` throws HTTP 500 when logging payment metadata.
  - Payments log shows `TypeError: Object of type Decimal is not JSON serializable`.
- **Root Cause:** Switched currency amounts to `decimal.Decimal` for accuracy but passed dictionary directly to standard `json.dumps()` without float conversion or default serializer.
- **Expected Fix:** Convert Decimal to float (`float(amount)`) or provide `default=str` in JSON serialization.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

---

## 3. Category II: Config & Environment (Faults 009 - 012)

### `fault_009_wrong_env_var`
- **Title:** Invalid downstream payments service port in orders environment
- **Category:** `config`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `cfg_20261123_001` (env revision `e1a2b3`)
- **Visible Symptoms:**
  - Orders service cannot communicate with Payments; logs report `ConnectionRefusedError: [Errno 111] Connection refused on http://127.0.0.1:9999`.
  - `POST /orders` returns HTTP 503.
- **Root Cause:** `PAYMENTS_SERVICE_URL` environment variable was set to port 9999 instead of 8082.
- **Expected Fix:** Update `PAYMENTS_SERVICE_URL=http://127.0.0.1:8082` (or `http://payments:8082`).
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_010_expired_token`
- **Title:** Expired internal service mutual authentication token
- **Category:** `config`
- **Target Service:** `gateway`
- **Difficulty:** `medium`
- **Culprit Change:** `cfg_20261123_002` (token rotation)
- **Visible Symptoms:**
  - Gateway receives HTTP 401 Unauthorized from Orders service on every forwarded request.
  - Orders log records `InvalidToken: signature has expired`.
- **Root Cause:** Static secret token in Gateway environment configuration expired following scheduled secret rotation without updating the Gateway environment file.
- **Expected Fix:** Update Gateway config with valid rotated internal API secret key.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_011_wrong_pool_size`
- **Title:** Database connection pool size reduced to 1 under high traffic
- **Category:** `config`
- **Target Service:** `orders`
- **Difficulty:** `medium`
- **Culprit Change:** `cfg_20261123_003` (pool tuning)
- **Visible Symptoms:**
  - Orders latency p99 spikes from 20ms to >15,000ms.
  - Gateway requests time out with HTTP 504 Gateway Timeout.
  - Metrics show `db_pool_available = 0` continuously.
- **Root Cause:** Environment variable `DB_POOL_MAX` was set to 1 instead of 20, causing all concurrent database transactions to queue up sequentially.
- **Expected Fix:** Increase `DB_POOL_MAX=20` in config and reload service.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_012_bad_feature_flag`
- **Title:** Broken async audit queue feature flag activated prematurely
- **Category:** `config`
- **Target Service:** `orders`
- **Difficulty:** `medium`
- **Culprit Change:** `cfg_20261123_004` (feature flag toggle)
- **Visible Symptoms:**
  - Orders service crashes on checkout with `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379`.
  - Error rate jumps to 100%.
- **Root Cause:** Feature flag `ENABLE_ASYNC_AUDIT=true` was enabled before the Redis cache/queue infrastructure was provisioned.
- **Expected Fix:** Revert feature flag to `ENABLE_ASYNC_AUDIT=false`.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

---

## 4. Category III: Resource & Infrastructure (Faults 013 - 016)

### `fault_013_conn_pool_exhaustion`
- **Title:** Leaked database connection in order lookup query
- **Category:** `resource`
- **Target Service:** `orders`
- **Difficulty:** `medium`
- **Culprit Change:** `dep_20261123_v1.0.9` (commit `b1c3d5e7`)
- **Visible Symptoms:**
  - System functions normally for the first 30 requests, then degrades to 100% 500 errors.
  - Postgres metrics show `active_connections = max_connections`.
  - Log records `psycopg2.OperationalError: FATAL: remaining connection slots are reserved`.
- **Root Cause:** In `get_order()`, database connection was acquired directly from pool but omitted `finally: connection.close()`, leaking a connection slot on every lookup.
- **Expected Fix:** Wrap database query in context manager `with db.get_connection() as conn:` to ensure automatic release.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_014_memory_leak`
- **Title:** Unbounded global in-memory request cache causing OOM restart
- **Category:** `resource`
- **Target Service:** `gateway`
- **Difficulty:** `medium`
- **Culprit Change:** `dep_20261123_v1.0.10` (commit `d3e5f7a9`)
- **Visible Symptoms:**
  - Gateway container memory usage grows linearly until process is killed by OS OOM killer (Exit code 137).
  - Prometheus metric `process_resident_memory_bytes` rises monotonically.
- **Root Cause:** Global debug list `GLOBAL_REQUEST_HISTORY.append(request_data)` appends every request body indefinitely without maximum size or TTL.
- **Expected Fix:** Remove unbounded global accumulator or replace with fixed-size `collections.deque(maxlen=100)`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_015_disk_full`
- **Title:** Application log disk volume exhaustion
- **Category:** `resource`
- **Target Service:** `orders`
- **Difficulty:** `hard`
- **Culprit Change:** `infra_20261123_001` (log level debug)
- **Visible Symptoms:**
  - Orders service fails with HTTP 500 on write operations.
  - Orders log records `OSError: [Errno 28] No space left on device`.
  - System metrics show root/log partition at 100% utilization.
- **Root Cause:** Verbose DEBUG payload logging flooded the log volume combined with disabled log rotation.
- **Expected Fix:** Clear stale unrotated logs, re-enable log rotation, and restore log level to `INFO`.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_016_slow_query_missing_index`
- **Title:** Unindexed order customer_id search causing CPU spike and timeouts
- **Category:** `resource`
- **Target Service:** `orders`
- **Difficulty:** `medium`
- **Culprit Change:** `dep_20261123_v1.0.11` (commit `f5a7b9c1`)
- **Visible Symptoms:**
  - `GET /orders?customer_id=X` query latency jumps from 8ms to 4,200ms.
  - Gateway times out waiting for Orders response.
  - Postgres process CPU utilization spikes to 95%.
- **Root Cause:** Added customer search query against orders table (500k rows) without creating an index on `customer_id`, causing full sequential table scans.
- **Expected Fix:** Create index on `orders(customer_id)`.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T3`

---

## 5. Category IV: Cross-Service Incidents (Faults 017 - 020)

### `fault_017_symptom_gw_cause_payments`
- **Title:** Gateway checkout outage caused by faulty Payments service deploy
- **Category:** `cross_service`
- **Target Service:** `payments` (symptoms manifest at `gateway`)
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.12` (commit `e6f8a0b2`)
- **Visible Symptoms:**
  - Ingress Gateway alerts on `High5xxErrorRate` (45% error rate).
  - Orders service health is 200, but orders checkout requests fail.
  - Root error trace is found only in the Payments service logs.
- **Root Cause:** A deployment to the Payments service introduced a validation failure on `currency="USD"`, which rejected orders, cascading upward to the Gateway.
- **Expected Fix:** Follow service map upstream to identify Payments as culprit; patch Payments currency validator or rollback Payments service.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_018_retry_storm`
- **Title:** Aggressive gateway retry policy causing downstream collapse
- **Category:** `cross_service`
- **Target Service:** `gateway`
- **Difficulty:** `hard`
- **Culprit Change:** `cfg_20261123_005` (retry config update)
- **Visible Symptoms:**
  - Normal 10 rps ingress traffic triggers 120 rps internal traffic between Gateway and Orders.
  - Orders service CPU saturates and thread pool is depleted.
- **Root Cause:** Gateway retry policy was updated to retry every HTTP 5xx error 10 times with zero backoff delay, multiplying downstream load during transient glitches.
- **Expected Fix:** Update Gateway retry policy: maximum 2 retries with exponential backoff and jitter.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_019_upstream_schema_change`
- **Title:** Uncoordinated API contract field rename between Orders and Gateway
- **Category:** `cross_service`
- **Target Service:** `orders`
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.13` (commit `a7b9c1d3`)
- **Visible Symptoms:**
  - Gateway returns `422 Unprocessable Entity` or `502 Bad Gateway` on order creation.
  - Gateway log indicates `KeyError: 'total'` while Orders log shows successful order processing.
- **Root Cause:** Orders service was deployed with a schema change renaming `total` to `total_amount_cents` without a backwards-compatible transition period for the Gateway.
- **Expected Fix:** Patch Orders service response schema to retain `total` for backwards compatibility.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_020_dependency_timeout_cascade`
- **Title:** External webhook latency causing thread pool starvation across services
- **Category:** `cross_service`
- **Target Service:** `payments`
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.14` (commit `c9d1e3f5`)
- **Visible Symptoms:**
  - Payments latency rises to 15 seconds; Orders and Gateway worker threads become exhausted waiting for sockets.
  - All services report HTTP 504 timeouts.
- **Root Cause:** Synchronous HTTP call to external notification webhook inside payment processing loop without an asynchronous queue or timeout cap.
- **Expected Fix:** Make webhook notification asynchronous via background task and enforce strict 1.0s timeout.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

---

## 6. Category V: Stretch Scenarios & Postmortem Replays (Faults 021 - 025)

### `fault_021_cloud_postmortem_cloudflare_regex`
- **Title:** Replay of Cloudflare 2019 CPU exhaustion regex catastrophe
- **Category:** `stretch`
- **Target Service:** `gateway`
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.15` (commit `e1f3a5b7`)
- **Visible Symptoms:**
  - Gateway CPU reaches 100% on a single core immediately upon matching user-agent string.
  - Ingress requests hang indefinitely and time out.
- **Root Cause:** Vulnerable regular expression with nested quantifiers `.*(?:.*=.*)*$` exhibiting exponential backtracking ($O(2^n)$) on malformed user headers.
- **Expected Fix:** Replace backtracking regex with atomic linear string matching or DFA-based regex pattern.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_022_cloud_postmortem_aws_dynamo_lease`
- **Title:** Replay of AWS DynamoDB metadata lease expiration split-brain
- **Category:** `stretch`
- **Target Service:** `orders`
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.16` (commit `a2c4e6f8`)
- **Visible Symptoms:**
  - Orders service intermittently rejects updates with `StaleLeaseError`.
  - Service flaps between healthy and unhealthy every 60 seconds.
- **Root Cause:** Background lease heartbeat renewal thread threw an unhandled exception and died silently, leaving lease un-renewed while main thread assumed lease was valid.
- **Expected Fix:** Restart heartbeat thread on failure and wrap lease check in automatic renewal try-catch block.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_023_repeated_incident_memory_test`
- **Title:** Repeated VIP discount null pointer incident for memory benchmark
- **Category:** `stretch`
- **Target Service:** `orders`
- **Difficulty:** `easy`
- **Culprit Change:** `dep_20261123_v1.0.17` (commit `b3d5f7a9`)
- **Visible Symptoms:**
  - Identical symptoms to `fault_001_bad_deploy`: `TypeError: 'NoneType' object is not subscriptable` in orders discount check.
- **Root Cause:** Regression deploy re-introducing identical null pointer bug from `fault_001`.
- **Benchmark Objective:** Demonstrates Person B memory component. Agent should query `search_past_incidents()`, find `inc_20261122_001` at rank 1, and produce verified fix in <30 seconds (50% reduction in MTTR vs first occurrence).
- **Expected Fix:** Apply defensive null check retrieved directly from past incident solution.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

### `fault_024_circuit_breaker_half_open_flap`
- **Title:** Circuit breaker threshold flap causing 50% dropped requests
- **Category:** `stretch`
- **Target Service:** `gateway`
- **Difficulty:** `hard`
- **Culprit Change:** `cfg_20261123_006` (resilience config update)
- **Visible Symptoms:**
  - Error rate oscillates wildly between 0% and 50% in a 10-second square wave pattern.
  - Gateway logs rapid transitions: `CLOSED -> OPEN -> HALF_OPEN -> OPEN`.
- **Root Cause:** `failure_threshold` was set to 1 and `half_open_success_threshold` set to 10 with a 2-second sleep, causing a single transient probe to immediately re-trip the breaker.
- **Expected Fix:** Tune circuit breaker: `failure_threshold=5`, `half_open_success_threshold=3`, cooldown `sleep_window=10s`.
- **Expected Fix Type:** `config`
- **Risk Tier:** `T1`

### `fault_025_poison_pill_payload`
- **Title:** Unhandled Unicode zero-width space in order item name
- **Category:** `stretch`
- **Target Service:** `orders`
- **Difficulty:** `hard`
- **Culprit Change:** `dep_20261123_v1.0.18` (commit `c4e6a8b0`)
- **Visible Symptoms:**
  - Only specific order requests with particular customer item names crash; general health check remains 200.
  - Postgres logs `InvalidByteSequence: zero-length character string not allowed in identifier`.
- **Root Cause:** Order item sanitizer failed to sanitize zero-width non-breaking spaces (`\ufeff` / `\u200b`), causing downstream database driver encoding crash.
- **Expected Fix:** Sanitize input item string using `unicodedata.normalize('NFKD', item).encode('ascii', 'ignore')` or strip zero-width characters.
- **Expected Fix Type:** `patch`
- **Risk Tier:** `T2`

---

## 7. Fault Catalogue Summary Matrix

| ID | Title | Category | Service | Difficulty | Fix Type | Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `fault_001` | Bad Deploy: VIP Discount Null Pointer | Code | orders | Easy | Patch | T2 |
| `fault_002` | Off-by-One Pagination Index Error | Code | orders | Easy | Patch | T2 |
| `fault_003` | Wrong Status Code 200 on Decline | Code | payments | Medium | Patch | T2 |
| `fault_004` | Strict ISO Parser Rejects Zulu Timestamps | Code | gateway | Easy | Patch | T2 |
| `fault_005` | ZeroDivisionError in Unit Discount | Code | orders | Easy | Patch | T2 |
| `fault_006` | Downstream Timeout Set to 5 Milliseconds | Code | orders | Medium | Patch | T2 |
| `fault_007` | SQL Typo "FORM" in Customer Lookup | Code | orders | Easy | Patch | T2 |
| `fault_008` | Broken Decimal JSON Serialization | Code | payments | Easy | Patch | T2 |
| `fault_009` | Wrong Payments Port in Environment (9999) | Config | orders | Easy | Config | T1 |
| `fault_010` | Expired Internal Service Auth Token | Config | gateway | Medium | Config | T1 |
| `fault_011` | DB Connection Pool Size Set to 1 | Config | orders | Medium | Config | T1 |
| `fault_012` | Unprovisioned Redis Feature Flag Enabled | Config | orders | Medium | Config | T1 |
| `fault_013` | Connection Slot Leak in Order Lookup | Resource | orders | Medium | Patch | T2 |
| `fault_014` | Unbounded Global List Memory Leak (OOM) | Resource | gateway | Medium | Patch | T2 |
| `fault_015` | Disk Volume Full from Verbose Debug Logs | Resource | orders | Hard | Config | T1 |
| `fault_016` | Missing DB Index on customer_id | Resource | orders | Medium | Patch | T3 |
| `fault_017` | Gateway 502 Outage Caused by Payments Deploy | Cross-Service | payments | Hard | Patch | T2 |
| `fault_018` | Infinite Retry Storm Multiplies Load 12x | Cross-Service | gateway | Hard | Config | T1 |
| `fault_019` | API Field Rename Without Backwards Compatibility | Cross-Service | orders | Hard | Patch | T2 |
| `fault_020` | External Synchronous Webhook Starvation | Cross-Service | payments | Hard | Patch | T2 |
| `fault_021` | Cloudflare 2019 Replay: Regex CPU Backtracking | Stretch | gateway | Hard | Patch | T2 |
| `fault_022` | AWS DynamoDB Replay: Heartbeat Lease Expiry | Stretch | orders | Hard | Patch | T2 |
| `fault_023` | Repeated Incident Memory Benchmark (v1.0.1) | Stretch | orders | Easy | Patch | T2 |
| `fault_024` | Circuit Breaker Rapid Oscillation Flapping | Stretch | gateway | Hard | Config | T1 |
| `fault_025` | Poison Pill Unicode Zero-Width Byte Crash | Stretch | orders | Hard | Patch | T2 |
