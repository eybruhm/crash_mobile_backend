# CRASH Backend - Code Reference

## Architecture Overview

This Django REST Framework backend follows a standard MVC pattern:
- **Models** (`models.py`) - Database schema
- **Serializers** (`serializers.py`) - Data validation and transformation
- **Views** (`views.py`) - Business logic and HTTP handlers
- **Services** (`services.py`) - Reusable business logic

---

## Models (`core/models.py`)

### `Admin`
**Purpose:** Admin user accounts with full system access

**Fields:**
- `admin_id` (UUID, PK) - Unique identifier
- `username` (str) - Login username
- `email` (str) - Email address
- `password` (str) - Hashed password
- `contact_no` (str) - Contact number
- `created_at` (datetime) - Account creation timestamp

**Table:** `tbl_admin`

---

### `User`
**Purpose:** Citizen/reporter accounts (mobile app users)

**Fields:**
- `user_id` (UUID, PK)
- `email` (str, unique)
- `phone` (str, unique)
- `password_hash` (str)
- `first_name`, `last_name` (str)
- `birthdate` (date)
- `sex` (str)
- `emergency_contact_name`, `emergency_contact_number` (str)
- `region`, `city`, `barangay` (str) - Address
- `created_at` (datetime)

**Table:** `tbl_users`

---

### `PoliceOffice`
**Purpose:** Police station/office accounts

**Fields:**
- `office_id` (UUID, PK, auto-generated)
- `office_name` (str) - Station name
- `email` (str, unique) - Login email
- `password_hash` (str) - Hashed password
- `head_officer` (str) - Chief officer name
- `contact_number` (str)
- `latitude`, `longitude` (decimal) - GPS coordinates
- `created_by` (FK → Admin) - Admin who created this office
- `created_at` (datetime)

**Table:** `tbl_police_offices`

**Relationships:**
- Foreign Key to `Admin` (SET NULL on delete)

---

### `Report`
**Purpose:** Incident reports submitted by users

**Fields:**
- `report_id` (UUID, PK, auto-generated)
- `reporter` (FK → User, SET NULL)
- `assigned_office` (FK → PoliceOffice, SET NULL)
- `category` (str) - Incident type
- `description` (text) - Detailed description
- `status` (str, choices) - Report lifecycle status
- `latitude`, `longitude` (decimal) - Incident location
- `created_at` (datetime)
- `remarks` (text) - Police notes
- `updated_at` (datetime) - Last update (DB trigger managed)

**Status Choices:**
- `Pending`, `Acknowledged`, `En Route`, `Resolved`, `Canceled`

**Table:** `tbl_reports`

**Relationships:**
- Foreign Key to `User` (reporter)
- Foreign Key to `PoliceOffice` (assigned_office)

---

### `Message`
**Purpose:** Chat messages between users and police for specific reports

**Fields:**
- `message_id` (UUID, PK, auto-generated)
- `report` (FK → Report, CASCADE)
- `sender_id` (UUID) - User or Police UUID
- `sender_type` (str, choices: `user`, `police`)
- `receiver_id` (UUID) - Recipient UUID
- `message_content` (text)
- `timestamp` (datetime)

**Table:** `tbl_messages`

**Relationships:**
- Foreign Key to `Report` (CASCADE delete)

---

### `Checkpoint`
**Purpose:** Police checkpoints with location and schedule

**Fields:**
- `checkpoint_id` (UUID, PK, auto-generated)
- `office` (FK → PoliceOffice, CASCADE)
- `checkpoint_name` (str)
- `contact_number` (str)
- `time_start`, `time_end` (time) - Operating hours
- `latitude`, `longitude` (decimal)
- `assigned_officers` (text) - Comma-separated names
- `created_at` (datetime)

**Table:** `tbl_checkpoints`

**Relationships:**
- Foreign Key to `PoliceOffice` (CASCADE delete)

---

### `Media`
**Purpose:** Photos/videos attached to reports

**Fields:**
- `media_id` (UUID, PK, auto-generated)
- `file_url` (str) - Public Supabase Storage URL
- `report` (FK → Report, CASCADE)
- `file_type` (str, choices: `image`, `video`)
- `sender_id` (UUID) - Uploader's UUID
- `uploaded_at` (datetime)

**Table:** `tbl_media`

**Relationships:**
- Foreign Key to `Report` (CASCADE delete)

---

## Serializers (`core/serializers.py`)

### `AdminSerializer`
**Purpose:** Serialize admin data (exclude password)

**Fields:** `admin_id`, `username`, `email`, `contact_no`

---

### `PoliceOfficeLoginSerializer`
**Purpose:** Serialize police office data for login response

**Fields:** `office_id`, `office_name`, `email`, `head_officer`, `contact_number`

**Usage:** Login response, list view (excludes password)

---

### `PoliceOfficeCreateSerializer`
**Purpose:** Handle police office creation with password hashing

**Fields:** All fields including `password` (write-only)

**Methods:**
- `create()` - Hashes password before saving

---

### `ReportCreateSerializer`
**Purpose:** Accept new report submissions from mobile app

**Fields:** `category`, `description`, `latitude`, `longitude`, `reporter`

---

### `ReportListSerializer`
**Purpose:** Display reports with related data (office name, reporter name)

**Fields:** All report fields + `assigned_office_name`, `reporter_full_name`

