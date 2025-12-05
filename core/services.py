# ============================================================================
# SERVICES: Reusable helper functions used by views
# Think of services as a "utility toolbox" - functions that many views need
# Instead of duplicating code in each view, we write it once here and reuse it
# Examples: PDF rendering, geocoding, filtering, time calculations
# ============================================================================

import requests, os, qrcode, base64
from io import BytesIO
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, Avg, F, DurationField, ExpressionWrapper
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from .models import Report, PoliceOffice

# Load the API Key from settings (stored in environment variables for security)
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

# ============================================================================
# GEOLOCATION & NAVIGATION: Google Maps Integration
# ============================================================================

def generate_directions_and_qr(start_lat, start_lng, end_lat, end_lng):
    # FUNCTION: Generate navigation link + QR code for police officer
    # Input: Starting location (lat/lng), ending location (lat/lng)
    # Output: Dict with Google Maps URL and QR code image (Base64)
    # Used by: Views that handle report routing/navigation
    # Example: Police officer scans QR → opens Google Maps directions automatically
    
    # Validate: Google Maps API key must be configured
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError("Google Maps API key is not configured.")

    # Step 1: Construct the Google Maps Directions URL
    # This link opens Google Maps with turn-by-turn directions
    # Format: https://www.google.com/maps/dir/START_LAT,START_LNG/END_LAT,END_LNG
    # This can be embedded in a QR code for easy mobile access
    maps_url = (
        f"https://www.google.com/maps/dir/{start_lat},{start_lng}/{end_lat},{end_lng}"
    )

    # Step 2: OPTIONAL - Call Google Directions API for ETA/Distance
    # NOTE: This would consume an API quota credit per request
    # Currently skipped; we just use the URL in the QR code
    # TODO: Add ETA calculation if budget allows

    # Step 3: Generate QR Code (in memory)
    # QR Code = 2D barcode that encodes the Google Maps URL
    # When scanned with a phone, it opens the directions link
    qr = qrcode.QRCode(
        version=1,  # Size of QR code (1 = smallest)
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # Error correction level
        box_size=10,  # Pixel size of each "square" in the QR code
        border=4,  # White space border around edges
    )
    qr.add_data(maps_url)  # Encode the Google Maps URL
    qr.make(fit=True)  # Generate the QR code pattern

    # Create the QR code image using Pillow library
    img = qr.make_image(fill_color="black", back_color="white")

    # Step 4: Save image to memory (BytesIO is like a temporary file in RAM)
    buffer = BytesIO()
    img.save(buffer, format="PNG")  # Save as PNG image format

    # Step 5: Convert to Base64 (text-based image encoding)
    # Why? Because JSON responses can't contain binary image data
    # Base64 = text representation that browsers can display directly
    base64_encoded_data = base64.b64encode(buffer.getvalue()).decode()

    # Step 6: Create Data URL (special format for embedding images in HTML)
    # Data URL = "data:image/png;base64,ENCODED_DATA"
    # Can be used directly in <img src="..."> tags
    qr_data_url = f"data:image/png;base64,{base64_encoded_data}"

    # Return all data needed for the frontend
    return {
        'directions_url': maps_url,  # Direct link to Google Maps
        'qr_code_base64': qr_data_url,  # QR code as an image
        # 'distance': 'X km', # TODO: Add distance from API call
        # 'duration': 'Y mins', # TODO: Add ETA from API call
    }



