# NEXUS Browser Extension — Roadmap

## Purpose

The NEXUS browser extension lets users save any webpage, article, video, or tool directly
to their personal NEXUS library without leaving the browser. It complements the web app by
removing friction: one click saves the current tab, extracts selected text, and triggers
AI analysis on the backend.

---

## Save Current Tab — Flow

1. User clicks the NEXUS extension icon (or uses keyboard shortcut).
2. Extension reads the current tab: `url`, `title`, and optionally `document.getSelection()`.
3. Extension sends a `POST /api/extension/save` request with the user's JWT in the
   `Authorization: Bearer <token>` header.
4. Backend validates the JWT, runs content safety check, runs AI analysis, upserts into
   ChromaDB, saves to `sites` table under `user_id`, and auto-assigns to a collection.
5. Extension shows a brief success toast ("Saved to NEXUS") or error badge.

---

## Auth / Token Handling

- On first use, the extension opens the NEXUS web app login page in a new tab.
- After login, the web app stores the JWT in `localStorage` (`nexus-token`) **and** a cookie.
- The extension reads the token from storage: `chrome.storage.local.get('nexus-token')`.
- The web app must call `chrome.storage.local.set({ 'nexus-token': token })` after login
  (requires the extension ID to be allowlisted, or uses a shared `chrome.runtime.sendMessage`).
- Alternatively, the extension can prompt for email/password and call `/api/auth/login` directly.
- Token expiry (30 days default). On 401, the extension clears the token and prompts re-login.

---

## API Endpoint Requirements

### `POST /api/extension/save`

**Headers:** `Authorization: Bearer <jwt>`

**Request body:**
```json
{
  "url":              "https://example.com/article",
  "title":            "Article Title",
  "source_type":      "article",
  "selected_text":    "Optional highlighted text from the page",
  "page_description": "Optional meta description"
}
```

**Response (created):**
```json
{
  "status":     "created",
  "message":    "Saved to your NEXUS library",
  "site":       { ...site object... },
  "collection": { ...collection assignment or null... }
}
```

**Response (duplicate):**
```json
{
  "status":  "duplicate",
  "message": "URL already in your NEXUS library"
}
```

**`source_type` values:** `webpage` | `article` | `video` | `tool` | `other`

---

## Chrome Extension Folder Structure (future)

```
nexus-extension/
├── manifest.json          # MV3 manifest
├── background/
│   └── service-worker.js  # Handles auth token storage and message routing
├── popup/
│   ├── popup.html
│   ├── popup.tsx          # React popup UI (save button, status)
│   └── popup.css
├── content/
│   └── content-script.js  # Reads selected text from the active page
├── auth/
│   └── login.html         # Inline login form for first-time auth
├── icons/
│   ├── 16.png
│   ├── 48.png
│   └── 128.png
└── lib/
    ├── api.ts             # Shared fetch helpers (mirrors web app lib/api.ts)
    └── storage.ts         # chrome.storage wrappers for token persistence
```

---

## MVP Extension Features

- [ ] Save current tab with one click
- [ ] Show last 3 saved items in the popup
- [ ] Display save status (saving / saved / duplicate / error)
- [ ] Store and refresh JWT automatically
- [ ] Works with the deployed backend (`https://nexus-backend-bx18.onrender.com`)
- [ ] CORS allowed via `allow_origin_regex: chrome-extension://.*` (already configured)

---

## Future Extension Features

- [ ] Save selected text as a highlight/note attached to the source
- [ ] Inline tag picker before saving
- [ ] Right-click context menu: "Save to NEXUS"
- [ ] Auto-detect page type (article, video, docs) and set `source_type`
- [ ] Badge showing library count
- [ ] Quick search of existing library from popup
- [ ] Keyboard shortcut (`Ctrl+Shift+S` / `Cmd+Shift+S`)
- [ ] Firefox version (WebExtensions API compatible)
- [ ] Offline queue: save while offline, sync when back online

---

## Backend Hooks Already Prepared

The `/api/extension/save` endpoint already calls:

| Hook | Status |
|------|--------|
| Content safety check | ✅ Implemented |
| AI auto-tagging + categorisation | ✅ Implemented |
| Summary generation | ✅ Implemented |
| ChromaDB embedding upsert | ✅ Implemented |
| Collection auto-assignment | ✅ Implemented |
| Discover profile signals | ✅ Via profile feedback endpoints |
| Selected text storage (`raw_content`) | ✅ Stored, used for embeddings |
