# Scenario: Database connection pool exhaustion

Incident INC-2001 affected `orders-api` on 2026-09-20 between 10:00 and 10:25 UTC.
The 5xx rate increased from 0.4% to 14% immediately after release `orders-7.4.0`.
Database connection pool utilization reached 100% while CPU stayed below 55%.
The on-call engineer rolled back the release at 10:18 UTC and error rates returned
to baseline within six minutes.

Evidence supports connection-pool exhaustion as the likely contributing cause.
Before changing pool size, verify connection leak metrics and reproduce the workload
in staging. Production rollback or configuration changes require service-owner
approval.