def reverse_geocode(latitude, longitude):
    # FUNCTION: Convert GPS coordinates to human-readable location (city/barangay)
    # Input: latitude, longitude (from GPS)
    # Output: (city_name, barangay_name) or (None, None) if API fails
    # Used by: Report creation (when citizen submits with GPS)
    # Example: (14.5995, 120.9842) → ("Manila", "Tondo")
    
    # Validate: Google Maps API key must be configured
    api_key = GOOGLE_MAPS_API_KEY
    if not api_key:
        # Can't call API without credentials
        return None, None

    # Step 1: Prepare API request to Google Geocoding service
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        'latlng': f'{latitude},{longitude}',  # "14.5995,120.9842"
        'key': api_key  # Authentication token
    }

    try:
        # Step 2: Call the Google Maps Geocoding API
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()  # Raise error if HTTP status is not 200
        data = response.json()  # Parse JSON response
        
        # DEBUG: Print response for troubleshooting
        print("=== Google Geocode Response ===")
        print(f"Status: {data.get('status')}")
        if data.get('results'):
            print(f"Number of results: {len(data['results'])}")
            for idx, result in enumerate(data['results'][:2]):  # Print first 2
                print(f"\nResult {idx}:")
                for comp in result['address_components']:
                    print(f"  {comp['long_name']} - Types: {comp['types']}")
        print("=" * 40)

        # Step 3: Parse the API response to extract city and barangay
        city = None
        barangay = None

        # Google returns multiple address levels (country > province > city > barangay)
        # We iterate through results to find city and barangay components
        if data['results']:
            # Loop through all results from most specific to least specific
            for result in data['results']:
                # Each result has address_components (e.g., "Tondo", "Manila", "Philippines")
                for component in result['address_components']:
                    types = component['types']  # Tag for what this component is
                    
                    # Look for city (labeled as 'locality' or 'administrative_area_level_2')
                    # Philippines naming: 'locality' = city
                    if not city and ('locality' in types or 'administrative_area_level_2' in types):
                        city = component['long_name']
                    
                    # Look for barangay (labeled as 'sublocality_level_1' or 'neighborhood')
                    # Philippines naming: 'sublocality_level_1' = barangay (administrative division)
                    if not barangay and ('sublocality_level_1' in types or 'neighborhood' in types):
                        barangay = component['long_name']
                
                # If we found both values, we can stop searching
                if city and barangay:
                    break
            
            # Step 4: Return whatever we found (may be None if not present in results)
            return city, barangay

    except Exception as e:
        # API call failed (timeout, network error, API error, etc.)
        # Log the error for debugging, but don't crash the app
        print(f"Geocoding error: {e}")
        return None, None

    # Fallback: API didn't return results
    return None, None


def get_active_checkpoints_list(all_checkpoints_qs):
    # FUNCTION: Filter checkpoints to show only those currently active
    # Input: QuerySet of all checkpoints from database
    # Output: Python list of checkpoint objects that are active RIGHT NOW
    # Used by: Views that show current/active checkpoints on map
    # Logic: Compares current time to checkpoint's time_start and time_end
    
    # Get the current time (hour:minute:second)
    current_time = datetime.now().time()
    active_list = []

    # Check each checkpoint to see if it's currently active
    for checkpoint in all_checkpoints_qs:
        start = checkpoint.time_start
        end = checkpoint.time_end

        # Skip checkpoints without proper time settings
        if start is None or end is None:
            continue

        # CASE 1: Normal shift (e.g., 6:00 AM to 2:00 PM)
        # start < end means the shift is within the same day
        if start < end:
            # Active if current time is between start and end
            # Example: start=06:00, current=09:00, end=14:00 → ACTIVE
            if start <= current_time < end:
                active_list.append(checkpoint)

        # CASE 2: Overnight shift (e.g., 8:00 PM to 4:00 AM next day)
        # start > end means the shift crosses midnight
        else:
            # Active if: NOW is after start (before midnight) OR NOW is before end (after midnight)
            # Example: start=20:00, current=22:00, end=04:00 → ACTIVE (after 20:00)
            # Example: start=20:00, current=02:00, end=04:00 → ACTIVE (before 04:00)
            # Example: start=20:00, current=12:00, end=04:00 → NOT ACTIVE (middle of day)
            if current_time >= start or current_time < end:
                active_list.append(checkpoint)

    return active_list



# ============================================================================
# ANALYTICS HELPERS: Data aggregation and filtering utilities
# Used by analytics endpoints to calculate crime statistics
# These functions handle: filtering, grouping, calculating percentages
# ============================================================================

