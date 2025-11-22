from django.db import models
import uuid

# Create your models here.
# Admin Model (Table A)
class Admin(models.Model):
    admin_id = models.UUIDField(primary_key=True)
    username = models.CharField(unique=True, max_length=50)
    email = models.CharField(unique=True, max_length=100)
    password = models.CharField(max_length=255)
    contact_no = models.CharField(max_length=15, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'tbl_admin'
        verbose_name = 'Admin Account'

# Citizen User Model (Table B)
class User(models.Model):
    user_id = models.UUIDField(primary_key=True)
    email = models.CharField(unique=True, max_length=100)
    phone = models.CharField(unique=True, max_length=20, blank=True, null=True) 
    password_hash = models.CharField(max_length=255) 
    first_name = models.CharField(max_length=50, default='Missing')
    last_name = models.CharField(max_length=50)
    birthdate = models.DateField()
    sex = models.CharField(max_length=10, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True, null=True)
    region = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    barangay = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'tbl_users'
        verbose_name = 'Citizen User'

# Police Office Model (Table C)
class PoliceOffice(models.Model):
    office_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office_name = models.CharField(max_length=100)
    email = models.CharField(unique=True, max_length=100, default='') # Added
    password_hash = models.CharField(max_length=255, default='')       # Added
    head_officer = models.CharField(max_length=100, blank=True, null=True)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    
    # Foreign Key to tbl_admin: ON DELETE SET NULL 
    created_by = models.ForeignKey(
        Admin, 
        on_delete=models.SET_NULL, 
        db_column='created_by', 
        blank=True, 
        null=True
    )
    created_at = models.DateTimeField(blank=True, null=True, auto_now_add=True)

    class Meta:
        db_table = 'tbl_police_offices'
        verbose_name = 'Police Office'

# Report Model (Table D) 
class Report(models.Model):
    # Status choices derived from your ENUM in Supabase
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Acknowledged', 'Acknowledged'),
        ('En Route', 'En Route'),
        ('Resolved', 'Resolved'),
        ('Canceled', 'Canceled'),
    ]
    
    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Foreign Keys with ON DELETE SET NULL 
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, db_column='reporter_id', blank=True, null=True)
    assigned_office = models.ForeignKey(PoliceOffice, on_delete=models.SET_NULL, db_column='assigned_office_id', blank=True, null=True)
    
    category = models.CharField(max_length=30)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    
    # Incident location
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    
    created_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True) # Will be managed by the DB trigger

    class Meta:
        db_table = 'tbl_reports'
        verbose_name = 'Incident Report'

# Message Model (Table G) 
class Message(models.Model):
    # Sender type from your ENUM 
    SENDER_TYPE_CHOICES = [
        ('user', 'User'),
        ('police', 'Police'),
    ]
    
    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Foreign Key to Report with CASCADE delete 
    report = models.ForeignKey(
        'Report', 
        on_delete=models.CASCADE, 
        db_column='report_id', 
        blank=True, 
        null=True
    )
    
    sender_id = models.UUIDField() # UUID of the sender (User or PoliceOffice)
    sender_type = models.CharField(max_length=10, choices=SENDER_TYPE_CHOICES)
    receiver_id = models.UUIDField() # UUID of the recipient (Not used for display, but required by schema)
    message_content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True) 

    class Meta:
        db_table = 'tbl_messages'
        verbose_name = 'Report Message'
    
class Checkpoint(models.Model):
    checkpoint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Foreign Key to PoliceOffice with CASCADE delete
    office = models.ForeignKey(
        'PoliceOffice', 
        on_delete=models.CASCADE, 
        db_column='office_id', 
        blank=True, 
        null=True
    )
    
    checkpoint_name = models.CharField(max_length=100)
    contact_number = models.CharField(max_length=20, blank=True, null=True) 
    
    time_start = models.TimeField(blank=True, null=True) 
    time_end = models.TimeField(blank=True, null=True)   
    
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    assigned_officers = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tbl_checkpoints'
        verbose_name = 'Police Checkpoint'

# Media Model (Table H) - NEW MODEL
class Media(models.Model):
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]
    
    media_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Change back to CharField. Django will NOT handle the upload itself.
    # The serializer will provide the URL string after S3 upload.
    file_url = models.CharField(max_length=255, blank=True, null=True)
    
    # Foreign Key to Report with CASCADE delete
    report = models.ForeignKey(
        'Report', 
        on_delete=models.CASCADE, 
        db_column='report_id', 
        blank=True, 
        null=True
    )
    
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    sender_id = models.UUIDField() # ID of the uploader (User or Police)
    uploaded_at = models.DateTimeField(auto_now_add=True) 

    class Meta:
        db_table = 'tbl_media'
        verbose_name = 'Report Media'