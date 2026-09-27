# Scenario: Cache stampede with conflicting hypotheses

Incident INC-2002 affected `catalog-api` on 2026-09-20. Request latency increased
from 90ms to 1.8s when the product catalog cache expired at 14:00 UTC.
Cache hit rate dropped from 96% to 12%, and database read throughput increased
fivefold.

An early note blamed a network provider because packet loss was observed in one
availability zone. A later dashboard review found no packet loss on the catalog
nodes. The evidence currently favors a cache stampede, but the network hypothesis
is not fully eliminated.

Recommended response: validate cache-key behavior, add request coalescing, and
compare database saturation with network telemetry before changing infrastructure.
