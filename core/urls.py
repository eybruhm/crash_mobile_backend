# ============================================================================
# URLS: Route mapping - connects HTTP requests to view handlers
# Think of this as a "phone directory" - when someone calls a number (URL),
# we tell Django which view handler (function) should answer that call.
# Example: GET /api/reports/ => ReportViewSet.list() method
# ============================================================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from .views import (
    LoginAPIView,
    PoliceOfficeAdminViewSet,
    ReportViewSet,
    MessageViewSet,
    CheckpointViewSet,
    MediaViewSet,
    TopLocationsAPIView,
    AdminMapAPIView,
    AnalyticsUpdateAPIView,
)
from .views.analytics import (
    AnalyticsOverviewSummaryAPIView,
    LocationHotspotsAPIView,
    CategoryConcentrationAPIView,
    AnalyticsExportAPIView,
)
from .views.reports import (
    ResolvedCasesAPIView,
    ResolvedCasesExportAPIView,
    SingleReportExportAPIView,
)


# ============================================================================
# ROUTER SETUP: Auto-generate URL patterns for CRUD operations
# DefaultRouter = automatically creates URL patterns for viewsets
# Instead of writing 5 endpoints manually, register a viewset and get 5 for free
# ============================================================================

# Create a main router instance
router = DefaultRouter()

# Register the Police Office ViewSet for admin CRUD operations
# This generates:
#   GET    /admin/police-offices/          => list all offices
#   POST   /admin/police-offices/          => create new office
#   GET    /admin/police-offices/{id}/     => get specific office
#   PUT    /admin/police-offices/{id}/     => update office
#   DELETE /admin/police-offices/{id}/     => delete office
router.register(r'admin/police-offices', PoliceOfficeAdminViewSet, basename='police-office')

# Register the Report ViewSet for crime report CRUD operations
# This generates: /reports/, /reports/{id}/, /reports/{id}/route/, etc.
router.register(r'reports', ReportViewSet, basename='report') 

# Register the Checkpoint ViewSet for patrol checkpoint management
# This generates: /checkpoints/, /checkpoints/{id}/, /checkpoints/active/, etc.
router.register(r'checkpoints', CheckpointViewSet, basename='checkpoint') 

# Register the Media ViewSet for file upload/retrieval
# This generates: /media/, /media/{id}/, etc.
router.register(r'media', MediaViewSet, basename='media')

# ============================================================================
# NESTED ROUTER: Messages as sub-resources of Reports
# Messages are "nested" under reports (/reports/{report_id}/messages/)
# Because messages always belong to a specific report
# ============================================================================

# Create a nested router that depends on the main "reports" router
# This allows nesting: /reports/{report_pk}/messages/
reports_router = routers.NestedSimpleRouter(router, r'reports', lookup='report')

# Register the Message ViewSet under reports
# This generates:
#   GET    /reports/{report_pk}/messages/          => list all messages for a report
#   POST   /reports/{report_pk}/messages/          => create new message
#   GET    /reports/{report_pk}/messages/{id}/     => get specific message
#   PUT    /reports/{report_pk}/messages/{id}/     => update message
reports_router.register(r'messages', MessageViewSet, basename='report-messages')

# ============================================================================
# URL PATTERNS: List of all endpoint routes
# When a request comes in, Django searches through these patterns top-to-bottom
# and uses the first match to route to the appropriate view
# ============================================================================

urlpatterns = [
    # =====================================================
    # AUTHENTICATION
    # =====================================================
    # POST /auth/login/ => LoginAPIView (handles admin & police login)
    path('auth/login/', LoginAPIView.as_view(), name='login'),

    # =====================================================
    # ADMIN MAP & MANAGEMENT
    # =====================================================
    # GET /admin/map/data/ => AdminMapAPIView (returns active reports + offices + checkpoints)
    path('admin/map/data/', AdminMapAPIView.as_view(), name='admin-map-data'),
    
    # POST /admin/analytics/update/ => AnalyticsUpdateAPIView (recalculate statistics cache)
    path('admin/analytics/update/', AnalyticsUpdateAPIView.as_view(), name='analytics-update'),

    # =====================================================
    # ANALYTICS ENDPOINTS (Dashboard Statistics)
    # =====================================================
    # GET /analytics/summary/overview/ => AnalyticsOverviewSummaryAPIView (total + avg resolution)
    path('analytics/summary/overview/', AnalyticsOverviewSummaryAPIView.as_view()),

    # GET /analytics/hotspots/locations/ => LocationHotspotsAPIView (top 3 locations with crime)
    path('analytics/hotspots/locations/', LocationHotspotsAPIView.as_view()),

    # GET /analytics/hotspots/categories/ => CategoryConcentrationAPIView (top 2 crime types)
    path('analytics/hotspots/categories/', CategoryConcentrationAPIView.as_view()),

    # GET /analytics/export/ => AnalyticsExportAPIView (PDF with all analytics data)
    path('analytics/export/', AnalyticsExportAPIView.as_view()),

    # GET /reports/summary/top-locations/ => TopLocationsAPIView (legacy endpoint)
    path('reports/summary/top-locations/', TopLocationsAPIView.as_view(), name='top-locations'),

    # =====================================================
    # RESOLVED CASES ENDPOINTS (Case Files)
    # =====================================================
    # GET /reports/resolved/ => ResolvedCasesAPIView (JSON list of resolved cases)
    path('reports/resolved/', ResolvedCasesAPIView.as_view()),

    # GET /reports/resolved/export/ => ResolvedCasesExportAPIView (PDF table of resolved cases)
    path('reports/resolved/export/', ResolvedCasesExportAPIView.as_view()),
    
    # GET /reports/{report_id}/export/ => SingleReportExportAPIView (PDF case file for one report)
    # UUID format: e.g., /reports/a1b2c3d4-e5f6-7890-1234-567890abcdef/export/
    path('reports/<uuid:report_id>/export/', SingleReportExportAPIView.as_view()),

    # =====================================================
    # AUTO-GENERATED ROUTER URLS (ViewSet Endpoints)
    # =====================================================
    # Include all ViewSet URL patterns generated by the router
    # Includes /reports/, /admin/police-offices/, /checkpoints/, /media/
    path('', include(router.urls)),
    
    # Include nested router URLs for /reports/{id}/messages/
    path('', include(reports_router.urls)),
]