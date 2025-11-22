# CRASH Backend - API Endpoints

Base URL: `http://127.0.0.1:8000` (development) or your deployed URL

## Authentication
Currently using **temporary authentication** (dummy tokens). JWT/session auth to be implemented.

---

## 1. Authentication

### Login (Admin/Police)
**POST** `/login/`

Authenticate admin or police office accounts.

**Request Body:**
```json
{
  "email": "test@crash.ph",
  "password": "testpass"
}
```

**Response (Success):**
```json
{
  "message": "Admin login successful",
  "role": "admin",
  "user": {
    "admin_id": "uuid-here",
    "username": "admin",
    "email": "test@crash.ph",
    "contact_no": "09123456789"
  },
  "token": "DUMMY_ADMIN_TOKEN"
}
```

**Response Codes:**
- `200 OK` - Login successful
- `400 Bad Request` - Missing email/password
- `401 Unauthorized` - Invalid credentials

---

## 2. Police Office Management (Admin Only)

### List All Police Offices
**GET** `/police-offices/`

**Response:**
```json
[
  {
    "office_id": "uuid",
    "office_name": "Station 1",
    "email": "station1@crash.ph",
    "head_officer": "Officer Name",
    "contact_number": "09123456789"
  }
]
```

### Create Police Office
**POST** `/police-offices/`

**Request Body:**
```json
{
  "office_name": "New Station",
  "email": "newstation@crash.ph",
  "password": "securepassword",
  "head_officer": "Chief Officer",
  "contact_number": "09123456789",
  "latitude": "14.5995124",
  "longitude": "120.9842195",
  "created_by": "admin-uuid-here"
}
```

**Response:** `201 Created` with office details

### Get Single Police Office
**GET** `/police-offices/{office_id}/`

### Update Police Office
**PUT/PATCH** `/police-offices/{office_id}/`

### Delete Police Office
**DELETE** `/police-offices/{office_id}/`

---

## 3. Reports (Incident Management)

### List Active Reports
**GET** `/reports/`

Returns all reports except Resolved/Canceled.

**Response:**
```json
[
  {
    "report_id": "uuid",
    "category": "Accident",
    "status": "Pending",
    "created_at": "2025-01-15T10:30:00Z",
    "latitude": "14.5995124",
    "longitude": "120.9842195",
    "description": "Car accident on highway",
    "assigned_office_name": "Station 1",
    "reporter_full_name": "Juan Dela Cruz"
  }
]
```

### Create Report (Mobile App)
**POST** `/reports/`

**Request Body:**
```json
{
  "category": "Accident",
  "description": "Detailed description here",
  "latitude": "14.5995124",
  "longitude": "120.9842195",
  "reporter": "user-uuid-here"
}
```

**Response:** `201 Created` with report details

**Categories:** `Accident`, `Crime`, `Fire`, `Medical`, `Other`

### Get Single Report
**GET** `/reports/{report_id}/`

### Update Report Status (Police)
**PUT/PATCH** `/reports/{report_id}/`

**Request Body:**
```json
{
  "status": "Acknowledged",
  "remarks": "Units dispatched"
}
```

**Status Options:**
- `Pending` - Initial state
- `Acknowledged` - Police confirmed receipt
- `En Route` - Police heading to location
- `Resolved` - Incident resolved
- `Canceled` - Report canceled

### Get Route/Directions
**GET** `/reports/{report_id}/route/`

Returns Google Maps routing URL and QR code for navigation.

**Response:**
```json
{
  "google_maps_url": "https://www.google.com/maps/dir/?api=1&origin=...",
  "qr_code_base64": "data:image/png;base64,iVBORw0KGgo..."
}
```

---

## 4. Messages (Report Chat)

### List Messages for a Report
**GET** `/reports/{report_id}/messages/`

**Response:**
```json
[
  {
    "message_id": "uuid",
    "sender_id": "uuid",
    "sender_type": "user",
    "receiver_id": "uuid",
    "message_content": "Need help urgently",
    "timestamp": "2025-01-15T10:32:00Z"
  }
]
```

### Send Message
**POST** `/reports/{report_id}/messages/`

**Request Body:**
```json
{
  "sender_id": "user-or-police-uuid",
  "sender_type": "user",
  "receiver_id": "police-or-user-uuid",
  "message_content": "Message text here"
}
```

**sender_type:** `user` or `police`

---

## 5. Checkpoints

### List All Checkpoints
**GET** `/checkpoints/`

**Response:**
```json
[
  {
    "checkpoint_id": "uuid",
    "office": "office-uuid",
    "office_name": "Station 1",
    "checkpoint_name": "Highway Checkpoint",
    "contact_number": "09123456789",
    "time_start": "08:00:00",
    "time_end": "20:00:00",
    "latitude": "14.5995124",
    "longitude": "120.9842195",
    "assigned_officers": "Officer A, Officer B",
    "created_at": "2025-01-15T08:00:00Z"
  }
]
```

### Create Checkpoint
**POST** `/checkpoints/`

**Request Body:**
```json
{
  "office": "office-uuid-here",
  "checkpoint_name": "New Checkpoint",
  "contact_number": "09123456789",
  "time_start": "08:00:00",
  "time_end": "20:00:00",
  "latitude": "14.5995124",
  "longitude": "120.9842195",
  "assigned_officers": "Officer Names"
}
```

### Get/Update/Delete Checkpoint
**GET/PUT/PATCH/DELETE** `/checkpoints/{checkpoint_id}/`

---

## 6. Media (File Uploads)

### List All Media
**GET** `/media/`

**Response:**
```json
[
  {
    "media_id": "uuid",
    "file_url": "https://supabase.co/storage/.../image.jpg",
    "report": "report-uuid",
    "file_type": "image",
    "sender_id": "user-uuid",
    "uploaded_at": "2025-01-15T10:35:00Z"
  }
]
```

### Upload Media
**POST** `/media/`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `report` (string): Report UUID
- `file_type` (string): `image` or `video`
- `sender_id` (string): Uploader's UUID
- `uploaded_file` (file): The actual file

**Example (curl):**
```bash
curl -X POST http://127.0.0.1:8000/media/ \
  -F "report=report-uuid-here" \
  -F "file_type=image" \
  -F "sender_id=user-uuid-here" \
  -F "uploaded_file=@/path/to/image.jpg"
```

**Response:** `201 Created` with media details including `file_url`

### Get Single Media
**GET** `/media/{media_id}/`

---

## HTTP Status Codes

- `200 OK` - Request successful
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication failed
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## CORS Configuration

For React Native/Expo, you may need to add CORS headers. Install `django-cors-headers`:

```bash
pip install django-cors-headers
```

Update `settings.py`:
```python
INSTALLED_APPS += ['corsheaders']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
CORS_ALLOW_ALL_ORIGINS = True  # For development only
```

## Rate Limiting

Currently no rate limiting. Consider implementing for production.

## Pagination

Default: No pagination. Add `?limit=10&offset=0` support if needed.

## Testing Endpoints

Use tools like:
- **Postman** - GUI for API testing
- **curl** - Command line
- **Thunder Client** - VS Code extension
- **Insomnia** - API client

Example collection available in repository (if provided).