def parse_filters(request):
    # FUNCTION: Extract and validate filter parameters from request
    # Input: HTTP request object with query parameters
    # Output: Dict with normalized filter values (days, scope, office_id, city, barangay, category)
    # Used by: All analytics endpoints to apply consistent filtering
    
    # Extract query parameters from URL (?days=30&scope=all&category=Robbery)
    # Provide default values if not specified
    days = int(request.query_params.get('days', 30))  # Default: last 30 days
    scope = (request.query_params.get('scope') or 'all').lower()  # Default: all offices
    office_id = request.query_params.get('office_id')  # Office filter (UUID)
    city = request.query_params.get('city')  # City filter
    barangay = request.query_params.get('barangay')  # Barangay filter
    category = request.query_params.get('category')  # Crime category filter

    # Normalize category: treat 'all' as None (means show all categories)
    if category and category.lower() == 'all':
        category = None

    # Calculate the start date for the time range filter
    # Example: days=30 → since = today - 30 days
    since = timezone.now() - timedelta(days=days)
    
    # Return a dict with all filters organized
    return {
        'days': days,  # Number of days to look back
        'since': since,  # Actual datetime cutoff
        'scope': scope,  # 'all' or 'our_office'
        'office_id': office_id,  # Specific office UUID or None
        'city': city,  # Specific city or None
        'barangay': barangay,  # Specific barangay or None
        'category': category,  # Specific crime type or None
    }



def apply_common_filters(qs, f):
    # FUNCTION: Apply all parsed filters to a queryset
    # Input: Django QuerySet, filter dict from parse_filters()
    # Output: Filtered QuerySet with only matching reports
    # Used by: All analytics views to apply consistent filtering logic
    # Example: start with all reports → filter by date → filter by scope → filter by location
    
    # FILTER 1: Date range (reports created since the cutoff date)
    # Example: only show reports from the last 30 days
    qs = qs.filter(created_at__gte=f['since'])

    # FILTER 2: Scope (all offices vs specific office)
    # scope='our_office' means: only show reports assigned to a specific office
    # scope='all' means: show reports from all offices
    if f['scope'] == 'our_office' and f['office_id']:
        qs = qs.filter(assigned_office_id=f['office_id'])

    # FILTER 3: Location (city and optionally barangay)
    # Case-insensitive matching ("manila" matches "Manila")
    if f['city']:
        qs = qs.filter(location_city__iexact=f['city'])
        # If barangay is also specified, add that filter too
        if f['barangay']:
            qs = qs.filter(location_barangay__iexact=f['barangay'])

    # FILTER 4: Crime category
    # Example: show only "Robbery" reports, case-insensitive
    if f['category']:
        qs = qs.filter(category__iexact=f['category'])

    # Return the filtered queryset
    # Can be used directly or filtered further by the calling view
    return qs



def format_duration(delta):
    # FUNCTION: Convert timedelta to human-readable format
    # Input: timedelta object (difference between two times)
    # Output: Formatted string like "2d 03:45:30" or "N/A"
    # Used by: Report views to display resolution time in readable format
    # Example: timedelta(days=2, seconds=13530) → "2d 03:45:30"
    
    # Handle missing data (None means time wasn't calculated)
    if not delta:
        return "N/A"
    
    # Convert timedelta to total seconds (easier to do math with)
    total_seconds = int(delta.total_seconds())
    
    # Calculate days, hours, minutes, seconds from total seconds
    days = total_seconds // 86400  # 86400 seconds in a day
    rem = total_seconds % 86400  # Remaining seconds after extracting days
    h, m, s = rem // 3600, (rem % 3600) // 60, rem % 60  # Extract h:m:s
    
    # Format as string: "2d 03:45:30" (only show days if > 0)
    return (f"{days}d " if days else "") + f"{h:02d}:{m:02d}:{s:02d}"



