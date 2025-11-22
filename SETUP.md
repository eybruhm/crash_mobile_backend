# CRASH Backend - Setup Guide

## Prerequisites
- Python 3.8 or higher
- PostgreSQL (via Supabase)
- Git

## Installation Steps

### 1. Clone the Repository
```bash
git clone <repository-url>
cd Project
```

### 2. Create Virtual Environment
```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install django djangorestframework psycopg2-binary python-dotenv django-storages boto3 qrcode pillow supabase
```

Or if a `requirements.txt` exists:
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root with the following:

```env
# Django Secret Key
SECRET_KEY='your-django-secret-key-here'

# Google Maps API (for routing)
GOOGLE_MAPS_API_KEY='your-google-maps-api-key'

# Supabase Configuration
SUPABASE_URL='https://your-project-id.supabase.co'
SUPABASE_SERVICE_ROLE_KEY='your-service-role-key-here'

# Optional: AWS/S3 settings (commented out if using Supabase SDK)
# AWS_ACCESS_KEY_ID='...'
# AWS_SECRET_ACCESS_KEY='...'
# AWS_STORAGE_BUCKET_NAME='crash-media'
# AWS_S3_ENDPOINT_URL='https://your-project.storage.supabase.co/storage/v1/s3'
```

**Important:** 
- Never commit `.env` to version control
- Replace all placeholder values with actual credentials
- Get `SUPABASE_SERVICE_ROLE_KEY` from: Supabase Dashboard → Settings → API → service_role key

### 5. Database Configuration

The database settings are in `crash_backend/settings.py`:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': 'postgres.your-project-id',
        'PASSWORD': 'your-db-password',
        'HOST': 'aws-x-region.pooler.supabase.com',
        'PORT': '5432',
    }
}
```

Get these credentials from: Supabase Dashboard → Settings → Database

### 6. Supabase Storage Setup

#### Create Storage Bucket
1. Go to Supabase Dashboard → Storage
2. Create a new bucket named `crash-media`
3. Set to **Public** bucket

#### Set Storage Policies
Run these SQL commands in Supabase SQL Editor:

```sql
-- Allow service role to insert files
CREATE POLICY "Allow Service Role Uploads"
ON storage.objects FOR INSERT
TO service_role
WITH CHECK (bucket_id = 'crash-media');

-- Allow public read access
CREATE POLICY "Allow Public Read"
ON storage.objects FOR SELECT
TO anon
USING (bucket_id = 'crash-media');
```

### 7. Run Migrations
```bash
python manage.py migrate
```

### 8. Create Admin Account (Optional)
If you need Django admin access:
```bash
python manage.py createsuperuser
```

### 9. Run Development Server
```bash
python manage.py runserver
```

Server will start at: `http://127.0.0.1:8000/`

## Verify Installation

Test the server is running:
```bash
curl http://127.0.0.1:8000/reports/
```

Should return an empty list or existing reports.

## Common Issues

### Issue: `ModuleNotFoundError: No module named 'supabase'`
**Solution:** Activate venv and install dependencies
```bash
.\venv\Scripts\Activate.ps1
pip install supabase
```

### Issue: Database connection refused
**Solution:** 
- Verify Supabase credentials in `.env`
- Check if your IP is allowed in Supabase (Dashboard → Settings → Database → Connection pooler)

### Issue: `SECRET_KEY` not set
**Solution:** Ensure `.env` file exists and `load_dotenv()` is called in `settings.py`

### Issue: File upload fails
**Solution:**
- Verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are correct
- Check storage bucket policies are set correctly
- Ensure bucket name is `crash-media`

## Project Structure
```
Project/
├── core/                   # Main app
│   ├── models.py          # Database models
│   ├── serializers.py     # DRF serializers
│   ├── views.py           # API endpoints
│   ├── urls.py            # Core URL routing
│   └── services.py        # Business logic (routing, QR)
├── crash_backend/         # Project settings
│   ├── settings.py        # Django configuration
│   └── urls.py            # Root URL routing
├── manage.py              # Django CLI
├── .env                   # Environment variables (DO NOT COMMIT)
└── requirements.txt       # Python dependencies
```

## Next Steps
- Read `API_ENDPOINTS.md` for available endpoints
- Read `INTEGRATION_GUIDE.md` for mobile app integration
- Read `CODE_REFERENCE.md` for code architecture
