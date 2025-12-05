from django.shortcuts import render
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from rest_framework.decorators import action
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Count, Avg, Sum, F, DurationField, ExpressionWrapper, Q
from django.core.cache import cache
from django.template.loader import render_to_string
from weasyprint import HTML
from .models import (
    Admin, 
    PoliceOffice, 
    Report, 
    Message,
    Checkpoint,
    Media,
    SummaryAnalytics,
    User,
)
from .serializers import (
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
from .services import (
    generate_directions_and_qr, 
    reverse_geocode, 
    get_active_checkpoints_list,
)

def parse_filters(request):
    days = int(request.query_params.get('days', 30))
    scope = (request.query_params.get('scope') or 'all').lower()
    office_id = request.query_params.get('office_id')
    city = request.query_params.get('city')
    barangay = request.query_params.get('barangay')
    category = request.query_params.get('category')  # None or specific, treat 'all' as None

    if category and category.lower() == 'all':
        category = None

    since = timezone.now() - timedelta(days=days)
    return {
        'days': days,
        'since': since,
        'scope': scope,
        'office_id': office_id,
        'city': city,
        'barangay': barangay,
        'category': category,
    }

def apply_common_filters(qs, f):
    # timeframe filter
    qs = qs.filter(created_at__gte=f['since'])

    # scope filter
    if f['scope'] == 'our_office' and f['office_id']:
        qs = qs.filter(assigned_office_id=f['office_id'])

    # location filters
    if f['city']:
        qs = qs.filter(location_city__iexact=f['city'])
        if f['barangay']:
            qs = qs.filter(location_barangay__iexact=f['barangay'])

    # category filter
    if f['category']:
        qs = qs.filter(category__iexact=f['category'])

    return qs

# Create your views here.
class LoginAPIView(APIView):
    # handles login for both Admin and Police roles

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password') # Plaintext for now; to be hashed later

        if not email or not password:
            return Response({"detail": "Email and password are required."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        # 1. Attempt Admin Login
        try:
            admin_user = Admin.objects.get(email=email)
            # TEMPORARY CHECK: Replace with actual hashing check later (Day 3 update)
            if password == "testpass": 
                serializer = AdminSerializer(admin_user)
                return Response({
                    "message": "Admin login successful",
                    "role": "admin",
                    "user": serializer.data,
                    "token": "DUMMY_ADMIN_TOKEN"
                }, status=status.HTTP_200_OK)
        except Admin.DoesNotExist:
            pass # Continue to Police check

        # 2. Attempt Police Login
        try:
            police_office = PoliceOffice.objects.get(email=email)
            # TEMPORARY CHECK: Replace with actual hashing check later (Day 3 update)
            if password == "testpass":
                serializer = PoliceOfficeLoginSerializer(police_office)
                return Response({
                    "message": "Police login successful",
                    "role": "police",
                    "user": serializer.data,
                    "token": "DUMMY_POLICE_TOKEN"
                }, status=status.HTTP_200_OK)
        except PoliceOffice.DoesNotExist:
            # 3. If neither found
            return Response({"detail": "Invalid credentials."}, 
                            status=status.HTTP_401_UNAUTHORIZED)
        
        # 4. Fallback for incorrect password (if email found but temp password is wrong)
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
    
class PoliceOfficeAdminViewSet(viewsets.ModelViewSet):
    # queryset = PoliceOffice.objects.all() # Fetch all offices for Admin view
    
    # CRITICAL: Filter to exclude the main Admin login account
    queryset = PoliceOffice.objects.all().exclude(email='test@crash.ph') 
    
    serializer_class = PoliceOfficeCreateSerializer
    # permission_classes = [IsAuthenticated, IsAdminUser] # You'll add IsAdminUser later

    # --- Override methods for different serializers ---
    
    def get_serializer_class(self):
        """Use the standard PoliceOfficeLoginSerializer for list/read, 
        but use the creation serializer for POST/CREATE."""
        if self.action in ['create', 'update', 'partial_update']:
            return PoliceOfficeCreateSerializer
        return PoliceOfficeLoginSerializer # Use the safer LoginSerializer for viewing

    # Automatically set the created_by field to the logged-in Admin
    def perform_create(self, serializer):
        # 1. Get the admin_id string from the request data
        admin_id_str = self.request.data.get('created_by', None)

        if not admin_id_str:
            # Handle case where created_by is missing (Optional: raise a validation error here)
            return Response({"created_by": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 2. Fetch the actual Admin object using the UUID string
            admin_instance = Admin.objects.get(admin_id=admin_id_str)
        except Admin.DoesNotExist:
            # Handle case where the provided UUID doesn't exist
            return Response({"created_by": "Admin account not found."}, status=status.HTTP_404_NOT_FOUND)

        # 3. Pass the *object instance* to the serializer.save() method
        # Django will automatically extract the primary key (admin_id) for the DB insertion.
        serializer.save(created_by=admin_instance)

class ReportViewSet(viewsets.ModelViewSet):
    # Base queryset for all report operations
    queryset = Report.objects.all().select_related('reporter', 'assigned_office')
    
    def get_serializer_class(self):
        """Use different serializers for input (create) vs. output (read)."""
        if self.action == 'create':
            return ReportCreateSerializer
        return ReportListSerializer # Use the list serializer for GET requests

    # --- Step 1: Implement Police Dashboard Read (Filtering) ---
    def get_queryset(self):
        # Implement the logic for Police Dashboard: fetch all active reports
        if self.request.method == 'GET':
            # Active status means NOT Resolved or Canceled 
            return self.queryset.exclude(status__in=['Resolved', 'Canceled']).order_by('-created_at')
        
        # For other methods (like PUT, DELETE), use the base queryset
        return self.queryset

    # --- Step 2: Implement Report Submission (Nearest Office Stub) ---
    def perform_create(self, serializer):
        # NOTE: In a real system, reporter_id comes from the auth token, 
        # but for Postman simulation, we get it from the request data for now.
        reporter_id = self.request.data.get('reporter')
        latitude = self.request.data.get('latitude')
        longitude = self.request.data.get('longitude')
        
        # 1. Geocode the Coordinates
        location_city, location_barangay = reverse_geocode(latitude, longitude)

        # 2. Simulate Nearest Office Assignment (STUB)
        # Full distance calculation (GIS) is Day X, so for now, assign to the first existing office.
        try:
            nearest_office = PoliceOffice.objects.all().first()
            assigned_office_instance = nearest_office
        except PoliceOffice.DoesNotExist:
            assigned_office_instance = None # If no offices exist

        # 3. Save the report with the assigned office and reporter ID
        serializer.save(
            assigned_office=assigned_office_instance,
            reporter_id=reporter_id, # Django handles UUID string for reporter_id correctly here
            # Pass the geocoded results for saving
            location_city=location_city,        
            location_barangay=location_barangay 
        )

    # --- Step 3: Implement Report Status Update ---
    def get_serializer_class(self):
        """Use different serializers based on the action."""
        if self.action == 'create':
            return ReportCreateSerializer
        # Use the specific serializer for PUT/PATCH operations
        if self.action in ['update', 'partial_update']:
            return ReportStatusUpdateSerializer
        return ReportListSerializer # Default for GET (list/retrieve)

    # GET /reports/{report_id}/route/
    @action(detail=True, methods=['get'])
    def route(self, request, pk=None):
        """
        Calculates and returns the routing URL and QR code for a specific report.
        """
        try:
            # 1. Get Report details (User's location)
            report = self.get_object() # Fetches the report instance based on URL ID (pk)

            # 2. Get Police Office details (Start location)
            assigned_office = report.assigned_office

            if not assigned_office:
                return Response({"detail": "Report is not yet assigned to an office."}, 
                                status=status.HTTP_400_BAD_REQUEST)

            # 3. Call the Service function
            routing_data = generate_directions_and_qr(
                start_lat=assigned_office.latitude,
                start_lng=assigned_office.longitude,
                end_lat=report.latitude,
                end_lng=report.longitude
            )

            # 4. Return the result
            return Response(routing_data, status=status.HTTP_200_OK)

        except Exception as e:
            # Basic error handling for key configuration issues
            return Response({"detail": f"Routing error: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # NEW ACTION: GET /reports/summary/resolved/
    @action(detail=False, methods=['get'])
    def summary_resolved(self, request):
        """Fetches all reports with status 'Resolved' for the Summary Dashboard."""
        
        # Filter the entire queryset for 'Resolved' status
        resolved_reports = self.queryset.filter(status='Resolved').order_by('-updated_at')
        
        # Use the ReportListSerializer for consistent output format
        serializer = self.get_serializer(resolved_reports, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    
    # We define this dynamically based on the URL path
    def get_queryset(self):
        # 1. Get report_id from the URL path (using the correct 'report_pk' key)
        report_id = self.kwargs.get('report_pk') # <--- CORRECTED KEY
        
        if report_id:
            # 2. Filter messages only for the specified report
            return Message.objects.filter(report_id=report_id).order_by('timestamp')
        return Message.objects.none() # Return empty if no report_id is provided

    def perform_create(self, serializer):
        # 1. Get report_id from the URL path (Change key from 'report_id' to 'report_pk')
        report_id = self.kwargs.get('report_pk') 
        
        # 2. Assign the report to the new message
        try:
            report_instance = Report.objects.get(report_id=report_id)
        except Report.DoesNotExist:
            # 3. Raise the correct exception type
            raise NotFound(detail="Report not found.") # <-- CORRECTED SYNTAX
        
        # 3. Simulate sender identification (Police flow)
        # NOTE: In a real authenticated scenario, you would get sender_id and sender_type 
        # from the logged-in user's token (PoliceOffice ID and 'police' role).
        
        # For testing the Police POST (Day 7):
        # The frontend provides sender_id, sender_type, and receiver_id in the body.
        
        serializer.save(
            report=report_instance,
            # For the POST request, the necessary sender/receiver IDs are expected
            # in the request body for testing flexibility.
        )

class CheckpointViewSet(viewsets.ModelViewSet):
    # Fetch all checkpoints and pre-fetch the related office name
    queryset = Checkpoint.objects.all().select_related('office').order_by('-created_at') 
    serializer_class = CheckpointSerializer
    
    # Optional: We can add perform_create here to link the checkpoint to the PoliceOffice 
    # based on the Admin's or Police Officer's identity, but for now, 
    # we rely on 'office' being passed in the POST body.

    @action(detail=False, methods=['get'])
    def active(self, request):
        """Filters and returns only checkpoints active at the current server time."""
        # Note: We call select_related in the service function to avoid database access errors
        all_checkpoints = self.queryset
        active_checkpoints = get_active_checkpoints_list(all_checkpoints) # <-- Call Service

        # Serialize the filtered list
        serializer = self.get_serializer(active_checkpoints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class MediaViewSet(viewsets.ModelViewSet):
    # Allow full CRUD access (Admin/Police/Citizen may upload media)
    queryset = Media.objects.all().select_related('report')
    serializer_class = MediaSerializer
    
    def get_queryset(self):
        # Start with the base queryset
        queryset = Media.objects.all().select_related('report').order_by('-uploaded_at')
        
        # 1. Check for a 'report_id' query parameter in the URL
        report_id = self.request.query_params.get('report_id')
        
        if report_id:
            # 2. If present, filter the queryset by the foreign key (report_id)
            # The filter key must match the foreign key field name on the model: 'report'
            queryset = queryset.filter(report_id=report_id)
            
        return queryset
    
    # Optional: You can implement permissions here to restrict uploads to logged-in users.

class TopLocationsAPIView(APIView):
    """
    Implements GET /reports/summary/top-locations/ 
    Calculates aggregated report counts filtered by location, category, and date.
    """
    
    def get(self, request):
        # Start with all Reports where the status is Resolved (as per project logic)
        queryset = Report.objects.filter(status='Resolved')
        
        # --- 1. Filtering Logic (Query Parameters) ---
        category = request.query_params.get('category')
        date_range = request.query_params.get('date_range') # Example: '30_days'
        
        # Filter by Category
        if category:
            queryset = queryset.filter(category__iexact=category) # __iexact is case-insensitive
            
        # Filter by Date Range (Example Logic)
        if date_range == '30_days':
            # Calculate the date 30 days ago
            date_cutoff = datetime.now() - timedelta(days=30)
            queryset = queryset.filter(created_at__gte=date_cutoff)
            
        # --- 2. Joining Data and Aggregation ---
        
        # Reports get the location details (city, barangay)
        # Then group by the location fields and category, and count the reports.
        aggregated_data = queryset.values(
            'location_city',           
            'location_barangay',       
            'category'
        ).annotate(
            report_count=Count('report_id') # Count the reports in each group
        ).order_by('-report_count')[:10] # Take the top 10 results
        
        # --- 3. Formatting Output ---
        
        # Remap the keys for cleaner JSON output (since aggregated_data is a dictionary list)
        results = [
            {
                'location_city': item['location_city'],
                'location_barangay': item['location_barangay'],
                'category': item['category'],
                'report_count': item['report_count']
            }
            for item in aggregated_data
            # Filter out entries where location data is missing (reporter__city is None)
            if item['location_city']
        ]

        return Response(results, status=status.HTTP_200_OK)
    
class AdminMapAPIView(APIView):
    """Provides aggregated data for the Admin Active Map (Reports, Offices, Active Checkpoints)."""
    
    def get(self, request):
        # 1. Active Reports (Active status only)
        active_reports = Report.objects.all().exclude(status__in=['Resolved', 'Canceled'])
        reports_serializer = ReportListSerializer(active_reports, many=True)
        
        # 2. Police Offices (All offices are always shown)
        all_offices = PoliceOffice.objects.all()
        offices_data = PoliceOfficeLoginSerializer(all_offices, many=True).data
        
        # 3. Active Checkpoints (Using the centralized service logic)
        all_checkpoints = Checkpoint.objects.all().select_related('office')
        active_checkpoints = get_active_checkpoints_list(all_checkpoints) # <-- Call Service

        checkpoints_data = CheckpointSerializer(active_checkpoints, many=True).data

        return Response({
            'active_reports': reports_serializer.data,
            'police_offices': offices_data,
            'active_checkpoints': checkpoints_data,
        }, status=status.HTTP_200_OK)
    
class AnalyticsUpdateAPIView(APIView):
    """Manually triggers the process to update the Summary Analytics performance table."""
    
    def post(self, request):
        # 🔒 STEP 1: Try to acquire the lock
        lock_key = 'analytics_update_lock'
        lock_acquired = cache.add(lock_key, 'locked', timeout=60)
        
        # If lock already exists, someone else is updating
        if not lock_acquired:
            return Response({
                "detail": "Analytics update already in progress. Please wait and try again."
            }, status=status.HTTP_409_CONFLICT)
        
        try:
            # 🔥 STEP 2: Perform the update (protected by lock)
            # 1. Aggregate Data from tbl_reports (Same query as Day 11)
            aggregated_data = Report.objects.filter(status='Resolved').values(
                'location_city', 
                'location_barangay', 
                'category'
            ).annotate(
                report_count=Count('report_id')
            )
            
            # 2. Iterate and Update/Insert into tbl_summary_analytics
            for item in aggregated_data:
                if not item['location_city']:
                    continue # Skip reports without valid geocoded data
                    
                SummaryAnalytics.objects.update_or_create(
                    location_city=item['location_city'],
                    location_barangay=item['location_barangay'],
                    category=item['category'],
                    defaults={
                        'report_count': item['report_count'],
                        'last_updated': timezone.now()
                    }
                )

            return Response({
                "detail": "Analytics summary table updated successfully."
            }, status=status.HTTP_200_OK)
            
        finally:
            # 🔓 STEP 3: Always release the lock when done (even if error occurs)
            cache.delete(lock_key)

class AnalyticsOverviewSummaryAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.all(), f)

        # Total assigned in scope (all statuses)
        total_assigned = base.count()

        # Average resolution time for resolved in scope
        resolved = base.filter(status='Resolved', updated_at__isnull=False)
        resolution_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        avg_res = resolved.annotate(res_time=resolution_delta).aggregate(avg=Avg('res_time'))['avg']

        # format avg duration into "Xd HH:MM:SS"
        avg_res_str = "N/A"
        if avg_res:
            total_seconds = int(avg_res.total_seconds())
            days = total_seconds // 86400
            rem = total_seconds % 86400
            h = rem // 3600
            m = (rem % 3600) // 60
            s = rem % 60
            avg_res_str = (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "total_assigned": total_assigned,
            "average_resolution_time": avg_res_str,
        }, status=status.HTTP_200_OK)

class LocationHotspotsAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved'), f)

        total = base.count()
        items = []

        if not f['city']:
            # Case A: Top 5 city-barangay
            qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
            items = list(qs)
        elif f['city'] and not f['barangay']:
            # Case B: Top 5 barangays within city
            qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
            items = list(qs)
        else:
            # Case C: Single selected barangay
            count = base.count()
            items = [{
                'location_city': f['city'],
                'location_barangay': f['barangay'],
                'report_count': count
            }]

        # add percent of total
        for i in items:
            i['report_percent'] = (i['report_count'] / total * 100.0) if total else 0.0

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "total_resolved": total,
            "results": items
        }, status=status.HTTP_200_OK)
    
class CategoryConcentrationAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved'), f)

        total = base.count()
        if not f['category']:
            qs = base.values('category').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
            results = []
            for row in qs:
                pct = (row['report_count'] / total * 100.0) if total else 0.0
                results.append({
                    'category': row['category'],
                    'report_count': row['report_count'],
                    'percentage': pct
                })
        else:
            count = base.count()
            pct = (count / total * 100.0) if total else 0.0
            results = [{
                'category': f['category'],
                'report_count': count,
                'percentage': pct
            }]

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "total_resolved": total,
            "results": results
        }, status=status.HTTP_200_OK)
    
class ResolvedCasesAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')

        # annotate resolution time
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)

        data = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            # format duration
            d = r['resolution_time']
            if d:
                total_seconds = int(d.total_seconds())
                days = total_seconds // 86400
                rem = total_seconds % 86400
                h,m,s = rem // 3600, (rem % 3600)//60, rem % 60
                res_str = (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"
            else:
                res_str = "N/A"
            r['resolution_time_str'] = res_str
            data.append(r)

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "count": len(data),
            "results": data
        }, status=status.HTTP_200_OK)
    
class AnalyticsExportAPIView(APIView):
    """
    Generates a PDF that captures Overview + Location Hotspots + Category Concentration
    using the same filters in 4.1.
    """
    def get(self, request):
        f = parse_filters(request)
        # Build each section by calling the same logic as APIs above
        # Overview
        base = apply_common_filters(Report.objects.all(), f)
        total_assigned = base.count()
        resolved = base.filter(status='Resolved', updated_at__isnull=False)
        resolution_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        avg_res = resolved.annotate(res_time=resolution_delta).aggregate(avg=Avg('res_time'))['avg']
        avg_res_str = "N/A"
        if avg_res:
            total_seconds = int(avg_res.total_seconds()); days = total_seconds // 86400
            rem = total_seconds % 86400; h=rem//3600; m=(rem%3600)//60; s=rem%60
            avg_res_str = (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"

        # Location hotspots (re-use the exact logic)
        loc_ctx = LocationHotspotsAPIView().get(request).data
        cat_ctx = CategoryConcentrationAPIView().get(request).data

        # Calculate percentage: filtered total as % of all reports (without filters)
        all_reports_total = Report.objects.count()
        total_reports_percent = (total_assigned / all_reports_total * 100.0) if all_reports_total else 0.0

        # Fetch office data - always use office_id if provided (even for all_offices scope)
        # This allows logged-in user's office to be the author regardless of scope
        office_name = 'All Offices'
        head_officer_name = 'N/A'
        if f['office_id']:
            try:
                office = PoliceOffice.objects.get(office_id=f['office_id'])
                office_name = office.office_name
                head_officer_name = office.head_officer or 'N/A'
            except PoliceOffice.DoesNotExist:
                pass

        # Choose template (example: use your deep dive or a combined template)
        html = render_to_string(
            'report_crime_deep_dive.html',
            {
                'category_filter_name': f['category'] or 'All Categories',
                'audit_scope': 'Our Office' if f['scope']=='our_office' else 'All Offices',
                'timeframe_days': f['days'],
                'total_reports': loc_ctx['total_resolved'],
                'total_reports_percent': total_reports_percent,
                'top_locations_list': [
                    {
                        'location_city': i.get('location_city'),
                        'location_barangay': i.get('location_barangay'),
                        'report_count': i['report_count'],
                        'report_percent': i['report_percent'],
                    } for i in loc_ctx['results']
                ],
                'category_is_specific': bool(f['category']),
                'category_results': cat_ctx['results'],
                'category_total': cat_ctx['total_resolved'],
                'avg_resolution_time': avg_res_str,
                'office_name': office_name,
                'head_officer_name': head_officer_name,
                'current_datetime': timezone.now(),
            }
        )
        pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        
        # Generate dynamic filename
        filename_parts = [f"analytics_{f['days']}days"]
        if f['scope'] == 'our_office':
            filename_parts.append('our_office')
        else:
            filename_parts.append('all_offices')
        if f['category']:
            filename_parts.append(f['category'].replace(' ', '_').lower())
        if f['city']:
            filename_parts.append(f['city'].replace(' ', '_').lower())
        filename = '_'.join(filename_parts) + '.pdf'
        
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

class ResolvedCasesExportAPIView(APIView):
    """Exports a LIST of resolved cases (table format) with filters applied."""
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)

        rows = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            d = r['resolution_time']
            if d:
                total_seconds = int(d.total_seconds())
                days = total_seconds // 86400
                rem = total_seconds % 86400
                h,m,s = rem // 3600, (rem % 3600)//60, rem % 60
                r['resolution_time_str'] = (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"
            else:
                r['resolution_time_str'] = "N/A"
            # Format UUID for display
            uuid_str = str(r['report_id'])
            r['report_id_short'] = f"{uuid_str[:5]}...{uuid_str[-5:]}"
            rows.append(r)

        # Fetch office data if scope is our_office
        office_name = 'All Offices'
        head_officer_name = 'N/A'
        if f['scope'] == 'our_office' and f['office_id']:
            try:
                office = PoliceOffice.objects.get(office_id=f['office_id'])
                office_name = office.office_name
                head_officer_name = office.head_officer or 'N/A'
            except PoliceOffice.DoesNotExist:
                pass

        html = render_to_string('report_resolved_cases_list.html', {
            'timeframe_days': f['days'],
            'audit_scope': 'Our Office' if f['scope']=='our_office' else 'All Offices',
            'city': f['city'],
            'barangay': f['barangay'],
            'category': f['category'],
            'rows': rows,
            'office_name': office_name,
            'head_officer_name': head_officer_name,
            'current_datetime': timezone.now(),
        })
        pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        
        # Generate dynamic filename
        filename_parts = [f"resolved_cases_{f['days']}days"]
        if f['scope'] == 'our_office':
            filename_parts.append('our_office')
        else:
            filename_parts.append('all_offices')
        if f['category']:
            filename_parts.append(f['category'].replace(' ', '_').lower())
        if f['city']:
            filename_parts.append(f['city'].replace(' ', '_').lower())
        filename = '_'.join(filename_parts) + '.pdf'
        
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

class SingleReportExportAPIView(APIView):
    """Exports a SINGLE report's detailed case file."""
    def get(self, request, report_id):
        try:
            # Fetch the report with related data
            report = Report.objects.select_related('reporter', 'assigned_office').get(
                report_id=report_id,
                status='Resolved'
            )
        except Report.DoesNotExist:
            return HttpResponse("Report not found or not resolved.", status=404)

        # Calculate resolution time
        if report.updated_at and report.created_at:
            delta = report.updated_at - report.created_at
            total_seconds = int(delta.total_seconds())
            days = total_seconds // 86400
            rem = total_seconds % 86400
            h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
            calculated_resolution_time = (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"
        else:
            calculated_resolution_time = "N/A"

        # Format office UUID for display
        office_id_str = str(report.assigned_office.office_id)
        office_id_short = f"{office_id_str[:7]}...{office_id_str[-7:]}"
        
        # Render template with full report details
        html = render_to_string('report_resolved_cases_audit.html', {
            'report': report,
            'reporter': report.reporter,
            'assigned_office': report.assigned_office,
            'office_id_short': office_id_short,
            'calculated_resolution_time': calculated_resolution_time,
            'current_datetime': timezone.now(),
            'office_id_str': office_id_str,
        })
        
        pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="case_file_{report.report_id}.pdf"'
        return response