#!/usr/bin/env python3
"""
Meetup Finder — server with reminder scheduling
Reminder scheduler runs in a background thread and fires email/SMS
at 24 h, 6 h, and 2 h before each event.
"""

import json, os, re, math, mimetypes, base64
import urllib.request, urllib.error, urllib.parse
import smtplib, uuid, threading, time
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from http.server           import HTTPServer, BaseHTTPRequestHandler
from pathlib               import Path
from datetime              import datetime, timezone, timedelta

PORT           = int(os.environ.get('PORT', 3000))
PUBLIC_DIR     = Path(__file__).parent / 'public'
REMINDERS_FILE = Path(__file__).parent / 'reminders.json'
MEETUP_GQL     = 'https://api.meetup.com/gql'
_lock          = threading.Lock()          # guards reminders.json

# ── Sample meetups (eventDatetime used by the scheduler) ─────────────────────
SAMPLE_MEETUPS = [
    {
        'id': 1, 'topic': 'tennis',
        'name': 'Issaquah Tennis Club — Weekly Pickup',
        'schedule': 'Every Saturday', 'time': '9:00 AM – 11:00 AM',
        'nextDate': 'Sat, Jun 13, 2026', 'eventDatetime': '2026-06-13T09:00:00-07:00',
        'venue': 'Issaquah Community Center Courts',
        'address': '301 EW Pickering Farm Rd, Issaquah, WA 98027',
        'distanceMi': 0.4, 'members': 24, 'attending': 12,
        'lat': 47.5346, 'lng': -122.0490,
        'description': 'Open to all skill levels. Rotating doubles keeps everyone active. Balls provided — just bring your racket.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=tennis&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 2, 'topic': 'tennis',
        'name': 'Eastside Casual Tennis',
        'schedule': 'Every Thursday', 'time': '6:00 PM – 8:00 PM',
        'nextDate': 'Thu, Jun 11, 2026', 'eventDatetime': '2026-06-11T18:00:00-07:00',
        'venue': 'Tibbetts Valley Park Tennis Courts',
        'address': '1979 12th Ave NW, Issaquah, WA 98027',
        'distanceMi': 0.9, 'members': 38, 'attending': 8,
        'lat': 47.5438, 'lng': -122.0279,
        'description': 'Relaxed evening sessions for intermediate players. Four courts reserved. Friendly, welcoming atmosphere.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=tennis&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 3, 'topic': 'tennis',
        'name': 'Morning Rally Tennis',
        'schedule': 'Tuesdays & Fridays', 'time': '7:00 AM – 9:00 AM',
        'nextDate': 'Fri, Jun 12, 2026', 'eventDatetime': '2026-06-12T07:00:00-07:00',
        'venue': 'Gilman Playground Courts',
        'address': '500 2nd Ave SE, Issaquah, WA 98027',
        'distanceMi': 0.6, 'members': 29, 'attending': 6,
        'lat': 47.5345, 'lng': -122.0468,
        'description': 'Pre-work tennis for early risers. Consistent group, great way to start the day. Intermediate to advanced.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=tennis&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 4, 'topic': 'tennis',
        'name': 'Pine Lake Tennis Group',
        'schedule': 'Every Sunday', 'time': '10:00 AM – 12:00 PM',
        'nextDate': 'Sun, Jun 14, 2026', 'eventDatetime': '2026-06-14T10:00:00-07:00',
        'venue': 'Pine Lake Park Tennis Courts',
        'address': '228th Ave SE & SE 24th St, Sammamish, WA',
        'distanceMi': 4.5, 'members': 45, 'attending': 10,
        'lat': 47.5934, 'lng': -122.0439,
        'description': 'Scenic park courts with Cascade mountain views. Open rallies and organised match play. Intermediate+ preferred.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=tennis&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 5, 'topic': 'science',
        'name': 'Eastside Science & Technology Enthusiasts',
        'schedule': '2nd Tuesday of month', 'time': '7:00 PM – 9:00 PM',
        'nextDate': 'Tue, Jun 9, 2026', 'eventDatetime': '2026-06-09T19:00:00-07:00',
        'venue': 'Issaquah Library — Meeting Room',
        'address': '10 W Sunset Way, Issaquah, WA 98027',
        'distanceMi': 0.2, 'members': 156, 'attending': 25,
        'lat': 47.5308, 'lng': -122.0315,
        'description': 'Monthly talks and demos covering physics, biology, AI, and emerging tech. Speakers from UW, local startups, and national labs.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=science&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 6, 'topic': 'science',
        'name': 'BioTech & Life Sciences Networking',
        'schedule': '2nd Thursday of month', 'time': '6:00 PM – 8:00 PM',
        'nextDate': 'Thu, Jun 11, 2026', 'eventDatetime': '2026-06-11T18:00:00-07:00',
        'venue': 'Issaquah Community Center',
        'address': '301 EW Pickering Farm Rd, Issaquah, WA 98027',
        'distanceMi': 0.4, 'members': 112, 'attending': 30,
        'lat': 47.5350, 'lng': -122.0495,
        'description': 'Networking and knowledge-sharing for biotech professionals, students, and curious minds. Guest talks and open Q&A.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=science&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 7, 'topic': 'science',
        'name': 'Cascades Science Discovery',
        'schedule': 'Every Wednesday', 'time': '6:30 PM – 8:30 PM',
        'nextDate': 'Wed, Jun 10, 2026', 'eventDatetime': '2026-06-10T18:30:00-07:00',
        'venue': 'Lake Sammamish State Park Pavilion',
        'address': '2000 NW Sammamish Rd, Issaquah, WA 98027',
        'distanceMi': 4.2, 'members': 67, 'attending': 15,
        'lat': 47.5679, 'lng': -122.0690,
        'description': 'Nature-based science exploration: Cascades ecology, geology, and wildlife. Occasional guided outdoor walks included.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=science&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    },
    {
        'id': 8, 'topic': 'science',
        'name': 'Pacific Northwest Astronomy Club',
        'schedule': 'Last Friday of month', 'time': '8:00 PM – 11:00 PM',
        'nextDate': 'Fri, Jun 26, 2026', 'eventDatetime': '2026-06-26T20:00:00-07:00',
        'venue': 'Cougar Mountain Regional Wildland Park',
        'address': 'Cougar Mountain Park, Bellevue, WA 98006',
        'distanceMi': 3.8, 'members': 89, 'attending': 20,
        'lat': 47.5167, 'lng': -122.0901,
        'description': 'Stargazing with club telescopes at a dark-sky site. Minimal light pollution. Beginners and experienced astronomers welcome.',
        'meetupUrl': 'https://www.meetup.com/find/?keywords=science&location=Issaquah%2C+WA&source=EVENTS&distance=fiveMiles'
    }
]

# ── Reminder storage ──────────────────────────────────────────────────────────
def load_reminders():
    with _lock:
        if REMINDERS_FILE.exists():
            try:
                return json.loads(REMINDERS_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

def save_reminders(reminders):
    with _lock:
        REMINDERS_FILE.write_text(json.dumps(reminders, indent=2, default=str))

# ── Email ─────────────────────────────────────────────────────────────────────
def _email_html(r, hours_before):
    accent = '#16a34a' if r.get('topic') == 'tennis' else '#2563eb'
    icon   = '🎾' if r.get('topic') == 'tennis' else '🔬'
    plural = 's' if hours_before != 1 else ''
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',system-ui,sans-serif">
  <div style="max-width:560px;margin:28px auto;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)">
    <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:#fff;padding:26px 28px">
      <div style="font-size:1.05rem;opacity:.7;margin-bottom:4px">Meetup Finder — Issaquah, WA</div>
      <div style="font-size:1.5rem;font-weight:800">🔔 Event Reminder</div>
    </div>
    <div style="background:#fff;padding:28px">
      <div style="background:#fef9c3;color:#854d0e;border:1px solid #fde68a;border-radius:8px;padding:10px 16px;margin-bottom:20px;font-weight:700;font-size:.95rem">
        ⏰ Starting in {hours_before} hour{plural}
      </div>
      <div style="font-size:.8rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:{accent};margin-bottom:6px">
        {icon} {r.get('topic','').capitalize()}
      </div>
      <h2 style="margin:0 0 14px;font-size:1.2rem;color:#1e293b">{r['eventName']}</h2>
      <div style="background:#f8fafc;border-radius:10px;padding:16px;margin-bottom:20px">
        <div style="color:#475569;font-size:.9rem;margin-bottom:8px">📅 {r['eventNextDate']} &nbsp;·&nbsp; {r['eventTime']}</div>
        <div style="color:#475569;font-size:.9rem">📍 {r['eventVenue']}</div>
      </div>
      <div style="color:#94a3b8;font-size:.78rem;border-top:1px solid #f1f5f9;padding-top:16px">
        You set this reminder via Meetup Finder.
        To cancel remaining reminders open the app and click the bell icon on this event.
      </div>
    </div>
  </div>
</body>
</html>"""

def send_email(to_addr, subject, html_body, plain_body):
    host    = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port    = int(os.environ.get('SMTP_PORT', 587))
    user    = os.environ.get('SMTP_USER', '').strip()
    passwd  = os.environ.get('SMTP_PASS', '').strip()
    sender  = os.environ.get('SMTP_FROM', user)

    if not user or not passwd:
        print(f'  [Email] SMTP not configured — skipping {to_addr}')
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'Meetup Finder <{sender}>'
    msg['To']      = to_addr
    msg.attach(MIMEText(plain_body, 'plain'))
    msg.attach(MIMEText(html_body,  'html'))

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, passwd)
            smtp.send_message(msg)
        print(f'  [Email] Sent "{subject}" → {to_addr}')
        return True
    except Exception as exc:
        print(f'  [Email] Error → {to_addr}: {exc}')
        return False

# ── SMS via Twilio REST API (no external package needed) ──────────────────────
def send_sms(to_number, body):
    sid        = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
    token      = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    from_num   = os.environ.get('TWILIO_FROM_NUMBER', '').strip()

    if not (sid and token and from_num):
        print(f'  [SMS] Twilio not configured — skipping {to_number}')
        return False

    url  = f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'
    cred = base64.b64encode(f'{sid}:{token}'.encode()).decode()
    data = urllib.parse.urlencode({'From': from_num, 'To': to_number, 'Body': body}).encode()

    req = urllib.request.Request(
        url, data=data,
        headers={'Authorization': f'Basic {cred}',
                 'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        print(f'  [SMS] Sent → {to_number}  SID={result.get("sid")}')
        return True
    except Exception as exc:
        print(f'  [SMS] Error → {to_number}: {exc}')
        return False

# ── Reminder scheduler ────────────────────────────────────────────────────────
def _parse_dt(iso_str):
    """Parse ISO-8601 with UTC offset (e.g. 2026-06-13T09:00:00-07:00)."""
    return datetime.fromisoformat(iso_str)

def _fire_reminder(r, hours_before):
    plural  = 's' if hours_before != 1 else ''
    subject = f'Reminder: "{r["eventName"]}" starts in {hours_before} hour{plural}'
    plain   = (f'This is your {hours_before}h reminder for:\n\n'
               f'{r["eventName"]}\n'
               f'{r["eventNextDate"]} · {r["eventTime"]}\n'
               f'{r["eventVenue"]}\n\n'
               f'See you there!')
    sms_body = (f'Reminder: {r["eventName"]} starts in {hours_before}h. '
                f'{r["eventVenue"]}. {r["eventNextDate"]} {r["eventTime"]}')[:160]

    if r.get('email'):
        send_email(r['email'], subject, _email_html(r, hours_before), plain)
    if r.get('phone'):
        send_sms(r['phone'], sms_body)

def _check_reminders():
    reminders = load_reminders()
    now       = datetime.now(timezone.utc)
    changed   = False

    for r in reminders:
        if r.get('cancelled'):
            continue
        try:
            event_dt = _parse_dt(r['eventDatetime']).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue

        if event_dt < now:
            continue

        sent = set(r.get('sentIntervals', []))
        for hours in r.get('intervals', []):
            if hours in sent:
                continue
            fire_at = event_dt - timedelta(hours=hours)
            if now >= fire_at:
                print(f'  [Scheduler] Firing {hours}h reminder for "{r["eventName"]}"')
                _fire_reminder(r, hours)
                sent.add(hours)
                r['sentIntervals'] = list(sent)
                changed = True

    if changed:
        save_reminders(reminders)

def _scheduler_loop():
    print('  [Scheduler] Started — checking every 60 s')
    while True:
        try:
            _check_reminders()
        except Exception as exc:
            print(f'  [Scheduler] Unexpected error: {exc}')
        time.sleep(60)

# ── Live Meetup.com GraphQL client ────────────────────────────────────────────
GQL_QUERY = """
query($query: String!, $lat: Float!, $lon: Float!, $radius: Float!) {
  keywordSearch(
    filter: { query: $query, lat: $lat, lon: $lon, radius: $radius, source: EVENTS }
    input: { first: 20 }
  ) {
    edges { node { result {
      ... on Event {
        id title description dateTime eventUrl going
        venue { name address city state lat lon }
        group { name urlname memberships { count } }
      }
    }}}
  }
}
"""

def _haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2-lat1)/2)**2
         + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def fetch_live_events(topic, lat, lng, radius_miles):
    token = os.environ.get('MEETUP_ACCESS_TOKEN', '').strip()
    if not token:
        return None
    payload = json.dumps({'query': GQL_QUERY,
                          'variables': {'query': topic, 'lat': lat,
                                        'lon': lng, 'radius': radius_miles*1609.34}}).encode()
    req = urllib.request.Request(
        MEETUP_GQL, data=payload,
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {token}'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        edges = (data.get('data') or {}).get('keywordSearch', {}).get('edges', [])
        results = []
        for edge in edges:
            r = (edge.get('node') or {}).get('result') or {}
            if not r.get('id'):
                continue
            v = r.get('venue') or {}
            g = r.get('group') or {}
            vlat, vlon = v.get('lat', lat), v.get('lon', lng)
            results.append({
                'id': r['id'], 'topic': topic,
                'name': r.get('title', ''),
                'description': (r.get('description') or '')[:300],
                'nextDate': r.get('dateTime', ''), 'eventDatetime': r.get('dateTime', ''),
                'schedule': 'See event page', 'time': '',
                'venue': v.get('name', 'TBD'),
                'address': ', '.join(filter(None, [v.get('address'), v.get('city'), v.get('state')])),
                'distanceMi': round(_haversine(lat, lng, vlat, vlon), 1),
                'members': (g.get('memberships') or {}).get('count', 0),
                'attending': r.get('going', 0),
                'lat': vlat, 'lng': vlon,
                'meetupUrl': r.get('eventUrl', f'https://www.meetup.com/{g.get("urlname","")}')
            })
        return results or None
    except Exception as exc:
        print(f'  [Meetup API] {exc}')
        return None

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f'  {self.address_string()}  {fmt % args}')

    # helpers
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, fpath):
        fpath = Path(fpath)
        if not fpath.is_file():
            self._send_json({'error': 'Not found'}, 404)
            return
        data = fpath.read_bytes()
        mime = mimetypes.guess_type(str(fpath))[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b''
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _qs(raw):
        if '?' not in raw:
            return {}
        return dict(urllib.parse.parse_qsl(raw.split('?', 1)[1]))

    # ── OPTIONS (CORS preflight) ──────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self):
        path   = self.path.split('?')[0]
        params = self._qs(self.path)

        if path == '/api/status':
            self._send_json({
                'liveApi':   bool(os.environ.get('MEETUP_ACCESS_TOKEN')),
                'emailReady': bool(os.environ.get('SMTP_USER')),
                'smsReady':  bool(os.environ.get('TWILIO_ACCOUNT_SID')),
                'location':  'Issaquah, WA',
                'center':    {'lat': 47.5301, 'lng': -122.0326},
                'radiusMiles': 5,
                'serverTime': datetime.now(timezone.utc).isoformat()
            })
            return

        if path == '/api/meetups':
            topics_raw = params.get('topics', 'tennis,science')
            lat    = float(params.get('lat',    47.5301))
            lng    = float(params.get('lng',   -122.0326))
            radius = float(params.get('radius', 5.0))
            topic_list = [t.strip().lower() for t in topics_raw.split(',') if t.strip()]
            source, results = 'sample', []
            if os.environ.get('MEETUP_ACCESS_TOKEN'):
                for t in topic_list:
                    live = fetch_live_events(t, lat, lng, radius)
                    if live:
                        results.extend(live); source = 'live'
            if not results:
                results = [m for m in SAMPLE_MEETUPS if m['topic'] in topic_list]
            self._send_json({'source': source, 'meetups': results,
                             'count': len(results),
                             'fetchedAt': datetime.now(timezone.utc).isoformat()})
            return

        m = re.fullmatch(r'/api/meetups/(\d+)', path)
        if m:
            mid = int(m.group(1))
            rec = next((x for x in SAMPLE_MEETUPS if x['id'] == mid), None)
            self._send_json(rec if rec else {'error': 'Not found'}, 200 if rec else 404)
            return

        if path == '/api/reminders':
            reminders = [r for r in load_reminders() if not r.get('cancelled')]
            self._send_json({'reminders': reminders, 'count': len(reminders)})
            return

        m = re.fullmatch(r'/api/reminders/([0-9a-f\-]+)', path)
        if m:
            rid = m.group(1)
            rec = next((r for r in load_reminders() if r['id'] == rid), None)
            self._send_json(rec if rec else {'error': 'Not found'}, 200 if rec else 404)
            return

        if path == '/':
            path = '/index.html'
        fp = PUBLIC_DIR / path.lstrip('/')
        self._send_file(fp) if fp.is_file() else self._send_file(PUBLIC_DIR / 'index.html')

    # ── POST ──────────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self.path.split('?')[0]
        data = self._read_body()
        if data is None:
            self._send_json({'error': 'Invalid JSON body'}, 400)
            return

        if path == '/api/reminders':
            self._create_reminder(data)
            return

        self._send_json({'error': 'Not found'}, 404)

    def _create_reminder(self, data):
        event_id  = data.get('eventId')
        email     = (data.get('email') or '').strip().lower()
        phone     = (data.get('phone') or '').strip()
        intervals = data.get('intervals', [])

        if not event_id:
            self._send_json({'error': 'eventId is required'}, 400); return
        if not email and not phone:
            self._send_json({'error': 'Provide at least an email address or phone number'}, 400); return

        valid_intervals = {h for h in intervals if h in (2, 6, 24)}
        if not valid_intervals:
            self._send_json({'error': 'Select at least one reminder time (2h, 6h, or 24h)'}, 400); return

        meetup = next((m for m in SAMPLE_MEETUPS if m['id'] == event_id), None)
        if not meetup:
            self._send_json({'error': 'Event not found'}, 404); return

        if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            self._send_json({'error': 'Invalid email address'}, 400); return

        # normalise phone → E.164
        if phone:
            digits = re.sub(r'\D', '', phone)
            if len(digits) == 10:
                digits = '1' + digits
            if len(digits) != 11:
                self._send_json({'error': 'Phone must be a 10-digit US number or E.164 format'}, 400); return
            phone = '+' + digits

        # reject if event already passed
        try:
            event_dt = _parse_dt(meetup['eventDatetime']).astimezone(timezone.utc)
            if event_dt < datetime.now(timezone.utc):
                self._send_json({'error': 'This event has already passed'}, 400); return
        except ValueError:
            pass

        reminder = {
            'id':             str(uuid.uuid4()),
            'eventId':        event_id,
            'eventName':      meetup['name'],
            'eventDatetime':  meetup['eventDatetime'],
            'eventNextDate':  meetup['nextDate'],
            'eventTime':      meetup.get('time', ''),
            'eventVenue':     meetup['venue'],
            'topic':          meetup['topic'],
            'email':          email or None,
            'phone':          phone or None,
            'intervals':      sorted(valid_intervals, reverse=True),
            'sentIntervals':  [],
            'cancelled':      False,
            'createdAt':      datetime.now(timezone.utc).isoformat()
        }
        reminders = load_reminders()
        reminders.append(reminder)
        save_reminders(reminders)

        labels = [f'{h}h' for h in reminder['intervals']]
        self._send_json({
            'id':      reminder['id'],
            'message': f"Reminder set! You'll be notified {', '.join(labels)} before the event.",
            'reminder': reminder
        }, 201)

    # ── DELETE ────────────────────────────────────────────────────────────────
    def do_DELETE(self):
        path = self.path.split('?')[0]
        m = re.fullmatch(r'/api/reminders/([0-9a-f\-]+)', path)
        if not m:
            self._send_json({'error': 'Not found'}, 404); return

        rid       = m.group(1)
        reminders = load_reminders()
        rec       = next((r for r in reminders if r['id'] == rid), None)
        if not rec:
            self._send_json({'error': 'Reminder not found'}, 404); return

        rec['cancelled'] = True
        save_reminders(reminders)
        self._send_json({'message': 'Reminder cancelled'})

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    t = threading.Thread(target=_scheduler_loop, daemon=True)
    t.start()

    httpd = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'\n  Meetup Finder  →  http://localhost:{PORT}')
    print(f'  Meetup API  : {"Live" if os.environ.get("MEETUP_ACCESS_TOKEN") else "Sample data"}')
    print(f'  Email       : {"Ready (" + os.environ.get("SMTP_USER","") + ")" if os.environ.get("SMTP_USER") else "Not configured (set SMTP_USER / SMTP_PASS)"}')
    print(f'  SMS         : {"Ready" if os.environ.get("TWILIO_ACCOUNT_SID") else "Not configured (set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER)"}')
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
