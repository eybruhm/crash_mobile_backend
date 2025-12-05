# core/serializers.py
# ============================================================================
# SERIALIZERS: Think of each serializer as a "translator" between Python objects
# and JSON (the format the frontend understands).
# Serializers handle: converting data to JSON, validating input, transforming fields.
# They sit between the view (Python) and the API (JSON).
# ============================================================================

from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.core.files.storage import default_storage
from django.conf import settings
from rest_framework.exceptions import ValidationError
from supabase import create_client
import os, uuid
from .models import (
    Admin, 
    PoliceOffice, 
    Report, 
    Message,
    Checkpoint,
    Media,
    SummaryAnalytics
)

# ============================================================================
# SUPABASE CLIENT SETUP
# ============================================================================
# Supabase = cloud database and file storage service
# This client connects our Django app to Supabase (initialized once at startup)
try:
    _supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
except Exception as e:
    # Fail immediately if credentials are missing or invalid
    # Better to crash now than discover the problem in production
    raise EnvironmentError(f"Supabase client failed to initialize: {e}")

# ============================================================================
# ADMIN SERIALIZERS
# ============================================================================

# ADMIN LOGIN SERIALIZER
# Used when: Returning admin data in responses (excludes sensitive password)
# Output: Admin ID, username, email, contact (safe to send to frontend)
class AdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admin
        # Only these fields are converted to JSON when returning admin data
        fields = ('admin_id', 'username', 'email', 'contact_no')
        
# ============================================================================
# POLICE OFFICE SERIALIZERS
# ============================================================================

# POLICE OFFICE LOGIN SERIALIZER
# Used when: Returning police office data to logged-in officers (after login)
# Output: Office info WITHOUT password (password_hash stays in database, never shown)
class PoliceOfficeLoginSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoliceOffice
        # Shows identification info, hides sensitive password field
        fields = ('office_id', 'office_name', 'email', 'head_officer', 'contact_number')

# POLICE OFFICE CREATION SERIALIZER
# Used when: Admin creates a new police office (includes password handling)
# Input: office_name, email, password (plain text), location, contact info
# Process: Accepts plain password, hashes it, stores hashed version
class PoliceOfficeCreateSerializer(serializers.ModelSerializer):
    # Define 'password' as write-only input field (not stored directly in database)
    # It gets converted to password_hash before saving
    password = serializers.CharField(write_only=True)
    
    class Meta:
        model = PoliceOffice
        # Fields that admin provides when creating a new office
        fields = (
            'office_name', 'email', 'password', 'head_officer', 
            'contact_number', 'latitude', 'longitude', 'created_by'
        )
        extra_kwargs = {
            'password_hash': {'write_only': True} 
        }
    
    # Override create() to handle password hashing before saving to database
    # Flow: plain password → hashed → stored in password_hash column
    def create(self, validated_data):
        # Extract plain password from the input data
        password = validated_data.pop('password')
        
        # Hash the password using Django's security function
        # Hashing = one-way conversion (can't decrypt, can only verify)
        validated_data['password_hash'] = make_password(password)
        
        # Create and save the PoliceOffice with the hashed password
        return PoliceOffice.objects.create(**validated_data)
    
# ============================================================================
# REPORT SERIALIZERS
# ============================================================================

# REPORT CREATION SERIALIZER
# Used when: Citizen submits a new crime report via mobile app
# Input: Crime category, description, GPS location, reporter ID
# Process: Validates data, converts JSON to Python object, saves to database
class ReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        # Fields that citizen provides when creating a report
        fields = (
            'category',          # What type of crime (e.g., "Robbery")
            'description',       # Details about what happened
            'latitude',          # GPS latitude of incident location
            'longitude',         # GPS longitude of incident location
            'reporter',          # Which citizen is reporting (their user ID)
            'location_city',     # Will be auto-filled by reverse geocoding
            'location_barangay'  # Will be auto-filled by reverse geocoding
        )
        # These fields are optional (can be calculated/filled later)
        extra_kwargs = {
            'location_city': {'required': False},
            'location_barangay': {'required': False},
        }

# REPORT LIST SERIALIZER
# Used when: Returning report data to police dashboard (reading reports)
# Output: Report details with human-readable names (not just IDs)
# Why: Police don't want to see UUID; they want "John Doe" not "user_id_12345"
class ReportListSerializer(serializers.ModelSerializer):
    # These are custom fields: shows the RELATED data (office name, reporter name)
    # source='assigned_office.office_name' = follow the relationship, get the name
    assigned_office_name = serializers.CharField(source='assigned_office.office_name', read_only=True)
    reporter_full_name = serializers.SerializerMethodField(read_only=True)
    incident_address = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Report
        # Fields to include in the JSON response
        fields = (
            'report_id',            # Unique report identifier
            'category',             # Crime type
            'status',               # Current status (Pending/Acknowledged/En Route/Resolved/Canceled)
            'created_at',           # When report was submitted
            'latitude',             # GPS coordinates
            'longitude',
            'description',          # Details about incident
            'assigned_office_name', # Human-readable office name
            'reporter_full_name',   # Human-readable citizen name
            'incident_address',     # Human-readable address (city, barangay)
        )
    
    # Custom method: combine first and last name into full name
    # Called for each report when serializing to JSON
    def get_reporter_full_name(self, obj):
        # If reporter exists, join first and last name
        if obj.reporter:
            return f"{obj.reporter.first_name} {obj.reporter.last_name}"
        # If reporter account was deleted, show placeholder
        return "N/A"
    
    # Custom method: format address as "Barangay, City" for readability
    def get_incident_address(self, obj):
        # If both city and barangay are available, combine them
        if obj.location_barangay and obj.location_city:
            return f"{obj.location_barangay}, {obj.location_city}"
        # If location hasn't been geocoded yet, show placeholder
        return "Address Pending"
    
