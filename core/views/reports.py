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


class ResolvedCasesAPIView(APIView):
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)
        data = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            r['resolution_time_str'] = format_duration(r['resolution_time'])
            data.append(r)

        return Response({
            "filters": {k: (str(v) if v is not None else None) for k, v in f.items()},
            "count": len(data),
            "results": data,
        }, status=200)


class ResolvedCasesExportAPIView(APIView):
    """Exports a LIST of resolved cases (table format) with filters applied."""
    def get(self, request):
        f = parse_filters(request)
        base = apply_common_filters(Report.objects.filter(status='Resolved', updated_at__isnull=False), f).order_by('-updated_at')
        res_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
        qs = base.annotate(resolution_time=res_delta)

        rows = []
        for r in qs.values('report_id','category','created_at','updated_at','location_city','location_barangay','remarks','resolution_time'):
            r['resolution_time_str'] = format_duration(r['resolution_time'])
            r['report_id_short'] = short_uuid(str(r['report_id']))
            rows.append(r)

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
            'timeframe_days': f['days'],
            'audit_scope': 'Our Office' if f['scope']=='our_office' else 'All Offices',
            'city': f['city'],
            'barangay': f['barangay'],
            'category': f['category'],
            'rows': rows,
            'office_name': office_name,
            'head_officer_name': head_officer_name,
            'current_datetime': timezone.now(),
        }

        pdf = render_pdf('report_resolved_cases_list.html', context, request.build_absolute_uri('/'))
        filename = build_resolved_filename(f)
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response


class SingleReportExportAPIView(APIView):
    """Exports a SINGLE report's detailed case file."""
    def get(self, request, report_id):
        try:
            report = Report.objects.select_related('reporter', 'assigned_office').get(report_id=report_id, status='Resolved')
        except Report.DoesNotExist:
            return HttpResponse("Report not found or not resolved.", status=404)

        if report.updated_at and report.created_at:
            delta = report.updated_at - report.created_at
        else:
            delta = None
        calculated_resolution_time = format_duration(delta)

        office_id_str = str(report.assigned_office.office_id) if report.assigned_office else ''
        office_id_short = short_uuid(office_id_str, start=7, end=7)

        context = {
            'report': report,
            'reporter': report.reporter,
            'assigned_office': report.assigned_office,
            'office_id_short': office_id_short,
            'calculated_resolution_time': calculated_resolution_time,
            'current_datetime': timezone.now(),
            'office_id_str': office_id_str,
        }

        pdf = render_pdf('report_resolved_cases_audit.html', context, request.build_absolute_uri('/'))
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="case_file_{report.report_id}.pdf"'
        return response
