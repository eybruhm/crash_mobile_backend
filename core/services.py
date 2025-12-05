# core/services.py
import requests, os, qrcode, base64
from io import BytesIO
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, Avg, F, DurationField, ExpressionWrapper
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from .models import Report, PoliceOffice

# Load the API Key from settings
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

def generate_directions_and_qr(start_lat, start_lng, end_lat, end_lng):
    """
    Generates Google Maps URL, calls API (optional), and creates Base64 QR code.
    """
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError("Google Maps API key is not configured.")

    # 1. Construct the Google Maps Directions URL
    # We use a universal link structure for direct use in mobile browsers via QR code.
    # Format: https://www.google.com/maps/dir/Start_LAT,Start_LNG/End_LAT,End_LNG
    maps_url = (
        f"https://www.google.com/maps/dir/{start_lat},{start_lng}/{end_lat},{end_lng}"
    )

    # 2. OPTIONAL: Call Google Directions API for ETA/Distance (requires API Key)
    # Note: This consumes an API credit. We focus on the URL for the QR code.
    # You can add the ETA/Distance logic here later.

    # 3. Generate QR Code Image (in memory)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(maps_url)
    qr.make(fit=True)

    # Create the image using Pillow
    img = qr.make_image(fill_color="black", back_color="white")

    # Save the image data into a buffer (BytesIO)
    buffer = BytesIO()
    img.save(buffer, format="PNG")

    # 4. Convert to Base64
    base64_encoded_data = base64.b64encode(buffer.getvalue()).decode()

    # Prepend the required Data URL header for HTML <img> tags
    qr_data_url = f"data:image/png;base64,{base64_encoded_data}"

    return {
        'directions_url': maps_url,
        'qr_code_base64': qr_data_url,
        # 'distance': 'X km', # Placeholder for optional API call result
        # 'duration': 'Y mins', # Placeholder for optional API call result
    }


def reverse_geocode(latitude, longitude):
    """Calls Google Maps Geocoding API to find city/barangay from coordinates."""
    api_key = GOOGLE_MAPS_API_KEY
    if not api_key:
        return None, None # Cannot geocode without key

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        'latlng': f'{latitude},{longitude}',
        'key': api_key
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # TEMPORARY DEBUG: Print the full response
        print("=== Google Geocode Response ===")
        print(f"Status: {data.get('status')}")
        if data.get('results'):
            print(f"Number of results: {len(data['results'])}")
            for idx, result in enumerate(data['results'][:2]):  # Print first 2
                print(f"\nResult {idx}:")
                for comp in result['address_components']:
                    print(f"  {comp['long_name']} - Types: {comp['types']}")
        print("=" * 40)

        city = None
        barangay = None

        # Logic to parse the Google Maps JSON result
        if data['results']:
            # Iterate through ALL results first to collect both values
            for result in data['results']:
                for component in result['address_components']:
                    types = component['types']
                    
                    # Check for City (locality or administrative_area_level_2)
                    if not city and ('locality' in types or 'administrative_area_level_2' in types):
                        city = component['long_name']
                    
                    # Check for Barangay (sublocality_level_1 or neighborhood)
                    if not barangay and ('sublocality_level_1' in types or 'neighborhood' in types):
                        barangay = component['long_name']
                
                # If we found both, exit early
                if city and barangay:
                    break
            
            # Return whatever we found (may be None if not present)
            return city, barangay

    except Exception as e:
        # For debugging: you can print the error temporarily
        print(f"Geocoding error: {e}")
        return None, None

    return None, None

def get_active_checkpoints_list(all_checkpoints_qs):
    """Filters checkpoint queryset using Python logic for time comparison."""
    current_time = datetime.now().time()
    active_list = []

    for checkpoint in all_checkpoints_qs:
        start = checkpoint.time_start
        end = checkpoint.time_end

        if start is None or end is None:
            continue

        # Case 1: Normal shift (start < end)
        if start < end:
            if start <= current_time < end:
                active_list.append(checkpoint)

        # Case 2: Overnight shift (start > end, e.g., 20:00 to 02:00)
        else:
            # Active if NOW is after start (before midnight) OR NOW is before end (after midnight)
            if current_time >= start or current_time < end:
                active_list.append(checkpoint)

    return active_list


# ---------- Shared analytics helpers ----------

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
    qs = qs.filter(created_at__gte=f['since'])

    if f['scope'] == 'our_office' and f['office_id']:
        qs = qs.filter(assigned_office_id=f['office_id'])

    if f['city']:
        qs = qs.filter(location_city__iexact=f['city'])
        if f['barangay']:
            qs = qs.filter(location_barangay__iexact=f['barangay'])

    if f['category']:
        qs = qs.filter(category__iexact=f['category'])

    return qs


def format_duration(delta):
    if not delta:
        return "N/A"
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    rem = total_seconds % 86400
    h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60
    return (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"


def compute_avg_resolution(qs):
    resolution_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
    avg_res = qs.annotate(res_time=resolution_delta).aggregate(avg=Avg('res_time'))['avg']
    return format_duration(avg_res)


def build_top_locations(f):
    base = apply_common_filters(Report.objects.filter(status='Resolved'), f)
    total = base.count()

    if not f['city']:
        qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
        items = list(qs)
    elif f['city'] and not f['barangay']:
        qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
        items = list(qs)
    else:
        count = base.count()
        items = [{
            'location_city': f['city'],
            'location_barangay': f['barangay'],
            'report_count': count
        }]

    for i in items:
        i['report_percent'] = (i['report_count'] / total * 100.0) if total else 0.0

    return {
        'filters': {k: (str(v) if v is not None else None) for k, v in f.items()},
        'total_resolved': total,
        'results': items,
    }


def build_category_concentration(f):
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

    return {
        'filters': {k: (str(v) if v is not None else None) for k, v in f.items()},
        'total_resolved': total,
        'results': results,
    }


def render_pdf(template_name, context, base_url):
    html = render_to_string(template_name, context)
    return HTML(string=html, base_url=base_url).write_pdf()


def short_uuid(uuid_str, start=5, end=5):
    if not uuid_str:
        return ""
    return f"{uuid_str[:start]}...{uuid_str[-end:]}"


def build_analytics_filename(f):
    parts = [f"analytics_{f['days']}days"]
    parts.append('our_office' if f['scope'] == 'our_office' else 'all_offices')
    if f['category']:
        parts.append(f['category'].replace(' ', '_').lower())
    if f['city']:
        parts.append(f['city'].replace(' ', '_').lower())
    return '_'.join(parts) + '.pdf'


def build_resolved_filename(f):
    parts = [f"resolved_cases_{f['days']}days"]
    parts.append('our_office' if f['scope'] == 'our_office' else 'all_offices')
    if f['category']:
        parts.append(f['category'].replace(' ', '_').lower())
    if f['city']:
        parts.append(f['city'].replace(' ', '_').lower())
    return '_'.join(parts) + '.pdf'