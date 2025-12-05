# ============================================================================
# REPORTS VIEWS: Resolved cases listing and PDF export endpoints
# Used to view and export resolved crime cases (case files and reports)
# Each view handles data for "Resolved Cases" page (different from analytics)
# ============================================================================

from django.http import HttpResponse
from django.utils import timezone
from django.db.models import DurationField, ExpressionWrapper, F
from rest_framework.views import APIView
from rest_framework.response import Response

from ..models import Report, PoliceOffice
from ..services import (
    parse_filters,
    apply_common_filters,
    format_duration,
    render_pdf,
    build_resolved_filename,
    short_uuid,
)


# ============================================================================
# RESOLVED CASES LIST VIEW (JSON)
# ============================================================================

class ResolvedCasesAPIView(APIView):
    # ENDPOINT: GET /reports/resolved/
    # Used when: Frontend loads the Resolved Cases page (list view)
    # Input: Filter query params (days, scope, office_id, city, barangay, category)
    # Output: Table of resolved cases with: ID, category, dates, location, resolution time
    # Note: Returns JSON (not PDF), frontend can render as table

    def get(self, request):
        # Parse all filter parameters from the request
        f = parse_filters(request)
        
        # Apply filters and get only resolved reports (status='Resolved')
        # Start with resolved + has completion date, apply all filters
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')
        
        # Calculate resolution time for each report (updated_at - created_at)
        # This is a database calculation, not Python
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)
        
        # Convert to JSON-ready format
        data = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            # Convert duration (timedelta) to readable format "2d 3h 45m"
            r['resolution_time_str'] = format_duration(r['resolution_time'])
            data.append(r)

        # Return the data as JSON with metadata
        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "count": len(data),
            "results": data,
        }, status=200)


# ============================================================================
# RESOLVED CASES EXPORT TO PDF VIEW
# ============================================================================

class ResolvedCasesExportAPIView(APIView):
    # ENDPOINT: GET /reports/resolved/export/ (PDF download)
    # Used when: User exports the resolved cases list to PDF
    # Output: Table PDF containing all resolved cases matching filters
    # PDF displays in browser (inline) instead of forcing download
    # Uses template: report_resolved_cases_list.html

    def get(self, request):
        # Parse all filter parameters from the request
        f = parse_filters(request)
        
        # Apply filters and get only resolved reports, newest first
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')
        
        # Calculate resolution time for each report
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)

        # Convert to PDF-friendly format
        rows = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            # Convert duration to readable format "2d 3h 45m"
            r['resolution_time_str'] = format_duration(r['resolution_time'])
            # Shorten UUID from full to "AAAAA...ZZZZZ" for table display
            r['report_id_short'] = short_uuid(str(r['report_id']))
            rows.append(r)

        # Get office information for PDF footer (who created the report)
        office_name = 'All Offices'
        head_officer_name = 'N/A'
        if f['office_id']:
            try:
                # Fetch office details from database
                office = PoliceOffice.objects.get(office_id=f['office_id'])
                office_name = office.office_name
                head_officer_name = office.head_officer or 'N/A'
            except PoliceOffice.DoesNotExist:
                pass

        # Build context (data) to pass to the PDF template
        context = {
            'timeframe_days': f['days'],
            'audit_scope': 'Our Office' if f['scope']=='our_office' else 'All Offices',
            'city': f['city'],
            'barangay': f['barangay'],
            'category': f['category'],
            'rows': rows,  # The table data
            'office_name': office_name,
            'head_officer_name': head_officer_name,
            'current_datetime': timezone.now(),
        }

        # Render the HTML template with the data, convert to PDF
        pdf = render_pdf('report_resolved_cases_list.html', context, request.build_absolute_uri('/'))
        
        # Generate a descriptive filename for the PDF
        filename = build_resolved_filename(f)
        
        # Create HTTP response with the PDF
        response = HttpResponse(pdf, content_type='application/pdf')
        # 'inline' = show in browser, not 'attachment' which forces download
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response


# ============================================================================
# SINGLE REPORT EXPORT TO PDF VIEW (Case File)
# ============================================================================

class SingleReportExportAPIView(APIView):
    # ENDPOINT: GET /reports/{report_id}/export/ (PDF download)
    # Used when: User exports a single resolved case to PDF (detailed case file)
    # Input: report_id (UUID in URL)
    # Output: Detailed case file PDF with full report information
    # PDF displays in browser (inline) instead of forcing download
    # Uses template: report_resolved_cases_audit.html

    def get(self, request, report_id):
        try:
            # Find the specific report in database (must be resolved status)
            # select_related = fetch reporter and office data efficiently
            report = Report.objects.select_related('reporter', 'assigned_office').get(report_id=report_id, status='Resolved')
        except Report.DoesNotExist:
            # Report not found or not resolved yet
            return HttpResponse("Report not found or not resolved.", status=404)

        # Calculate resolution time (time from submission to resolution)
        if report.updated_at and report.created_at:
            # Duration = completion time - submission time
            delta = report.updated_at - report.created_at
        else:
            # If either timestamp is missing, can't calculate
            delta = None
        # Convert duration to readable format "2d 3h 45m"
        calculated_resolution_time = format_duration(delta)

        # Get shortened office ID for display (first 7 and last 7 chars)
        # Example: "a1b2c3d4e5f6-1234-5678" becomes "a1b2c3d...5678"
        office_id_str = str(report.assigned_office.office_id) if report.assigned_office else ''
        office_id_short = short_uuid(office_id_str, start=7, end=7)

        # Build context (data) to pass to the PDF template
        context = {
            'report': report,  # The full report object (all fields)
            'reporter': report.reporter,  # The citizen who reported
            'assigned_office': report.assigned_office,  # The police office handling it
            'office_id_short': office_id_short,  # Shortened office ID for display
            'calculated_resolution_time': calculated_resolution_time,  # "2d 3h 45m"
            'current_datetime': timezone.now(),  # When the report was exported
            'office_id_str': office_id_str,  # Full office ID (for backend use)
        }

        # Render the HTML template with the data, convert to PDF
        pdf = render_pdf('report_resolved_cases_audit.html', context, request.build_absolute_uri('/'))
        
        # Create HTTP response with the PDF
        response = HttpResponse(pdf, content_type='application/pdf')
        # 'inline' = show in browser, not 'attachment' which forces download
        response['Content-Disposition'] = f'inline; filename="case_file_{report.report_id}.pdf"'
        return response
