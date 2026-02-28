# Task 2: User and Audit Tables Provisioning Record

**Provisioned:** 2026-02-28
**AWS Account:** 842387632939
**Region:** us-east-1

## Tables Created

### wafr-users
- **ARN:** arn:aws:dynamodb:us-east-1:842387632939:table/wafr-users
- **Partition Key:** user_id (S)
- **Sort Key:** None
- **Billing Mode:** PAY_PER_REQUEST
- **GSI:** email-index (PK: email, no SK, Projection: ALL)
- **TTL:** Not configured (per locked decision — user records kept indefinitely)
- **PITR:** ENABLED

### wafr-audit-log
- **ARN:** arn:aws:dynamodb:us-east-1:842387632939:table/wafr-audit-log
- **Partition Key:** user_id (S)
- **Sort Key:** timestamp_session_id (S) — underscore used (not `#`; hash is reserved in DynamoDB expression syntax)
- **Billing Mode:** PAY_PER_REQUEST
- **GSI:** session_id-timestamp-index (PK: session_id, SK: timestamp, Projection: ALL)
- **TTL:** Not configured (per locked decision — audit trails kept indefinitely)
- **PITR:** ENABLED

## Design Notes

- Sort key for wafr-audit-log uses `timestamp_session_id` (underscore separator) not `timestamp#session_id`
  as `#` is a reserved character in DynamoDB expression syntax (Open Question 3 from research)
- Application code in Phase 2 will write composite value as formatted string (e.g., `"2026-02-28T12:00:00Z_sess-123"`)

## Verification Status

- [x] Both tables ACTIVE
- [x] PAY_PER_REQUEST billing
- [x] Correct GSIs with proper key schemas
- [x] No TTL configured (correct per locked decision)
- [x] PITR enabled on both tables