def compute_avg_resolution(qs):
    # FUNCTION: Calculate average time from report submission to resolution
    # Input: QuerySet of resolved reports (must have updated_at and created_at)
    # Output: Formatted string like "2d 03:45:30" or "N/A"
    # Used by: Analytics views to show average resolution time in dashboard
    # Example: 100 reports, avg resolution time = 2 days 3 hours 45 minutes
    
    # Use Django's database annotation to calculate resolution time for each report
    # ExpressionWrapper = run calculation in the database (efficient!)
    # F('updated_at') - F('created_at') = time difference
    resolution_delta = ExpressionWrapper(F('updated_at') - F('created_at'), output_field=DurationField())
    
    # Annotate each report with its resolution time, then aggregate the average
    # aggregate(avg=Avg('res_time')) = calculate the average of all resolution times
    avg_res = qs.annotate(res_time=resolution_delta).aggregate(avg=Avg('res_time'))['avg']
    
    # Convert the average duration to a readable format
    # format_duration handles None gracefully if no reports exist
    return format_duration(avg_res)



def build_top_locations(f):
    # FUNCTION: Find top 3-5 locations with highest crime counts
    # Input: Filter dict from parse_filters()
    # Output: Dict with {results: [...locations...], total_resolved: count}
    # Used by: Analytics views to show "where do crimes happen most?"
    # Example: {Manila/Tondo: 50 reports (30%), Manila/Intramuros: 35 reports (21%), ...}
    
    # Apply all filters to get matching resolved reports
    base = apply_common_filters(Report.objects.filter(status='Resolved'), f)
    total = base.count()  # Total number of matching reports

    # Branch 1: If NO city is specified, group by city/barangay (show top locations)
    if not f['city']:
        # Group reports by location, count how many in each location
        # Example: {Manila/Tondo: 50, Manila/Intramuros: 35, ...}
        qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
        items = list(qs)
    
    # Branch 2: If city is specified but NO barangay, still group by location
    # (but results will be filtered to that city only)
    elif f['city'] and not f['barangay']:
        qs = base.values('location_city', 'location_barangay').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
        items = list(qs)
    
    # Branch 3: If both city AND barangay are specified, show that specific location
    # (no grouping needed, all reports are already from that location)
    else:
        count = base.count()
        items = [{
            'location_city': f['city'],
            'location_barangay': f['barangay'],
            'report_count': count
        }]

    # Calculate percentage for each location
    # Example: 50 out of 100 reports = 50%
    for i in items:
        i['report_percent'] = (i['report_count'] / total * 100.0) if total else 0.0

    # Return the data structure that views expect
    return {
        'filters': {k: (str(v) if v is not None else None) for k, v in f.items()},
        'total_resolved': total,  # Total number of matching reports
        'results': items,  # List of locations with counts and percentages
    }



def build_category_concentration(f):
    # FUNCTION: Find top 2-5 crime categories with highest counts
    # Input: Filter dict from parse_filters()
    # Output: Dict with {results: [...categories...], total_resolved: count}
    # Used by: Analytics views to show "which crimes are most common?"
    # Example: {Robbery: 85 reports (50%), Theft: 60 reports (35%), ...}
    
    # Apply all filters to get matching resolved reports
    base = apply_common_filters(Report.objects.filter(status='Resolved'), f)
    total = base.count()  # Total number of matching reports

    # Branch 1: If NO specific category is specified, group by category (show top ones)
    if not f['category']:
        # Group reports by crime type, count how many in each category
        # Example: {Robbery: 85, Theft: 60, ...}
        qs = base.values('category').annotate(report_count=Count('report_id')).order_by('-report_count')[:5]
        results = []
        for row in qs:
            pct = (row['report_count'] / total * 100.0) if total else 0.0
            results.append({
                'category': row['category'],
                'report_count': row['report_count'],
                'percentage': pct
            })
    
    # Branch 2: If a specific category is specified, show just that category
    # (no grouping needed, all reports are already of that type)
    else:
        count = base.count()
        pct = (count / total * 100.0) if total else 0.0
        results = [{
            'category': f['category'],
            'report_count': count,
            'percentage': pct
        }]

    # Return the data structure that views expect
    return {
        'filters': {k: (str(v) if v is not None else None) for k, v in f.items()},
        'total_resolved': total,  # Total number of matching reports
        'results': results,  # List of categories with counts and percentages
    }



