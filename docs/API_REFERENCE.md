# SAP Role Access Visualizer — API Reference

Base URL: `http://127.0.0.1:8000`  
Auth: None (internal tool)  
Interactive docs: http://127.0.0.1:8000/docs

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status + cached role count |
| GET | `/api/modules` | Distinct module list |
| GET | `/api/roles` | Role list (filterable) |
| GET | `/api/roles/{name}` | Full role detail + hierarchy |
| POST | `/api/compare` | Multi-role T-code comparison |
| POST | `/api/refresh` | Reload cache from CSV |

---

### GET /api/roles

**Query params:** `module=FI` · `search=manager`

```bash
curl "http://127.0.0.1:8000/api/roles?module=FI&search=manager"
```

**Response:**
```json
[{"agr_name":"ZC:FI:S4CLNT000:XX:ROLE_A","text":"FI - Comptable AP","function_key":"FI","module_name":"Finance","tcode_count":1567}]
```

---

### GET /api/roles/{name}

Role name contains colons — URL-encode it: `ZC%3AFI%3AS4CLNT000%3AXX%3AROLE_A`

```bash
curl "http://127.0.0.1:8000/api/roles/ZC%3AFI%3AS4CLNT000%3AXX%3AROLE_A"
```

**Response:** Full RoleDetail with `single_roles[].tcodes[]`

---

### POST /api/compare

```bash
curl -X POST "http://127.0.0.1:8000/api/compare" \
  -H "Content-Type: application/json" \
  -d '{"roles":["ZC:FI:S4CLNT000:XX:ROLE_A","ZC:FI:S4CLNT000:XX:ROLE_B"]}'
```

**Response:** `{roles:[{agr_name,unique_tcodes}], shared_tcodes}`

---

## Error codes

| Code | Meaning |
|---|---|
| 400 | Fewer than 2 roles in compare / duplicate roles |
| 404 | Role not found |
| 503 | Cache not loaded yet — POST /api/refresh |
