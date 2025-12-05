from django.http import HttpResponse
from django.utils import timezone
from django.db.models import F, DurationField, ExpressionWrapper, Avg
from rest_framework.views import APIView
from rest_framework.response import Response

from ..models import Report, PoliceOffice
from ..services import (
    parse_filters,
    apply_common_filters,
    build_top_locations,
    build_category_concentration,
    compute_avg_resolution,
    render_pdf,
    build_analytics_filename,
)


class AnalyticsOverviewSummaryAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.all(), f)

        total_assigned = base.count()
        resolved = base.filter(status='Resolved', updated_at__isnull=False)
        avg_res_str = compute_avg_resolution(resolved)

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "total_assigned": total_assigned,
            "average_resolution_time": avg_res_str,
        }, status=200)


class LocationHotspotsAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        ctx = build_top_locations(f)
        return Response(ctx, status=200)


class CategoryConcentrationAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        ctx = build_category_concentration(f)
        return Response(ctx, status=200)


class AnalyticsExportAPIView(APIView):
    """Exports Overview + Location Hotspots + Category Concentration in one PDF."""

    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.all(), f)
        total_assigned = base.count()
        resolved = base.filter(status='Resolved', updated_at__isnull=False)
        avg_res_str = compute_avg_resolution(resolved)

        loc_ctx = build_top_locations(f)
        cat_ctx = build_category_concentration(f)

        all_reports_total = Report.objects.count()
        total_reports_percent = (total_assigned / all_reports_total * 100.0) if all_reports_total else 0.0

        office_name = 'All Offices'
        head_officer_name = 'N/A'
        if f['office_id']:
            try:
                office = PoliceOffice.objects.get(office_id=f['office_id'])
                office_name = office.office_name
                head_officer_name = office.head_officer or 'N/A'
            except PoliceOffice.DoesNotExist:
                pass

        context = {
            'category_filter_name': f['category'] or 'All Categories',
            'audit_scope': 'Our Office' if f['scope'] == 'our_office' else 'All Offices',
            'timeframe_days': f['days'],
            'total_reports': loc_ctx['total_resolved'],
            'total_reports_percent': total_reports_percent,
            'top_locations_list': [
                {
                    'location_city': i.get('location_city'),
                    'location_barangay': i.get('location_barangay'),
                    'report_count': i['report_count'],
                    'report_percent': i['report_percent'],
                }
                for i in loc_ctx['results']
            ],
            'category_is_specific': bool(f['category']),
            'category_results': cat_ctx['results'],
            'category_total': cat_ctx['total_resolved'],
            'avg_resolution_time': avg_res_str,
            'office_name': office_name,
            'head_officer_name': head_officer_name,
            'current_datetime': timezone.now(),
        }

        pdf = render_pdf('report_crime_deep_dive.html', context, request.build_absolute_uri('/'))
        filename = build_analytics_filename(f)

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
