# NEXUS OAuth Setup Guide

Set these environment variables in your **Render** service dashboard
(Environment → Add Environment Variable), then redeploy.

```
BACKEND_URL=https://nexus-backend-bx18.onrender.com
FRONTEND_URL=https://nexus-frontend-five-swart.vercel.app
```

---

## Google OAuth

Two flows are available. Choose based on whether you have the client secret.

### Flow A — Redirect / Authorization Code (requires client secret)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
3. Application type: **Web application**
4. Authorized redirect URIs — add:
   ```
   https://nexus-backend-bx18.onrender.com/api/auth/google/callback
   http://localhost:8000/api/auth/google/callback
   ```
5. After saving, click the **client name** in the credentials list to open the detail page
6. The **Client secret** is shown there with a copy icon — or click **"Download JSON"**
   to get a file named `client_secret_....json` containing both values

**Render env vars:**
```
GOOGLE_CLIENT_ID=<your-client-id>
GOOGLE_CLIENT_SECRET=<your-client-secret>
```

### Flow B — Google Identity Services / GIS (client ID only, no secret needed)

The frontend renders Google's Sign In With Google button (GIS JavaScript library).
After the user consents, GIS returns a signed `credential` (JWT id_token) to the
frontend. The frontend POSTs this to the backend, which verifies the signature
against Google's public keys — no client secret is ever needed.

**Backend endpoint:** `POST /api/auth/google/token`
**Request body:** `{ "credential": "<id_token from GIS>" }`
**Response:** `{ "token": "<nexus-jwt>" }`

**Render env vars (Flow B only):**
```
GOOGLE_CLIENT_ID=<your-client-id>
```

**Frontend integration (add to your login page HTML):**
```html
<script src="https://accounts.google.com/gsi/client" async></script>
<div id="g_id_onload"
     data-client_id="YOUR_GOOGLE_CLIENT_ID"
     data-callback="handleGoogleCredential">
</div>
<div class="g_id_signin" data-type="standard"></div>

<script>
async function handleGoogleCredential(response) {
  const res = await fetch('https://nexus-backend-bx18.onrender.com/api/auth/google/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential: response.credential }),
  });
  const { token } = await res.json();
  localStorage.setItem('nexus_token', token);
  window.location.href = '/app';
}
</script>
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
