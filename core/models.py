from django.db import models
import uuid

# ============================================================================
# MODELS: Think of each class as a TABLE in the database.
# Each field = a COLUMN in that table. When you save an instance,
# it creates a new ROW in the corresponding database table.
# ============================================================================

# ADMIN MODEL - Stores system administrator accounts
# Who: Platform managers who oversee the whole system
# Data: Login info (email/password), contact, created timestamp
class Admin(models.Model):
    # UUIDField = unique identifier (like a fingerprint, never repeats)
    # primary_key=True = this is the main ID column for this table
    admin_id = models.UUIDField(primary_key=True)
    
    # CharField = text field; unique=True = no two admins can have same username
    username = models.CharField(unique=True, max_length=50)
    
    # unique=True = each admin must have a different email (no duplicates)
    email = models.CharField(unique=True, max_length=100)
    password = models.CharField(max_length=255)
    
    # blank=True, null=True = optional field (can be empty in database)
    contact_no = models.CharField(max_length=15, blank=True, null=True)
    
    # DateTimeField = stores date AND time (e.g., "2025-12-06 14:30:45")
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        # db_table = tell Django what table name to use in the database
        db_table = 'tbl_admin'
        # verbose_name = human-readable name shown in Django admin panel
        verbose_name = 'Admin Account'

# CITIZEN/USER MODEL - Stores regular citizens who report crimes
# Who: People in the community reporting incidents (e.g., someone who witnessed a robbery)
# Data: Personal info, location, emergency contacts for when police need to follow up
class User(models.Model):
    # UUIDField with primary_key=True = unique ID, like a citizen ID number
    user_id = models.UUIDField(primary_key=True)
    
    # Email must be unique (one email = one account)
    email = models.CharField(unique=True, max_length=100)
    
    # Phone must be unique (one phone = one account), optional field
    phone = models.CharField(unique=True, max_length=20, blank=True, null=True)
    
    # password_hash = encrypted version of the password (never store plain text!)
    password_hash = models.CharField(max_length=255)
    
    # Personal details about the citizen reporting the incident
    first_name = models.CharField(max_length=50, default='Missing')
    last_name = models.CharField(max_length=50)
    birthdate = models.DateField()  # DateField = only date, no time component
    sex = models.CharField(max_length=10, blank=True, null=True)
    
    # Emergency contact = who to call if something happens to this person
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True, null=True)
    
    # Location fields = where does this citizen live?
    region = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    barangay = models.CharField(max_length=50, blank=True, null=True)
    
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'tbl_users'
        verbose_name = 'Citizen User'

# POLICE OFFICE MODEL - Stores police station/precinct information
# Who: Each police office (station) that responds to incident reports
# Data: Office name, location (GPS), head officer, login credentials for officers
class PoliceOffice(models.Model):
    # UUIDField with default=uuid.uuid4 = automatically generates a unique ID when created
    office_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Name of the police station (e.g., "Quezon City Police District 1")
    office_name = models.CharField(max_length=100)
    
    # Email and password = officers from this office can log in with this account
    email = models.CharField(unique=True, max_length=100, default='')
    password_hash = models.CharField(max_length=255, default='')
    
    # Who is in charge of this police office?
    head_officer = models.CharField(max_length=100, blank=True, null=True)
    
    # Contact number = public number to reach this office
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    
    # GPS coordinates = the physical location of the police office
    # Used to calculate which office is closest to an incident
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    
    # ForeignKey = "link" to the Admin table
    # on_delete=SET_NULL = if the admin is deleted, set this to NULL (don't delete the office)
    # This shows which admin created this police office
    created_by = models.ForeignKey(
        Admin, 
        on_delete=models.SET_NULL, 
        db_column='created_by', 
        blank=True, 
        null=True
    )
    
    # auto_now_add=True = automatically set to current time when first created (never changes after)
    created_at = models.DateTimeField(blank=True, null=True, auto_now_add=True)

    class Meta:
        db_table = 'tbl_police_offices'
        verbose_name = 'Police Office'

