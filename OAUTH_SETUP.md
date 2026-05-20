# NEXUS OAuth Setup Guide

Set these environment variables in your **Render** service dashboard
(Environment → Add Environment Variable), then redeploy.

```
BACKEND_URL=https://nexus-backend-bx18.onrender.com
FRONTEND_URL=https://nexus-frontend-five-swart.vercel.app
```

---

## Google OAuth

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (or select existing)
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
4. Application type: **Web application**
5. Authorized redirect URIs — add:
   ```
   https://nexus-backend-bx18.onrender.com/api/auth/google/callback
   http://localhost:8000/api/auth/google/callback
   ```
6. Copy **Client ID** and **Client Secret**

**Render env vars:**
```
GOOGLE_CLIENT_ID=<your-client-id>
GOOGLE_CLIENT_SECRET=<your-client-secret>
```

---

## Microsoft OAuth

1. Go to [portal.azure.com](https://portal.azure.com)
2. **Azure Active Directory → App registrations → New registration**
3. Name: NEXUS
4. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**
5. Redirect URI: **Web** →
   ```
   https://nexus-backend-bx18.onrender.com/api/auth/microsoft/callback
   ```
6. After creation: **Certificates & secrets → New client secret** → copy the value
7. Copy **Application (client) ID** from the Overview page

**Render env vars:**
```
MICROSOFT_CLIENT_ID=<application-client-id>
MICROSOFT_CLIENT_SECRET=<client-secret-value>
```

---

## GitHub OAuth

1. Go to [github.com/settings/developers](https://github.com/settings/developers)
2. **OAuth Apps → New OAuth App**
3. Homepage URL: `https://nexus-frontend-five-swart.vercel.app`
4. Authorization callback URL:
   ```
   https://nexus-backend-bx18.onrender.com/api/auth/github/callback
   ```
5. Register, then **Generate a new client secret**

**Render env vars:**
```
GITHUB_CLIENT_ID=<your-client-id>
GITHUB_CLIENT_SECRET=<your-client-secret>
```

---

## Local Development

Add to `nexus-backend/.env`:
```
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
```

Add `http://localhost:8000/api/auth/*/callback` to each provider's redirect URI list.

---

## How it works

1. User clicks "Continue with Google" on the login/signup page
2. Browser is redirected to `GET /api/auth/google` on the backend
3. Backend redirects to Google's consent screen
4. After consent, Google redirects to `GET /api/auth/google/callback?code=...`
5. Backend exchanges code for access token, fetches user info
6. Backend finds or creates the user (links by email if account exists)
7. Backend issues a JWT and redirects to `{FRONTEND_URL}/auth/callback?token=<jwt>`
8. Frontend stores the JWT and redirects to `/app`

OAuth-created accounts are stored in the same `users` table.
Existing email/password accounts are linked automatically if the OAuth email matches.
