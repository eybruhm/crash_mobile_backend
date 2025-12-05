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


class LoginAPIView(APIView):
    """Handles login for both Admin and Police roles."""

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({"detail": "Email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Attempt Admin Login (temporary password check)
        try:
            admin_user = Admin.objects.get(email=email)
            if password == "testpass":
                serializer = AdminSerializer(admin_user)
                return Response({
                    "message": "Admin login successful",
                    "role": "admin",
                    "user": serializer.data,
                    "token": "DUMMY_ADMIN_TOKEN",
                }, status=status.HTTP_200_OK)
        except Admin.DoesNotExist:
            pass

        # 2. Attempt Police Login (temporary password check)
        try:
            police_office = PoliceOffice.objects.get(email=email)
            if password == "testpass":
                serializer = PoliceOfficeLoginSerializer(police_office)
                return Response({
                    "message": "Police login successful",
                    "role": "police",
                    "user": serializer.data,
                    "token": "DUMMY_POLICE_TOKEN",
                }, status=status.HTTP_200_OK)
        except PoliceOffice.DoesNotExist:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)


class PoliceOfficeAdminViewSet(viewsets.ModelViewSet):
    queryset = PoliceOffice.objects.all().exclude(email='test@crash.ph')
    serializer_class = PoliceOfficeCreateSerializer

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PoliceOfficeCreateSerializer
        return PoliceOfficeLoginSerializer

    def perform_create(self, serializer):
        admin_id_str = self.request.data.get('created_by')
        if not admin_id_str:
            return Response({"created_by": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            admin_instance = Admin.objects.get(admin_id=admin_id_str)
        except Admin.DoesNotExist:
            return Response({"created_by": "Admin account not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer.save(created_by=admin_instance)


class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.all().select_related('reporter', 'assigned_office')

    def get_serializer_class(self):
        if self.action == 'create':
            return ReportCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ReportStatusUpdateSerializer
        return ReportListSerializer

    def get_queryset(self):
        if self.request.method == 'GET':
            return self.queryset.exclude(status__in=['Resolved', 'Canceled']).order_by('-created_at')
        return self.queryset

    def perform_create(self, serializer):
        reporter_id = self.request.data.get('reporter')
        latitude = self.request.data.get('latitude')
        longitude = self.request.data.get('longitude')
        location_city, location_barangay = reverse_geocode(latitude, longitude)
        try:
            assigned_office_instance = PoliceOffice.objects.all().first()
        except PoliceOffice.DoesNotExist:
            assigned_office_instance = None

        serializer.save(
            assigned_office=assigned_office_instance,
            reporter_id=reporter_id,
            location_city=location_city,
            location_barangay=location_barangay,
        )

    @action(detail=True, methods=['get'])
    def route(self, request, pk=None):
        try:
            report = self.get_object()
            assigned_office = report.assigned_office
            if not assigned_office:
                return Response({"detail": "Report is not yet assigned to an office."}, status=status.HTTP_400_BAD_REQUEST)

            routing_data = generate_directions_and_qr(
                start_lat=assigned_office.latitude,
                start_lng=assigned_office.longitude,
                end_lat=report.latitude,
                end_lng=report.longitude,
            )
            return Response(routing_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": f"Routing error: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def summary_resolved(self, request):
        resolved_reports = self.queryset.filter(status='Resolved').order_by('-updated_at')
        serializer = self.get_serializer(resolved_reports, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer

    def get_queryset(self):
        report_id = self.kwargs.get('report_pk')
        if report_id:
            return Message.objects.filter(report_id=report_id).order_by('timestamp')
        return Message.objects.none()

    def perform_create(self, serializer):
        report_id = self.kwargs.get('report_pk')
        try:
            report_instance = Report.objects.get(report_id=report_id)
        except Report.DoesNotExist:
            raise NotFound(detail="Report not found.")
        serializer.save(report=report_instance)


class CheckpointViewSet(viewsets.ModelViewSet):
    queryset = Checkpoint.objects.all().select_related('office').order_by('-created_at')
    serializer_class = CheckpointSerializer

    @action(detail=False, methods=['get'])
    def active(self, request):
        all_checkpoints = self.queryset
        active_checkpoints = get_active_checkpoints_list(all_checkpoints)
        serializer = self.get_serializer(active_checkpoints, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MediaViewSet(viewsets.ModelViewSet):
    queryset = Media.objects.all().select_related('report')
    serializer_class = MediaSerializer

    def get_queryset(self):
        queryset = Media.objects.all().select_related('report').order_by('-uploaded_at')
        report_id = self.request.query_params.get('report_id')
        if report_id:
            queryset = queryset.filter(report_id=report_id)
        return queryset


class TopLocationsAPIView(APIView):
    """GET /reports/summary/top-locations/ aggregated by city/barangay and category."""

    def get(self, request):
        queryset = Report.objects.filter(status='Resolved')
        category = request.query_params.get('category')
        date_range = request.query_params.get('date_range')

        if category:
            queryset = queryset.filter(category__iexact=category)
        if date_range == '30_days':
            date_cutoff = datetime.now() - timedelta(days=30)
            queryset = queryset.filter(created_at__gte=date_cutoff)

        aggregated_data = queryset.values(
            'location_city',
            'location_barangay',
            'category'
        ).annotate(report_count=Count('report_id')).order_by('-report_count')[:10]

        results = [
            {
                'location_city': item['location_city'],
                'location_barangay': item['location_barangay'],
                'category': item['category'],
                'report_count': item['report_count'],
            }
            for item in aggregated_data
            if item['location_city']
        ]

        return Response(results, status=status.HTTP_200_OK)


class AdminMapAPIView(APIView):
    """Provides aggregated data for the Admin Active Map (Reports, Offices, Active Checkpoints)."""

    def get(self, request):
        active_reports = Report.objects.all().exclude(status__in=['Resolved', 'Canceled'])
        reports_serializer = ReportListSerializer(active_reports, many=True)

        all_offices = PoliceOffice.objects.all()
        offices_data = PoliceOfficeLoginSerializer(all_offices, many=True).data

        all_checkpoints = Checkpoint.objects.all().select_related('office')
        active_checkpoints = get_active_checkpoints_list(all_checkpoints)
        checkpoints_data = CheckpointSerializer(active_checkpoints, many=True).data

        return Response({
            'active_reports': reports_serializer.data,
            'police_offices': offices_data,
            'active_checkpoints': checkpoints_data,
        }, status=status.HTTP_200_OK)


class AnalyticsUpdateAPIView(APIView):
    """Manually triggers the process to update the Summary Analytics performance table."""

    def post(self, request):
        lock_key = 'analytics_update_lock'
        lock_acquired = cache.add(lock_key, 'locked', timeout=60)
        if not lock_acquired:
            return Response({"detail": "Analytics update already in progress. Please wait and try again."}, status=status.HTTP_409_CONFLICT)

        try:
            aggregated_data = Report.objects.filter(status='Resolved').values(
                'location_city',
                'location_barangay',
                'category',
            ).annotate(report_count=Count('report_id'))

            for item in aggregated_data:
                if not item['location_city']:
                    continue
                SummaryAnalytics.objects.update_or_create(
                    location_city=item['location_city'],
                    location_barangay=item['location_barangay'],
                    category=item['category'],
                    defaults={
                        'report_count': item['report_count'],
                        'last_updated': datetime.now(),
                    },
                )

            return Response({"detail": "Analytics summary table updated successfully."}, status=status.HTTP_200_OK)
        finally:
            cache.delete(lock_key)