# REPORT MODEL - Stores crime incident reports submitted by citizens
# Who: Created by citizens reporting a crime; assigned to and updated by police
# Data: What happened, where, who reported it, current status, resolution info
class Report(models.Model):
    # STATUS_CHOICES = predefined options for the status field
    # Like a dropdown menu: citizen submits → police acknowledges → they go → resolved/canceled
    STATUS_CHOICES = [
        ('Pending', 'Pending'),           # Just submitted, waiting for police
        ('Acknowledged', 'Acknowledged'), # Police got it, they know about it
        ('En Route', 'En Route'),         # Police are on their way
        ('Resolved', 'Resolved'),         # Incident handled, case closed
        ('Canceled', 'Canceled'),         # False alarm or canceled
    ]
    
    # Unique ID for this incident report
    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # ForeignKey to User = "which citizen reported this?" 
    # on_delete=SET_NULL = if citizen deletes account, keep the report but set reporter to NULL
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, db_column='reporter_id', blank=True, null=True)
    
    # ForeignKey to PoliceOffice = "which police office handles this?"
    # The nearest office is automatically assigned when report is created
    assigned_office = models.ForeignKey(PoliceOffice, on_delete=models.SET_NULL, db_column='assigned_office_id', blank=True, null=True)
    
    # What kind of crime? (e.g., "Robbery", "Theft", "Assault")
    category = models.CharField(max_length=30)
    
    # Details about the incident (what happened, what was stolen, etc.)
    description = models.TextField(blank=True, null=True)
    
    # Current status of the report (uses STATUS_CHOICES above)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    
    # GPS coordinates of where the incident happened
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    
    # auto_now_add=True = automatically set when first created, never changes
    created_at = models.DateTimeField(auto_now_add=True)
    
    # What did police do to resolve it? (notes/comments)
    remarks = models.TextField(blank=True, null=True)
    
    # updated_at = when the status last changed (managed by database trigger/logic)
    # Could be when police arrived, when case closed, etc.
    updated_at = models.DateTimeField(blank=True, null=True)
    
    # Geocoded location = actual city/barangay name (converted from GPS coordinates)
    location_city = models.CharField(max_length=50, blank=True, null=True)     
    location_barangay = models.CharField(max_length=50, blank=True, null=True) 
    
    class Meta:
        db_table = 'tbl_reports'
        verbose_name = 'Incident Report'

# Message Model (Table G) 

# MESSAGE MODEL - Stores back-and-forth communication between citizens and police
# Who: Citizens and police officers having conversations about a specific incident report
# Data: Who sent it, what they said, timestamp, which report it's about
class Message(models.Model):
    # SENDER_TYPE_CHOICES = who is sending this message?
    # Like a tag: either a regular citizen or a police officer
    SENDER_TYPE_CHOICES = [
        ('user', 'User'),      # Citizen sending a message
        ('police', 'Police'),  # Police officer sending a message
    ]
    
    # Unique ID for this message
    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # ForeignKey to Report = "which report is this message about?"
    # on_delete=CASCADE = if the report is deleted, delete all its messages too
    # This links the message to a specific incident
    report = models.ForeignKey(
        'Report', 
        on_delete=models.CASCADE, 
        db_column='report_id', 
        blank=True, 
        null=True
    )
    
    # sender_id = UUID of whoever sent this (could be User ID or PoliceOffice ID)
    # We don't use ForeignKey here because sender could be either table
    sender_id = models.UUIDField()
    
    # Type of sender (tells us: is sender_id a User or PoliceOffice?)
    sender_type = models.CharField(max_length=10, choices=SENDER_TYPE_CHOICES)
    
    # receiver_id = who should receive this message (also a UUID)
    receiver_id = models.UUIDField()
    
    # The actual message text that was sent
    message_content = models.TextField()
    
    # auto_now_add=True = time is automatically recorded when message is created
    timestamp = models.DateTimeField(auto_now_add=True) 

    class Meta:
        db_table = 'tbl_messages'
        verbose_name = 'Report Message'

