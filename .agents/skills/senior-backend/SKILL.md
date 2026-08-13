---
name: "senior-backend"
description: Designs and implements backend systems including REST APIs, microservices, database architectures, authentication flows, and security hardening. Use when the user asks to "design REST APIs", "optimize database queries", "implement authentication", "build microservices", "review backend code", "set up GraphQL", "handle database migrations", or "load test APIs". Covers Node.js/Express/Fastify development, PostgreSQL optimization, API security, and backend architecture patterns.
---

# Senior Backend Engineer

Backend development patterns, API design, database optimization, and security practices.

---

## Backend Development Workflows

### API Design Workflow

Use when designing a new API or refactoring existing endpoints.

**Step 1: Define resources and operations**
```yaml
# openapi.yaml
openapi: 3.0.3
info:
  title: User Service API
  version: 1.0.0
paths:
  /users:
    get:
      summary: List users
      parameters:
        - name: "limit"
          in: query
          schema:
            type: integer
            default: 20
    post:
      summary: Create user
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateUser'
```

**Step 2: Implement business logic with validation**
```typescript
import { z } from 'zod';

const CreateUserSchema = z.object({
  email: z.string().email().max(255),
  name: z.string().min(1).max(100),
  age: z.number().int().positive().optional()
});
```

---

### Database Optimization Workflow

Use when queries are slow or database performance needs improvement.

**Step 1: Identify slow queries**
```sql
EXPLAIN ANALYZE SELECT * FROM orders
WHERE user_id = 123
ORDER BY created_at DESC
LIMIT 10;
-- Look for: Seq Scan (bad), Index Scan (good)
```

**Step 2: Apply index strategy**
```sql
-- Single column (equality lookups)
CREATE INDEX idx_users_email ON users(email);

-- Composite (multi-column queries)
CREATE INDEX idx_orders_user_status ON orders(user_id, status);

-- Partial (filtered queries)
CREATE INDEX idx_orders_active ON orders(created_at) WHERE status = 'active';

-- Covering (avoid table lookup)
CREATE INDEX idx_users_email_name ON users(email) INCLUDE (name);
```

---

### Security Hardening Workflow

Use when preparing an API for production or after a security review.

**Step 1: Review authentication setup**
```typescript
const jwtConfig = {
  secret: process.env.JWT_SECRET,  // Must be from env, never hardcoded
  expiresIn: '1h',                 // Short-lived tokens
  algorithm: 'RS256'               // Prefer asymmetric
};
```

**Step 2: Add rate limiting**
```typescript
import rateLimit from 'express-rate-limit';

const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,  // 15 minutes
  max: 100,                   // 100 requests per window
  standardHeaders: true,
  legacyHeaders: false,
});
app.use('/api/', apiLimiter);
```

**Step 3: Validate all inputs**
- Use schema validation (Zod, Pydantic, etc.) on every endpoint
- Sanitize output to prevent XSS
- Parameterize all SQL queries

**Step 4: Review security headers**
```typescript
import helmet from 'helmet';
app.use(helmet({
  contentSecurityPolicy: true,
  hsts: { maxAge: 31536000, includeSubDomains: true },
}));
```

---

## Common Patterns Quick Reference

### REST API Response Format
```json
{
  "data": { "id": 1, "name": "John" },
  "meta": { "requestId": "abc-123" }
}
```

### Error Response Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid email format",
    "details": [{ "field": "email", "message": "must be valid email" }]
  },
  "meta": { "requestId": "abc-123" }
}
```

### HTTP Status Codes
| Code | Use Case |
|------|----------|
| 200 | Success (GET, PUT, PATCH) |
| 201 | Created (POST) |
| 204 | No Content (DELETE) |
| 400 | Validation error |
| 401 | Authentication required |
| 403 | Permission denied |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

## Assumptions and Verifiable Success Criteria (Karpathy discipline)

Before this skill scaffolds, recommends a pattern, or modifies a schema, the following assumptions MUST be surfaced. If any are unknown, stop and ask.

1. **Read/write ratio + one-year p99 QPS** — drives DB, cache, queue, and partitioning choices.
2. **Tenancy model** — single-tenant, shared multi-tenant, isolated multi-tenant.
3. **Data sensitivity tier** — public / internal / PII / PHI / PCI.
4. **SLO + named error-budget consumer** — no SLO = no reliability work prioritization.

**Verifiable success criteria** — every recommendation must include:
- Latency targets (p50, p95, p99 in ms)
- Uptime / SLO target
- RPO + RTO

If any of those three is not stated, the recommendation is incomplete.

---

## Forcing-question library

Before locking any backend decision, walk these seven forcing questions:

1. Read/write ratio + p99 QPS forecast?
2. Tenancy model — single / shared / isolated?
3. Sync / async / event-driven — default + exceptions?
4. Data sensitivity tier — PII / PHI / PCI?
5. Monolith / modular monolith / microservices — team-size justification?
6. RPO + RTO?
7. SLO + named error-budget consumer?

One question per turn. Always recommend the answer with cited rationale. If a kill criterion trips, stop — don't scaffold around an unresolved gap.