# ============================================================================
# PDF & UTILITY HELPERS: Document generation and formatting
# Used by views to generate PDFs and format data for display
# ============================================================================

def render_pdf(template_name, context, base_url):
    # FUNCTION: Convert Django HTML template to PDF file
    # Input: template_name (e.g., "report_crime_deep_dive.html"), context data, base URL
    # Output: Binary PDF data (bytes) ready to send to browser
    # Used by: All export views to generate downloadable/viewable PDFs
    # How it works: Render template to HTML → convert HTML to PDF using WeasyPrint
    
    # Step 1: Render the Django template with the context data
    # This converts a .html template + Python dict → HTML string
    html = render_to_string(template_name, context)
    
    # Step 2: Convert HTML to PDF using WeasyPrint library
    # HTML() parses the HTML, write_pdf() generates PDF bytes
    # base_url is needed for resolving CSS/image paths in the template
    return HTML(string=html, base_url=base_url).write_pdf()



def short_uuid(uuid_str, start=5, end=5):
    # FUNCTION: Abbreviate UUID for display in tables/PDFs
    # Input: UUID string (e.g., "a1b2c3d4-e5f6-7890-1234-567890abcdef")
    # Output: Shortened version (e.g., "a1b2c...90abc" using default start=5, end=5)
    # Used by: PDF templates to show UUIDs in a readable table format
    # Why? Full UUID is long; abbreviating helps fit in narrow columns
    
    # Handle empty/None input
    if not uuid_str:
        return ""
    
    # Take first N characters, add "...", add last N characters
    # Example: "abcde12345...XYZ99" (first 5 + last 5)
    return f"{uuid_str[:start]}...{uuid_str[-end:]}"



def build_analytics_filename(f):
    # FUNCTION: Generate descriptive filename for analytics PDF export
    # Input: Filter dict from parse_filters()
    # Output: String like "analytics_30days_all_offices_robbery_manila.pdf"
    # Used by: AnalyticsExportAPIView to set the PDF filename
    # Why? Users can understand what the file contains from the name
    
    # Start with base name including time range
    parts = [f"analytics_{f['days']}days"]
    
    # Add scope (our_office vs all_offices)
    parts.append('our_office' if f['scope'] == 'our_office' else 'all_offices')
    
    # Add category if filtered by a specific crime type
    if f['category']:
        parts.append(f['category'].replace(' ', '_').lower())
    
    # Add city if filtered by a specific location
    if f['city']:
        parts.append(f['city'].replace(' ', '_').lower())
    
    # Combine with underscores and .pdf extension
    # Result: "analytics_30days_our_office_robbery_manila.pdf"
    return '_'.join(parts) + '.pdf'


def build_resolved_filename(f):
    # FUNCTION: Generate descriptive filename for resolved cases PDF export
    # Input: Filter dict from parse_filters()
    # Output: String like "resolved_cases_30days_all_offices.pdf"
    # Used by: ResolvedCasesExportAPIView to set the PDF filename
    # Similar to build_analytics_filename but for resolved cases reports
    
    # Start with base name including time range
    parts = [f"resolved_cases_{f['days']}days"]
    
    # Add scope (our_office vs all_offices)
    parts.append('our_office' if f['scope'] == 'our_office' else 'all_offices')
    
    # Add category if filtered by a specific crime type
    if f['category']:
        parts.append(f['category'].replace(' ', '_').lower())
    
    # Add city if filtered by a specific location
    if f['city']:
        parts.append(f['city'].replace(' ', '_').lower())
    
    # Combine with underscores and .pdf extension
    # Result: "resolved_cases_30days_all_offices.pdf"
    return '_'.join(parts) + '.pdf'