# REPORT STATUS UPDATE SERIALIZER
# Used when: Police update report status (e.g., "Pending" → "En Route" → "Resolved")
# Input: New status, remarks/notes from police
# Process: Validates status is one of the allowed choices, saves update
class ReportStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        # Only allow police to change these two fields
        fields = ('status', 'remarks')
        # These fields can't be changed (to prevent tampering with incident details)
        read_only_fields = ('report_id', 'reporter', 'category', 'latitude', 'longitude') 

 
# ============================================================================
# MESSAGE SERIALIZER
# ============================================================================

# MESSAGE SERIALIZER
# Used when: Police and citizens exchange messages about an incident report
# Input/Output: All message fields (sender ID, content, timestamp, etc.)
# Flow: Citizen sends → message saved → police reads → police replies
class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        # Include all fields for complete message data
        fields = '__all__'
        # These are automatically set by the system (can't be manually edited)
        read_only_fields = ('message_id', 'timestamp')

# ============================================================================
# CHECKPOINT SERIALIZER
# ============================================================================

# CHECKPOINT SERIALIZER
# Used when: Admin creates/views police checkpoints and patrol locations
# Input: Checkpoint name, location, time range, assigned officers
# Output: Same data plus office name (for readability instead of office ID)
class CheckpointSerializer(serializers.ModelSerializer):
    # Include the related office name instead of just the office ID
    # Makes the response more human-readable for admin interface
    office_name = serializers.CharField(source='office.office_name', read_only=True)
    
    class Meta:
        model = Checkpoint
        # Include all checkpoint fields
        fields = '__all__'
        # These are auto-generated or managed by the system
        read_only_fields = ('checkpoint_id', 'created_at', 'office_name')
        # Note: The office_id (foreign key) is provided in the request body

# ============================================================================
# MEDIA SERIALIZER (File Upload)
# ============================================================================

# MEDIA SERIALIZER
# Used when: Citizens/police upload photos or videos as evidence for a report
# Input: File (image/video), report ID, file type, uploader ID
# Process: Upload file to Supabase cloud storage, save URL in database
# Output: File URL and metadata (ID, upload time, file type)
class MediaSerializer(serializers.ModelSerializer):
    # Define 'uploaded_file' as write-only (input only, not in response)
    # This is the actual file data the client sends
    # In the database, we only store the file_url (link to the file)
    uploaded_file = serializers.FileField(write_only=True) 

    class Meta:
        model = Media
        # 'uploaded_file' is for input; 'file_url' is what gets stored/returned
        fields = ('media_id', 'file_url', 'report', 'file_type', 'sender_id', 'uploaded_file') 
        # System-managed fields (can't be edited by client)
        read_only_fields = ('media_id', 'uploaded_at', 'file_url')

    # Override create() to handle file upload to Supabase cloud storage
    # Flow: receive file → upload to cloud → get URL → save URL in database
    def create(self, validated_data):
        # Extract the uploaded file from the request
        uploaded_file = validated_data.pop('uploaded_file') 
        report = validated_data['report']
        
        # Step 1: Generate unique file path (prevents name collisions)
        # Extract file extension (e.g., ".jpg", ".mp4")
        _, ext = os.path.splitext(uploaded_file.name or "") 
        # Create unique filename using UUID (e.g., "a1b2c3d4e5f6.jpg")
        object_name = f"{uuid.uuid4().hex}{ext.lower()}" 
        # Create organized path: reports/{report_id}/{unique_filename}
        object_path = f"reports/{report.report_id}/{object_name}" 

        # Step 2: Upload file to Supabase cloud storage
        # Supabase stores files in buckets (like folders)
        # This uploads to the "crash-media" bucket at object_path
        try:
            # Read file content into memory
            content = uploaded_file.read() 
            # Upload to Supabase storage (bucket name: "crash-media")
            _supabase.storage.from_("crash-media").upload(object_path, content) 
        except Exception as e:
            # If upload fails, raise validation error so client knows what went wrong
            raise serializers.ValidationError({"upload": f"Supabase upload failed: {e}"}) 

        # Step 3: Build public URL (the link to access the uploaded file)
        # Supabase files are accessible via: [BASE_URL]/storage/v1/object/public/[BUCKET]/[PATH]
        base = settings.SUPABASE_URL.rstrip("/") 
        # Construct: https://supabase.com/storage/v1/object/public/crash-media/reports/report_id/file.jpg
        public_url = f"{base}/storage/v1/object/public/crash-media/{object_path}" 

        # Store the public URL so we can access the file later
        validated_data['file_url'] = public_url 
        
        # Step 4: Save the record to database with the file URL
        return super().create(validated_data)


# ============================================================================
# SUMMARY ANALYTICS SERIALIZER (Cached Statistics)
# ============================================================================

# SUMMARY ANALYTICS SERIALIZER
# Used when: Analytics dashboard needs quick access to crime statistics (pre-calculated)
# Input: Location (city/barangay), category, report count
# Purpose: Provides cached summary data so dashboard loads instantly (no complex queries needed)
# Note: These records are auto-generated by caching system, rarely created manually
class SummaryAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SummaryAnalytics
        # Include all cached statistics fields
        fields = '__all__'
        # All fields are system-managed (updated by cache job, not by API requests)
        read_only_fields = ('summary_id', 'report_count', 'last_updated')