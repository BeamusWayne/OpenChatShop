# Load Test Baseline

## Baseline Targets

| Metric | Target |
|--------|--------|
| P99 latency | < 2s |
| Throughput | > 100 RPS |
| Error rate | < 0.1% |

## Running

```bash
# Web UI mode
locust -f tests/load/locustfile.py --host http://localhost:8000

# Headless mode (CI)
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --headless --users 200 --spawn-rate 10 --run-time 60s
```

## User Classes

| Class | Behavior |
|-------|----------|
| `ChatUser` | Random messages across 8 intent categories |
| `OrderQuerier` | Focused order-status queries (ORD-001) |
| `ProductSearcher` | Focused product-search queries (laptops) |
| `MixedWorkload` | 70% chat + 20% order + 10% search |