**Methods:**
- `get_reporter_full_name()` - Joins first/last name

---

### `ReportStatusUpdateSerializer`
**Purpose:** Allow police to update report status

**Fields:** `status`, `remarks` (editable only)

---

### `MessageSerializer`
**Purpose:** Handle message CRUD operations

**Fields:** All message fields

---

### `CheckpointSerializer`
**Purpose:** Handle checkpoint CRUD with office name

**Fields:** All checkpoint fields + `office_name` (read-only)

---

### `MediaSerializer`
**Purpose:** Handle file uploads to Supabase Storage

**Fields:** `media_id`, `file_url`, `report`, `file_type`, `sender_id`, `uploaded_file`

**Methods:**
- `create()` - Uploads file to Supabase, generates UUID filename, returns public URL

**Key Logic:**
1. Reads uploaded file
2. Generates UUID-based filename
3. Uploads to `crash-media` bucket via Supabase SDK
4. Retrieves public URL
5. Saves URL to database

---

## Views (`core/views.py`)

### `LoginAPIView` (APIView)
**Purpose:** Authenticate admin or police users

**Methods:**
- `post()` - Check email/password, return user data + token

**Logic:**
1. Try Admin login first
2. If not found, try Police login
3. Return role-specific response with dummy token

---

### `PoliceOfficeAdminViewSet` (ModelViewSet)
**Purpose:** CRUD operations for police offices (admin only)

**Methods:**
- `list()` - Get all offices (excludes main admin account)
- `create()` - Create new office with password hashing
- `retrieve()` - Get single office
- `update()`, `partial_update()` - Update office
- `destroy()` - Delete office

**Custom Methods:**
- `get_serializer_class()` - Use different serializers for create vs read
- `perform_create()` - Link office to admin creator

---

### `ReportViewSet` (ModelViewSet)
**Purpose:** Incident report management

**Methods:**
- `list()` - Get active reports (excludes Resolved/Canceled)
- `create()` - Submit new report, auto-assign to nearest office (stub)
- `retrieve()` - Get single report
- `update()`, `partial_update()` - Update report status
- `route()` - Custom action to generate routing directions

**Custom Actions:**
- `@action(detail=True, methods=['get']) route()` - Returns Google Maps URL + QR code

**Custom Methods:**
- `get_queryset()` - Filter active reports for GET requests
- `perform_create()` - Assign nearest office, link reporter
- `get_serializer_class()` - Different serializers per action

---

### `MessageViewSet` (ModelViewSet)
**Purpose:** Report chat message management

**Methods:**
- `list()` - Get messages for specific report
- `create()` - Send new message

**Custom Methods:**
- `get_queryset()` - Filter by `report_pk` from URL
- `perform_create()` - Link message to report

---

### `CheckpointViewSet` (ModelViewSet)
**Purpose:** Police checkpoint CRUD

**Methods:**
- Standard CRUD operations (list, create, retrieve, update, destroy)

---

### `MediaViewSet` (ModelViewSet)
**Purpose:** File upload/retrieval

**Methods:**
- `list()` - Get all media
- `create()` - Upload file (handled by serializer)
- `retrieve()` - Get single media
- Standard update/delete (optional use)

---

## Services (`core/services.py`)

### `generate_directions_and_qr(start_lat, start_lng, end_lat, end_lng)`
**Purpose:** Generate Google Maps routing URL and QR code

**Parameters:**
- `start_lat`, `start_lng` - Police office coordinates
- `end_lat`, `end_lng` - Incident location coordinates

**Returns:**
```python
{
    "google_maps_url": "https://google.com/maps/dir/...",
    "qr_code_base64": "data:image/png;base64,..."
}
```

**Dependencies:**
- `qrcode` library
- Google Maps API (via URL construction)

---

## URL Routing (`core/urls.py`)

```python
router = DefaultRouter()
router.register(r'police-offices', PoliceOfficeAdminViewSet)
router.register(r'reports', ReportViewSet)
router.register(r'checkpoints', CheckpointViewSet)
router.register(r'media', MediaViewSet)

urlpatterns = [
    path('login/', LoginAPIView.as_view()),
    path('reports/<uuid:report_pk>/messages/', MessageViewSet as nested route),
    path('', include(router.urls)),
]
```

---

## Key Design Patterns

### 1. **Serializer Switching**
ViewSets use `get_serializer_class()` to return different serializers based on action (create vs list vs update).

### 2. **Soft Deletes via SET NULL**
When a User is deleted, their reports remain but `reporter` becomes NULL.

### 3. **Nested Routing**
Messages are accessed via `/reports/{id}/messages/` to scope by report.

### 4. **External Storage**
Media files stored in Supabase Storage, only URLs saved in DB.

### 5. **Service Layer**
Complex logic (routing, QR generation) extracted to `services.py`.

---

## Database Schema Relationships

```
Admin
  └── creates → PoliceOffice

User (reporter)
  └── creates → Report

PoliceOffice
  └── assigned to → Report
  └── manages → Checkpoint

Report
  ├── has many → Message
  └── has many → Media
```

---

## Future Enhancements

- JWT authentication
- Real-time notifications (WebSockets/Firebase)
- Geospatial queries for nearest office
- File upload validation (size, type)
- Soft delete for reports
- Audit logs
