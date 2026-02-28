# Task 1: Session Tables Provisioning Record

**Provisioned:** 2026-02-28
**AWS Account:** 842387632939
**Region:** us-east-1

## Tables Created

### wafr-sessions
- **ARN:** arn:aws:dynamodb:us-east-1:842387632939:table/wafr-sessions
- **Partition Key:** session_id (S)
- **Sort Key:** created_at (S)
- **Billing Mode:** PAY_PER_REQUEST
- **GSI:** user_id-created_at-index (PK: user_id, SK: created_at, Projection: ALL)
- **TTL:** ENABLED on expires_at attribute
- **PITR:** ENABLED

### wafr-review-sessions
- **ARN:** arn:aws:dynamodb:us-east-1:842387632939:table/wafr-review-sessions
- **Partition Key:** session_id (S)
- **Sort Key:** item_id (S)
- **Billing Mode:** PAY_PER_REQUEST
- **GSI:** status-created_at-index (PK: status, SK: created_at, Projection: ALL)
- **TTL:** ENABLED on expires_at attribute
- **PITR:** ENABLED

## Verification Status

- [x] Both tables ACTIVE
- [x] PAY_PER_REQUEST billing
- [x] Correct GSIs with proper key schemas
- [x] TTL enabled on expires_at (365-day TTL will be set by application at write time)
- [x] PITR enabled on both tables
