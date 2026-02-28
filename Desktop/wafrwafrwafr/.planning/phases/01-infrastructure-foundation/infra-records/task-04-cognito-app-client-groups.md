# Task 4: Cognito App Client and Groups Provisioning Record

**Provisioned:** 2026-02-28
**AWS Account:** 842387632939
**Region:** us-east-1

## App Client Created

### wafr-app-client
- **Client ID:** 65fis729feu3lr317rm6oaue5s
- **User Pool ID:** us-east-1_U4ugKPUrh
- **Client Secret:** NONE (public client — required for Amplify frontend)
- **Access Token Validity:** 1 hour
- **Token Validity Units:** AccessToken=hours
- **Explicit Auth Flows:**
  - ALLOW_USER_SRP_AUTH (Amplify default, most secure)
  - ALLOW_REFRESH_TOKEN_AUTH
  - NOTE: ALLOW_USER_PASSWORD_AUTH intentionally excluded (sends plaintext password)

## User Groups Created

### WafrTeam
- **Group Name:** WafrTeam
- **Description:** Internal WAFR team members with full access
- **User Pool:** us-east-1_U4ugKPUrh

### WafrClients
- **Group Name:** WafrClients
- **Description:** External WAFR clients with limited access
- **User Pool:** us-east-1_U4ugKPUrh

## Critical Output Values for Plan 01-03

These values must be stored in Secrets Manager by Plan 01-03:

| Key | Value |
|-----|-------|
| COGNITO_USER_POOL_ID | us-east-1_U4ugKPUrh |
| COGNITO_APP_CLIENT_ID | 65fis729feu3lr317rm6oaue5s |

## Verification Status

- [x] App Client exists with no client secret
- [x] Auth flows: ALLOW_USER_SRP_AUTH + ALLOW_REFRESH_TOKEN_AUTH only
- [x] No ALLOW_USER_PASSWORD_AUTH (plaintext password flow excluded)
- [x] Access token validity: 1 hour
- [x] WafrTeam group created
- [x] WafrClients group created