# CHECKPOINT MODEL - Stores police checkpoints/patrol locations
# Who: Police officers staffing checkpoints at specific locations
# Data: Where checkpoint is, when it's active, which officers are stationed there
class Checkpoint(models.Model):
    # Unique ID for this checkpoint
    checkpoint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # ForeignKey to PoliceOffice = "which police office runs this checkpoint?"
    # on_delete=CASCADE = if office is deleted, delete all its checkpoints too
    office = models.ForeignKey(
        'PoliceOffice', 
        on_delete=models.CASCADE, 
        db_column='office_id', 
        blank=True, 
        null=True
    )
    
    # Name of this checkpoint (e.g., "Highway Entry Point 1")
    checkpoint_name = models.CharField(max_length=100)
    
    # Phone number for this checkpoint location
    contact_number = models.CharField(max_length=20, blank=True, null=True) 
    
    # time_start and time_end = what hours is this checkpoint active?
    # For example: 8 AM to 5 PM (or overnight shift 10 PM to 6 AM)
    # TimeField = just time, no date (e.g., "14:30:00")
    time_start = models.TimeField(blank=True, null=True) 
    time_end = models.TimeField(blank=True, null=True)   
    
    # GPS coordinates of where the checkpoint is located
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    
    # Names/IDs of officers assigned to work at this checkpoint
    assigned_officers = models.TextField(blank=True, null=True)
    
    # When was this checkpoint created?
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tbl_checkpoints'
        verbose_name = 'Police Checkpoint'

# MEDIA MODEL - Stores photos/videos that citizens and police upload for a report
# Who: Citizens and police can upload images or videos as evidence
# Data: The file (stored in cloud), who uploaded it, what report it belongs to
class Media(models.Model):
    # FILE_TYPE_CHOICES = what kind of file is this?
    # Like a dropdown: image (photo) or video
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]
    
    # Unique ID for this media file
    media_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # file_url = link to the file stored in cloud storage (like AWS S3)
    # CharField instead of FileField because file is already stored elsewhere
    # We only store the URL (the path to find the file)
    file_url = models.CharField(max_length=255, blank=True, null=True)
    
    # ForeignKey to Report = "which report does this photo/video belong to?"
    # on_delete=CASCADE = if report deleted, delete all its media files too
    report = models.ForeignKey(
        'Report', 
        on_delete=models.CASCADE, 
        db_column='report_id', 
        blank=True, 
        null=True
    )
    
    # Type of file (tells us: is it an image or video?)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    
    # sender_id = UUID of whoever uploaded this (User or Police officer)
    sender_id = models.UUIDField()
    
    # When was this file uploaded?
    uploaded_at = models.DateTimeField(auto_now_add=True) 

    class Meta:
        db_table = 'tbl_media'
        verbose_name = 'Report Media'

# SUMMARY ANALYTICS MODEL - Stores cached statistics for performance
# Who: System automatically updates this when new reports are resolved
# Data: Total crimes per location/category (used for dashboards and reports)
# Why: Prevents slow aggregation queries; instead, lookup pre-calculated numbers
class SummaryAnalytics(models.Model):
    # Unique ID for this analytics record
    summary_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # What location is this data for?
    location_city = models.CharField(max_length=50)
    location_barangay = models.CharField(max_length=50)
    
    # What crime category is this data for?
    category = models.CharField(max_length=30)
    
    # Total count of resolved reports for this location + category combo
    # If location="QC", barangay="Diliman", category="Robbery", 
    # report_count might be 47 (47 robberies in Diliman, QC)
    report_count = models.IntegerField(default=0)
    
    # When was this statistic last updated?
    last_updated = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tbl_summary_analytics'
        verbose_name = 'Summary Analytics'
        # unique_together = prevent duplicate rows
        # Can't have two rows with same city + barangay + category
        unique_together = ('location_city', 'location_barangay', 'category')