# core/serializers.py
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

# Supabase Client Initialization
# NOTE: Client is initialized once at the module level for efficiency.
try:
    _supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
except Exception as e:
    # Fail fast if connection details are missing
    raise EnvironmentError(f"Supabase client failed to initialize: {e}")

# Serializer for Admin details 
class AdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admin
        fields = ('admin_id', 'username', 'email', 'contact_no')
        
# Serializer for Police Office (used for login response, excluding password_hash)
class PoliceOfficeLoginSerializer(serializers.ModelSerializer):
    class Meta:
        model = PoliceOffice
        # Exclude sensitive data (password_hash) and focus on identification fields
        fields = ('office_id', 'office_name', 'email', 'head_officer', 'contact_number')

# Serializer for Police Office creation (includes password hashing)
class PoliceOfficeCreateSerializer(serializers.ModelSerializer):
    # 1. Define 'password' field for input only
    password = serializers.CharField(write_only=True)
    
    class Meta:
        model = PoliceOffice
        # Include email and password_hash for creation
        fields = (
            'office_name', 'email', 'password', 'head_officer', 
            'contact_number', 'latitude', 'longitude', 'created_by'
        )
        extra_kwargs = {
            'password_hash': {'write_only': True} 
        }
    
    # 2. Override the create method to hash the password
    def create(self, validated_data):
        # Pop the plain password out of the data dictionary
        password = validated_data.pop('password')
        
        # Hash the password and set it to the password_hash field
        validated_data['password_hash'] = make_password(password)
        
        # Create the PoliceOffice object with the hashed password
        return PoliceOffice.objects.create(**validated_data)
    
# Serializer for receiving new reports (input from mobile app)
class ReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = (
            'category', 
            'description', 
            'latitude', 
            'longitude', 
            'reporter', # The ID will be passed/inferred during POST
            'location_city',     
            'location_barangay'  
        )
        extra_kwargs = {
            'location_city': {'required': False},
            'location_barangay': {'required': False},
        }

# Serializer for listing active reports (output to police dashboard)
class ReportListSerializer(serializers.ModelSerializer):
    # Display the related police office name and reporter name, not just UUIDs
    assigned_office_name = serializers.CharField(source='assigned_office.office_name', read_only=True)
    reporter_full_name = serializers.SerializerMethodField(read_only=True)
    
    incident_address = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Report
        fields = (
            'report_id', 
            'category', 
            'status', 
            'created_at', 
            'latitude',
            'longitude',
            'description',
            'assigned_office_name', 
            'reporter_full_name',
            'incident_address',    
        )
    
    # Custom method to join first and last names
    def get_reporter_full_name(self, obj):
        if obj.reporter:
            return f"{obj.reporter.first_name} {obj.reporter.last_name}"
        return "N/A" # If reporter is null (deleted account)
    
    # Custom method to format incident address
    def get_incident_address(self, obj):
        if obj.location_barangay and obj.location_city:
            return f"{obj.location_barangay}, {obj.location_city}"
        return "Address Pending"
    
# Serializer for updating report status (used by police to update status)
class ReportStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        # Only allow updating status and remarks
        fields = ('status', 'remarks')
        read_only_fields = ('report_id', 'reporter', 'category', 'latitude', 'longitude') 

# Serializer for Messages between police and citizens
class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = '__all__' # Include all fields for simple read/write
        read_only_fields = ('message_id', 'timestamp')

# Serializer for Checkpoints
class CheckpointSerializer(serializers.ModelSerializer):
    # Include office_name for list view readability
    office_name = serializers.CharField(source='office.office_name', read_only=True)
    
    class Meta:
        model = Checkpoint
        fields = '__all__'
        read_only_fields = ('checkpoint_id', 'created_at', 'office_name')
        # Note: office_id (parent FK) will be passed in POST/PUT request body

# Serializer for Media uploads associated with reports
class MediaSerializer(serializers.ModelSerializer):
    # This field handles the incoming file data from Postman/Mobile App
    uploaded_file = serializers.FileField(write_only=True) 

    class Meta:
        model = Media
        # Ensure 'uploaded_file' is used for input, and 'file_url' for output
        fields = ('media_id', 'file_url', 'report', 'file_type', 'sender_id', 'uploaded_file') 
        read_only_fields = ('media_id', 'uploaded_at', 'file_url')

    def create(self, validated_data):
        uploaded_file = validated_data.pop('uploaded_file') 
        report = validated_data['report']
        
        # 1. Prepare unique file path
        # Uses UUID to ensure uniqueness, avoiding collisions, then appends the file extension.
        _, ext = os.path.splitext(uploaded_file.name or "") 
        object_name = f"{uuid.uuid4().hex}{ext.lower()}" 
        # Creates an organized path: crash-media/reports/{report_id}/{file_uuid}.ext
        object_path = f"reports/{report.report_id}/{object_name}" 

        # 2. File Upload via SDK
        try:
            content = uploaded_file.read() 
            # Use 'from_' method to specify the bucket name
            _supabase.storage.from_("crash-media").upload(object_path, content) 
        except Exception as e:
            # Raise a DRF validation error if the upload fails (e.g., policy denial, size limit)
            raise serializers.ValidationError({"upload": f"Supabase upload failed: {e}"}) 

        # 3. Retrieve and/or Construct Public URL
        # NOTE: Using get_public_url() is best practice, but we use the reliable fallback as primary.
        
        # Fallback construction using defined settings (guarantees correct format) [cite: 850]
        base = settings.SUPABASE_URL.rstrip("/") 
        # Constructs: [BASE_URL]/storage/v1/object/public/crash-media/[OBJECT_PATH]
        public_url = f"{base}/storage/v1/object/public/crash-media/{object_path}" 

        validated_data['file_url'] = public_url 
        
        # 4. Save the database record with the final public URL
        return super().create(validated_data) 
    
# Serializer for Summary Analytics (for dashboard charts)
class SummaryAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SummaryAnalytics
        # Use only the fields necessary for charting/display
        fields = ('location_city', 'location_barangay', 'category', 'report_count')