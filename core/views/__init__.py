# ============================================================================
# VIEWS: Think of views as "request handlers" - they receive HTTP requests from
# the frontend, process them using models/serializers, and send back responses.
# Each view = one endpoint. Views are like "recipe executors" for API endpoints.
# ============================================================================

from datetime import datetime, timedelta

from django.http import HttpResponse
from django.db.models import Count
from django.core.cache import cache
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    Admin,
    PoliceOffice,
    Report,
    Message,
    Checkpoint,
    Media,
    SummaryAnalytics,
    User,
)
from ..serializers import (
    AdminSerializer,
    PoliceOfficeLoginSerializer,
    PoliceOfficeCreateSerializer,
    ReportCreateSerializer,
    ReportListSerializer,
    ReportStatusUpdateSerializer,
    MessageSerializer,
    CheckpointSerializer,
    MediaSerializer,
)
from ..services import (
    generate_directions_and_qr,
    reverse_geocode,
    get_active_checkpoints_list,
)


# ============================================================================
# LOGIN VIEW
# ============================================================================

class LoginAPIView(APIView):
    # ENDPOINT: POST /api/login/
    # Used when: Admin or Police officer tries to log in
    # Input: email and password (plain text)
    # Output: User data, role (admin/police), token if successful
    # Note: Password is temporary (hardcoded "testpass" for testing)
    # TODO: Replace with proper JWT token authentication

    def post(self, request):
        # Get email and password from request body
        email = request.data.get('email')
        password = request.data.get('password')

        # Validate: both email and password must be provided
        if not email or not password:
            return Response({"detail": "Email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Try Admin login first: search database for admin with this email
        try:
            admin_user = Admin.objects.get(email=email)
            # Temporary security: check against hardcoded password (not secure!)
            if password == "testpass":
                # Serialize admin data (converts to JSON, excludes password)
                serializer = AdminSerializer(admin_user)
                return Response({
                    "message": "Admin login successful",
                    "role": "admin",
                    "user": serializer.data,
                    "token": "DUMMY_ADMIN_TOKEN",  # TODO: Use real JWT
                }, status=status.HTTP_200_OK)
        except Admin.DoesNotExist:
            # Email not found in Admin table, try Police next
            pass

        # Try Police login: search database for police office with this email
        try:
            police_office = PoliceOffice.objects.get(email=email)
            # Temporary security: check against hardcoded password
            if password == "testpass":
                # Serialize police office data (excludes password)
                serializer = PoliceOfficeLoginSerializer(police_office)
                return Response({
                    "message": "Police login successful",
                    "role": "police",
                    "user": serializer.data,
                    "token": "DUMMY_POLICE_TOKEN",  # TODO: Use real JWT
                }, status=status.HTTP_200_OK)
        except PoliceOffice.DoesNotExist:
            # Email not found in either table = invalid credentials
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        # Fallback: credentials didn't match any user
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)


# ============================================================================
# POLICE OFFICE ADMIN CRUD VIEW
# ============================================================================

class PoliceOfficeAdminViewSet(viewsets.ModelViewSet):
    # ENDPOINTS: GET, POST, PUT, DELETE for police offices
    # Used when: Admin manages (create/list/update/delete) police office accounts
    # Input: Office name, email, password, location, contact info
    # Output: Office data (for list/retrieve/update)
    # Note: Excludes test account to keep database clean

    # Start with all police offices except test account
    queryset = PoliceOffice.objects.all().exclude(email='test@crash.ph')
    serializer_class = PoliceOfficeCreateSerializer

    # Choose the right serializer based on the action being performed
    # Create/Update = need password handling (PoliceOfficeCreateSerializer)
    # Retrieve/List = no password needed (PoliceOfficeLoginSerializer)
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PoliceOfficeCreateSerializer
        return PoliceOfficeLoginSerializer

    # Override the save process when creating a new police office
    # Make sure we link it to the admin who created it
    def perform_create(self, serializer):
        # Get the admin ID from the request (who is creating this office)
        admin_id_str = self.request.data.get('created_by')
        if not admin_id_str:
            return Response({"created_by": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Find the admin in the database
        try:
            admin_instance = Admin.objects.get(admin_id=admin_id_str)
        except Admin.DoesNotExist:
            return Response({"created_by": "Admin account not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # Save the office with the admin link
        serializer.save(created_by=admin_instance)


# ============================================================================
# REPORT CRUD VIEW
# ============================================================================

class ReportViewSet(viewsets.ModelViewSet):
    # ENDPOINTS: GET (list/retrieve), POST (create), PUT (update), DELETE for reports
    # Used when: Citizens submit reports, police view/update them
    # Input: Crime category, description, GPS location (for creation)
    # Output: Report data with human-readable names (for list/retrieve)
    # Key feature: Automatically geocodes GPS to city/barangay names

    # Start with all reports, load related data efficiently (prevents N+1 queries)
    # select_related = fetch reporter and office data in one query
    queryset = Report.objects.all().select_related('reporter', 'assigned_office')

    # Choose the right serializer based on the action being performed
    # Create = needs location validation (ReportCreateSerializer)
    # Update = status only (ReportStatusUpdateSerializer, prevents tampering)
    # List/Retrieve = full data with human-readable names (ReportListSerializer)
    def get_serializer_class(self):
        if self.action == 'create':
            return ReportCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ReportStatusUpdateSerializer
        return ReportListSerializer

    # Override which reports are returned based on the request type
    # When listing: only show ACTIVE reports (hide resolved/canceled from main list)
    # When updating: show all reports (police need to access resolved ones)
    def get_queryset(self):
        if self.request.method == 'GET':
            # Exclude resolved and canceled to keep active list clean
            return self.queryset.exclude(status__in=['Resolved', 'Canceled']).order_by('-created_at')
        return self.queryset

    # Override the save process when creating a new report
    # Automatically: assign to nearest office, geocode location
    def perform_create(self, serializer):
        # Extract location data from request
        reporter_id = self.request.data.get('reporter')
        latitude = self.request.data.get('latitude')
        longitude = self.request.data.get('longitude')
        
        # Convert GPS coordinates to human-readable city/barangay names
        location_city, location_barangay = reverse_geocode(latitude, longitude)
        
        # Assign to the first police office in the system
        # TODO: Implement "nearest office" logic based on GPS coordinates
        try:
            assigned_office_instance = PoliceOffice.objects.all().first()
        except PoliceOffice.DoesNotExist:
            assigned_office_instance = None

        # Save the report with auto-calculated fields
        serializer.save(
            assigned_office=assigned_office_instance,
            reporter_id=reporter_id,
            location_city=location_city,
            location_barangay=location_barangay,
        )

    # Custom action: GET /reports/{id}/route/
    # Returns directions from police office to incident location
    @action(detail=True, methods=['get'])
    def route(self, request, pk=None):
        try:
            # Get the specific report
            report = self.get_object()
            assigned_office = report.assigned_office
            
            # Check if report is assigned to an office
            if not assigned_office:
                return Response({"detail": "Report is not yet assigned to an office."}, status=status.HTTP_400_BAD_REQUEST)

            # Generate directions from office to incident location
            routing_data = generate_directions_and_qr(
                start_lat=assigned_office.latitude,
                start_lng=assigned_office.longitude,
                end_lat=report.latitude,
                end_lng=report.longitude,
            )
            return Response(routing_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": f"Routing error: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Custom action: GET /reports/summary_resolved/
    # Returns all resolved reports (for resolved cases page)
    @action(detail=False, methods=['get'])
    def summary_resolved(self, request):
        # Get all resolved reports, sorted by most recent first
        resolved_reports = self.queryset.filter(status='Resolved').order_by('-updated_at')
        serializer = self.get_serializer(resolved_reports, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# MESSAGE CRUD VIEW (Nested under Reports)
# ============================================================================

class MessageViewSet(viewsets.ModelViewSet):
    # ENDPOINTS: GET (list), POST (create), PUT (update), DELETE for messages
    # Used when: Police and citizens exchange messages about a specific report
    # Input: Message content, sender ID, sender type (police/citizen)
    # Output: All messages for a report, sorted by time
    # Note: This is a nested resource (messages belong to a report)

    serializer_class = MessageSerializer

    # Override: only return messages for a specific report (from URL parameter)
    # URL format: /reports/{report_pk}/messages/
    # report_pk = report ID from the URL
    def get_queryset(self):
        report_id = self.kwargs.get('report_pk')  # Get report ID from URL
        if report_id:
            # Return messages for this report, sorted oldest to newest
            return Message.objects.filter(report_id=report_id).order_by('timestamp')
        # If no report ID in URL, return empty (shouldn't happen with proper routing)
        return Message.objects.none()

    # Override the save process when creating a new message
    # Ensure the message is linked to the correct report
    def perform_create(self, serializer):
        report_id = self.kwargs.get('report_pk')  # Get report ID from URL
        try:
            # Find the report in the database
            report_instance = Report.objects.get(report_id=report_id)
        except Report.DoesNotExist:
            raise NotFound(detail="Report not found.")
        # Save message linked to this report
        serializer.save(report=report_instance)


# ============================================================================
# CHECKPOINT CRUD VIEW
# ============================================================================

class CheckpointViewSet(viewsets.ModelViewSet):
    # ENDPOINTS: GET (list/retrieve), POST (create), PUT (update), DELETE for checkpoints
    # Used when: Admin manages police patrol checkpoint locations
    # Input: Checkpoint name, location, time range, assigned officers
    # Output: Checkpoint data with office name (for readability)
    # Key feature: Can filter for only "active" checkpoints (current time in range)

    # Start with all checkpoints, load office data efficiently, newest first
    queryset = Checkpoint.objects.all().select_related('office').order_by('-created_at')
    serializer_class = CheckpointSerializer

    # Custom action: GET /checkpoints/active/
    # Returns only checkpoints that are currently active (right now)
    @action(detail=False, methods=['get'])
    def active(self, request):
        # Get all checkpoints from database
        all_checkpoints = self.queryset
        # Filter to only those currently active (helper function checks time_start/time_end)
        active_checkpoints = get_active_checkpoints_list(all_checkpoints)
        # Serialize and return the active ones
        serializer = self.get_serializer(active_checkpoints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# MEDIA UPLOAD/VIEW
# ============================================================================

class MediaViewSet(viewsets.ModelViewSet):
    # ENDPOINTS: GET (list/retrieve), POST (upload), DELETE for media files
    # Used when: Citizens/police upload photos/videos as evidence for a report
    # Input: File, report ID, file type, uploader ID (in request body)
    # Output: File URL (stored in Supabase cloud) and metadata
    # Key feature: Files upload to cloud storage, not local disk

    queryset = Media.objects.all().select_related('report')
    serializer_class = MediaSerializer

    # Override: filter media by report_id if provided in query string
    # Usage: GET /media/?report_id=123 returns only files for that report
    def get_queryset(self):
        queryset = Media.objects.all().select_related('report').order_by('-uploaded_at')
        # Check if frontend passed report_id as a query parameter
        report_id = self.request.query_params.get('report_id')
        if report_id:
            # Filter to only files attached to this report
            queryset = queryset.filter(report_id=report_id)
        return queryset


# ============================================================================
# TOP LOCATIONS SUMMARY VIEW
# ============================================================================

class TopLocationsAPIView(APIView):
    # ENDPOINT: GET /reports/summary/top-locations/
    # Used when: Dashboard needs to show "where do crimes happen the most?"
    # Input: Optional filters (category, date_range)
    # Output: List of locations with crime counts, sorted by highest count first
    # Note: Groups by city/barangay/category combination

    def get(self, request):
        # Start with all resolved reports
        queryset = Report.objects.filter(status='Resolved')
        
        # Optional filter: by crime category
        category = request.query_params.get('category')
        if category:
            queryset = queryset.filter(category__iexact=category)  # Case-insensitive
        
        # Optional filter: by date range (default: all time)
        date_range = request.query_params.get('date_range')
        if date_range == '30_days':
            date_cutoff = datetime.now() - timedelta(days=30)
            queryset = queryset.filter(created_at__gte=date_cutoff)

        # Group reports by location and category, count how many in each group
        # Returns something like: {city: "Manila", barangay: "Tondo", category: "Robbery", count: 5}
        aggregated_data = queryset.values(
            'location_city',
            'location_barangay',
            'category'
        ).annotate(report_count=Count('report_id')).order_by('-report_count')[:10]  # Top 10 only

        # Format the data for JSON response
        results = [
            {
                'location_city': item['location_city'],
                'location_barangay': item['location_barangay'],
                'category': item['category'],
                'report_count': item['report_count'],
            }
            for item in aggregated_data
            if item['location_city']  # Skip if location is missing
        ]

        return Response(results, status=status.HTTP_200_OK)


# ============================================================================
# ADMIN MAP VIEW (Dashboard Map)
# ============================================================================

class AdminMapAPIView(APIView):
    # ENDPOINT: GET /admin/map/
    # Used when: Admin dashboard loads the interactive map
    # Output: All active reports + all police offices + currently active checkpoints
    # Purpose: Shows real-time crime incidents, police locations, and patrols on a map

    def get(self, request):
        # Get all ACTIVE reports (exclude resolved and canceled from map view)
        active_reports = Report.objects.all().exclude(status__in=['Resolved', 'Canceled'])
        reports_serializer = ReportListSerializer(active_reports, many=True)

        # Get all police office locations
        all_offices = PoliceOffice.objects.all()
        offices_data = PoliceOfficeLoginSerializer(all_offices, many=True).data

        # Get currently ACTIVE checkpoints (based on current time)
        all_checkpoints = Checkpoint.objects.all().select_related('office')
        active_checkpoints = get_active_checkpoints_list(all_checkpoints)
        checkpoints_data = CheckpointSerializer(active_checkpoints, many=True).data

        # Return all three data types in one response
        return Response({
            'active_reports': reports_serializer.data,
            'police_offices': offices_data,
            'active_checkpoints': checkpoints_data,
        }, status=status.HTTP_200_OK)


# ============================================================================
# ANALYTICS UPDATE VIEW (Cache Manager)
# ============================================================================

class AnalyticsUpdateAPIView(APIView):
    # ENDPOINT: POST /analytics/update/
    # Used when: Admin wants to refresh the analytics cache (or called periodically)
    # Process: Re-calculates statistics for ALL location/category combinations
    # Purpose: Pre-calculates data so analytics page loads instantly (no heavy queries)
    # Safety: Uses a "lock" to prevent multiple updates running at the same time

    def post(self, request):
        # Prevent two updates from running simultaneously (causes database issues)
        # cache.add() returns False if key already exists
        lock_key = 'analytics_update_lock'
        lock_acquired = cache.add(lock_key, 'locked', timeout=60)  # Lock expires after 60 seconds
        if not lock_acquired:
            # Another update is already in progress
            return Response({"detail": "Analytics update already in progress. Please wait and try again."}, status=status.HTTP_409_CONFLICT)

        try:
            # Group all resolved reports by location and category, count each group
            aggregated_data = Report.objects.filter(status='Resolved').values(
                'location_city',
                'location_barangay',
                'category',
            ).annotate(report_count=Count('report_id'))

            # For each location/category combination, update or create SummaryAnalytics record
            for item in aggregated_data:
                # Skip if location wasn't geocoded yet
                if not item['location_city']:
                    continue
                # Update existing record or create new one if it doesn't exist
                SummaryAnalytics.objects.update_or_create(
                    location_city=item['location_city'],
                    location_barangay=item['location_barangay'],
                    category=item['category'],
                    defaults={  # These fields get updated/set
                        'report_count': item['report_count'],
                        'last_updated': datetime.now(),
                    },
                )

            return Response({"detail": "Analytics summary table updated successfully."}, status=status.HTTP_200_OK)
        finally:
            # Always remove the lock, even if there's an error
            # This prevents the system from getting stuck
            cache.delete(lock_key)
