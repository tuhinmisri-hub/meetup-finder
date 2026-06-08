#!/usr/bin/env python3
"""Event Finder — dynamic zip-based search with reminder scheduling."""

import json, os, re, math, mimetypes, base64, calendar
import urllib.request, urllib.error, urllib.parse
import smtplib, uuid, threading, time
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from http.server           import HTTPServer, BaseHTTPRequestHandler
from pathlib               import Path
from datetime              import datetime, timezone, timedelta, date

PORT           = int(os.environ.get('PORT', 3000))
PUBLIC_DIR     = Path(__file__).parent / 'public'
REMINDERS_FILE = Path(__file__).parent / 'reminders.json'
_lock          = threading.Lock()

# ── Topic catalogue ───────────────────────────────────────────────────────────
TOPICS = {
    'tennis':      {'label': 'Tennis',      'icon': 'fa-table-tennis-paddle-ball', 'color': '#16a34a'},
    'science':     {'label': 'Science',     'icon': 'fa-flask',                    'color': '#2563eb'},
    'hiking':      {'label': 'Hiking',      'icon': 'fa-person-hiking',            'color': '#ea580c'},
    'technology':  {'label': 'Technology',  'icon': 'fa-laptop-code',              'color': '#7c3aed'},
    'photography': {'label': 'Photography', 'icon': 'fa-camera',                   'color': '#db2777'},
    'fitness':     {'label': 'Fitness',     'icon': 'fa-dumbbell',                 'color': '#dc2626'},
    'books':       {'label': 'Books',       'icon': 'fa-book-open',                'color': '#0d9488'},
    'music':       {'label': 'Music',       'icon': 'fa-music',                    'color': '#4f46e5'},
    'food':        {'label': 'Food',        'icon': 'fa-utensils',                 'color': '#b45309'},
    'outdoors':    {'label': 'Outdoors',    'icon': 'fa-tree',                     'color': '#15803d'},
}

# weekday: 0=Mon … 6=Sun   scheduleType: weekly | biweekly | monthly | monthly_last
TOPIC_EVENTS = {
    'tennis': [
        {'name': '{city} Tennis Club — Weekly Pickup', 'scheduleType': 'weekly',       'weekday': 5, 'hour': 9,  'duration': 2, 'venue': '{city} Community Center Courts',    'desc': 'Open to all skill levels. Rotating doubles. Balls provided.'},
        {'name': 'Evening Tennis Social',              'scheduleType': 'weekly',       'weekday': 3, 'hour': 18, 'duration': 2, 'venue': '{city} Park Tennis Courts',          'desc': 'Relaxed evening sessions. Friendly atmosphere for all levels.'},
        {'name': '{city} Tennis Mixer',                'scheduleType': 'monthly',      'weekday': 6, 'nth': 2,   'hour': 10, 'duration': 2, 'venue': 'Sports Complex',        'desc': 'Monthly social mixer with ladder play. All levels welcome.'},
        {'name': 'Morning Rally Tennis',               'scheduleType': 'weekly',       'weekday': 1, 'hour': 7,  'duration': 2, 'venue': 'Recreation Center Courts',          'desc': 'Pre-work tennis for early risers. Intermediate to advanced.'},
    ],
    'science': [
        {'name': '{city} Science & Tech Enthusiasts',  'scheduleType': 'monthly',      'weekday': 1, 'nth': 2,   'hour': 19, 'duration': 2, 'venue': '{city} Public Library — Meeting Room', 'desc': 'Monthly talks on physics, biology, AI, and emerging tech.'},
        {'name': 'BioTech & Life Sciences Networking', 'scheduleType': 'monthly',      'weekday': 3, 'nth': 2,   'hour': 18, 'duration': 2, 'venue': '{city} Community Center',              'desc': 'Networking for biotech professionals, students, and curious minds.'},
        {'name': 'Astronomy & Stargazing Night',       'scheduleType': 'monthly_last', 'weekday': 4,             'hour': 20, 'duration': 3, 'venue': 'Regional Park (dark-sky site)',         'desc': 'Stargazing with club telescopes. Beginners always welcome.'},
        {'name': 'Nature & Ecology Walks',             'scheduleType': 'weekly',       'weekday': 2, 'hour': 18, 'duration': 2, 'venue': 'State Park Pavilion',                             'desc': 'Explore local ecology, geology, and wildlife with a naturalist guide.'},
        {'name': 'Science News Weekly',                'scheduleType': 'weekly',       'weekday': 0, 'hour': 19, 'duration': 2, 'venue': '{city} Public Library',                           'desc': 'Weekly roundup and discussion of the latest science & research news.'},
    ],
    'hiking': [
        {'name': '{city} Trail Blazers',    'scheduleType': 'weekly',  'weekday': 6, 'hour': 8,  'duration': 4, 'venue': 'Trailhead Parking Lot',      'desc': 'Weekend morning hikes. Easy to moderate difficulty. Dogs welcome.'},
        {'name': 'Weeknight Nature Walk',   'scheduleType': 'weekly',  'weekday': 2, 'hour': 17, 'duration': 2, 'venue': '{city} City Park Entrance',  'desc': 'Short evening walks in local parks. Great for all fitness levels.'},
        {'name': '{city} Summit Seekers',   'scheduleType': 'monthly', 'weekday': 5, 'nth': 1,   'hour': 7, 'duration': 6, 'venue': 'Carpooling Meeting Point', 'desc': 'Monthly challenging hike with significant elevation gain. Intermediate+.'},
    ],
    'technology': [
        {'name': '{city} Developers Meetup',       'scheduleType': 'monthly',   'weekday': 2, 'nth': 3,  'hour': 18, 'duration': 2, 'venue': 'Co-working Space',        'desc': 'Talks, demos, and networking for software developers. All stacks welcome.'},
        {'name': 'AI & Machine Learning Group',    'scheduleType': 'biweekly',  'weekday': 1, 'hour': 19, 'duration': 2, 'venue': '{city} Public Library',           'desc': 'Collaborative learning on ML concepts, papers, and hands-on projects.'},
        {'name': 'Startup Founders Coffee',        'scheduleType': 'monthly',   'weekday': 5, 'nth': 1,  'hour': 9,  'duration': 2, 'venue': 'Local Coffee Shop',       'desc': 'Informal networking for startup founders and entrepreneurs. No pitch decks.'},
        {'name': '{city} Cyber & Security Talks',  'scheduleType': 'monthly',   'weekday': 3, 'nth': 3,  'hour': 18, 'duration': 2, 'venue': 'Tech Hub Conference Room', 'desc': 'Talks on cybersecurity, privacy, and digital safety for all experience levels.'},
        {'name': 'Weekly Dev Showcase',            'scheduleType': 'weekly',    'weekday': 3, 'hour': 18, 'duration': 2, 'venue': 'Co-working Space',                'desc': 'Show and tell for developers — share what you built this week. All languages.'},
    ],
    'photography': [
        {'name': '{city} Photography Walk',      'scheduleType': 'weekly',  'weekday': 6, 'hour': 7,  'duration': 3, 'venue': 'Downtown Meeting Point', 'desc': 'Morning photo walks exploring local scenes. All cameras welcome.'},
        {'name': 'Photography Critique Night',   'scheduleType': 'monthly', 'weekday': 2, 'nth': 2,   'hour': 19, 'duration': 2, 'venue': '{city} Community Center',  'desc': 'Share your recent shots for friendly critique and feedback.'},
        {'name': 'Golden Hour Shoot',            'scheduleType': 'monthly', 'weekday': 4, 'nth': 3,   'hour': 18, 'duration': 2, 'venue': '{city} Lake Park',          'desc': 'Evening session capturing golden hour and sunset light together.'},
    ],
    'fitness': [
        {'name': '{city} Outdoor Boot Camp', 'scheduleType': 'weekly', 'weekday': 5, 'hour': 7,  'duration': 1, 'venue': '{city} City Park',   'desc': 'High-energy outdoor workout. All fitness levels welcome. Bring water.'},
        {'name': 'Morning Yoga in the Park', 'scheduleType': 'weekly', 'weekday': 6, 'hour': 8,  'duration': 1, 'venue': 'Park Lawn',           'desc': 'Relaxing outdoor yoga session. Bring your own mat. Free.'},
        {'name': 'Running Club — 5K Fun Run','scheduleType': 'weekly', 'weekday': 0, 'hour': 7,  'duration': 1, 'venue': 'Community Track',     'desc': 'Friendly group runs at all paces. Walkers always welcome.'},
    ],
    'books': [
        {'name': '{city} Book Club',             'scheduleType': 'monthly', 'weekday': 6, 'nth': 2,   'hour': 14, 'duration': 2, 'venue': '{city} Public Library', 'desc': 'Monthly fiction and non-fiction reads. New members welcome.'},
        {'name': 'Science Fiction Reading Group','scheduleType': 'monthly', 'weekday': 4, 'nth': 3,   'hour': 19, 'duration': 2, 'venue': 'Local Bookstore',         'desc': 'Deep dives into classic and contemporary sci-fi. Lively discussions.'},
        {'name': 'Writers Workshop',             'scheduleType': 'biweekly','weekday': 2, 'hour': 18, 'duration': 2, 'venue': 'Coffee Shop',             'desc': 'Supportive workshop for writers of all genres. Share excerpts and get feedback.'},
        {'name': 'Weekend Reading Hour',         'scheduleType': 'weekly',  'weekday': 6, 'hour': 10, 'duration': 2, 'venue': 'Local Coffee Shop',        'desc': 'Casual Saturday reading session. Bring whatever you\'re currently reading.'},
    ],
    'music': [
        {'name': '{city} Open Mic Night',     'scheduleType': 'weekly',   'weekday': 4, 'hour': 19, 'duration': 3, 'venue': 'Local Venue Stage',   'desc': 'All musicians welcome. 10-minute slots. Sign up at the door.'},
        {'name': 'Acoustic Jam Session',      'scheduleType': 'biweekly', 'weekday': 5, 'hour': 18, 'duration': 3, 'venue': 'Music Studio',         'desc': 'Casual acoustic jam. All skill levels, all styles. Bring your instrument.'},
        {'name': 'Music Theory Study Group',  'scheduleType': 'monthly',  'weekday': 2, 'nth': 1,   'hour': 19, 'duration': 2, 'venue': 'Community Center', 'desc': 'Learning music theory together. Beginners to intermediate welcome.'},
    ],
    'food': [
        {'name': '{city} Foodies & Cooks',       'scheduleType': 'monthly',  'weekday': 6, 'nth': 2,  'hour': 12, 'duration': 3, 'venue': 'Community Kitchen',       'desc': 'Cook and share dishes from different cuisines. Bring a dish to share.'},
        {'name': 'Farmers Market Social',        'scheduleType': 'weekly',   'weekday': 5, 'hour': 9,  'duration': 2, 'venue': '{city} Farmers Market',      'desc': "Explore local produce and artisan foods together. Every Saturday morning."},
        {'name': 'Restaurant Explorers',         'scheduleType': 'monthly',  'weekday': 4, 'nth': 3,  'hour': 19, 'duration': 2, 'venue': 'Rotating Local Restaurants', 'desc': 'Monthly group dinner at a different local restaurant. All cuisines.'},
    ],
    'outdoors': [
        {'name': '{city} Paddling Club',        'scheduleType': 'weekly',   'weekday': 6, 'hour': 9,  'duration': 3, 'venue': 'Boat Launch / Waterfront', 'desc': 'Kayak and canoe meetups on local lakes and rivers. Beginners welcome.'},
        {'name': 'Bird Watching Walk',          'scheduleType': 'biweekly', 'weekday': 6, 'hour': 7,  'duration': 3, 'venue': 'Nature Reserve Entrance',  'desc': 'Guided bird-watching walk for all experience levels. Binoculars recommended.'},
        {'name': '{city} Cycling Group',        'scheduleType': 'weekly',   'weekday': 0, 'hour': 8,  'duration': 3, 'venue': 'Trailhead Parking Lot',     'desc': 'Sunday morning group rides on paved and gravel paths. Multiple pace groups.'},
        {'name': 'Backpacking Planning Night',  'scheduleType': 'monthly',  'weekday': 1, 'nth': 2,   'hour': 19, 'duration': 2, 'venue': 'Outdoor Gear Shop',      'desc': 'Plan upcoming backpacking trips and share gear knowledge.'},
    ],
}

# ── Date helpers ──────────────────────────────────────────────────────────────
def _next_weekday(wd):
    """Next occurrence of weekday wd (0=Mon,6=Sun) from today, inclusive."""
    today = date.today()
    delta = (wd - today.weekday()) % 7
    return today + timedelta(days=delta if delta else 7)

def _nth_weekday_of_month(n, wd, ref=None):
    """n-th occurrence (1-based) of weekday wd in ref's month; steps forward if past."""
    ref = ref or date.today()
    first = ref.replace(day=1)
    offset = (wd - first.weekday()) % 7
    d = first + timedelta(days=offset + 7*(n-1))
    if d < date.today():
        nxt = (ref.replace(day=1) + timedelta(days=32)).replace(day=1)
        return _nth_weekday_of_month(n, wd, nxt)
    return d

def _last_weekday_of_month(wd, ref=None):
    """Last occurrence of weekday wd in ref's month; steps forward if past."""
    ref = ref or date.today()
    last_day = calendar.monthrange(ref.year, ref.month)[1]
    last = ref.replace(day=last_day)
    offset = (last.weekday() - wd) % 7
    d = last - timedelta(days=offset)
    if d < date.today():
        nxt = (ref.replace(day=1) + timedelta(days=32)).replace(day=1)
        return _last_weekday_of_month(wd, nxt)
    return d

def _event_date(tmpl):
    stype = tmpl.get('scheduleType', 'weekly')
    wd    = tmpl['weekday']
    if stype == 'weekly' or stype == 'biweekly':
        return _next_weekday(wd)
    if stype == 'monthly':
        return _nth_weekday_of_month(tmpl.get('nth', 1), wd)
    if stype == 'monthly_last':
        return _last_weekday_of_month(wd)
    return _next_weekday(wd)

def _schedule_label(tmpl):
    days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    wd   = tmpl['weekday']
    stype = tmpl.get('scheduleType','weekly')
    nth_names = ['','1st','2nd','3rd','4th']
    if stype == 'weekly':       return f'Every {days[wd]}'
    if stype == 'biweekly':     return f'Every other {days[wd]}'
    if stype == 'monthly':      return f'{nth_names[tmpl.get("nth",1)]} {days[wd]} of month'
    if stype == 'monthly_last': return f'Last {days[wd]} of month'
    return f'Every {days[wd]}'

def _fmt_time(hour, duration):
    def _h(h):
        ampm = 'AM' if h < 12 else 'PM'
        h12  = h % 12 or 12
        return f'{h12}:00 {ampm}'
    return f'{_h(hour)} – {_h(hour + duration)}'

# ── Deterministic seeded RNG ──────────────────────────────────────────────────
def _make_rand(seed_str):
    state = [sum(ord(c) * (i+1) for i, c in enumerate(str(seed_str))) & 0xFFFFFFFF]
    def rand():
        state[0] = (state[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return state[0] / 0xFFFFFFFF
    return rand

def _rand_point(lat, lng, radius_mi, rand):
    r     = radius_mi * rand() ** 0.5
    theta = rand() * 2 * math.pi
    dlat  = (r / 69.0) * math.cos(theta)
    dlng  = (r / (69.0 * math.cos(math.radians(lat)))) * math.sin(theta)
    return round(lat + dlat, 4), round(lng + dlng, 4)

# ── Geocoding ─────────────────────────────────────────────────────────────────
def geocode_zip(zip_code):
    url = f'https://api.zippopotam.us/us/{zip_code}'
    req = urllib.request.Request(url, headers={'User-Agent': 'MeetupFinder/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get('post code') != zip_code:
            return None
        p = data['places'][0]
        return {
            'lat':   float(p['latitude']),
            'lng':   float(p['longitude']),
            'city':  p['place name'],
            'state': p['state abbreviation'],
            'zip':   zip_code,
        }
    except Exception as exc:
        print(f'  [Geocode] zip={zip_code}: {exc}')
        return None

def reverse_geocode(lat, lng):
    url = f'https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json'
    req = urllib.request.Request(url, headers={'User-Agent': 'MeetupFinder/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        addr = data.get('address', {})
        city = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('county', 'Local')
        return {
            'lat':   lat,
            'lng':   lng,
            'city':  city,
            'state': addr.get('state', ''),
            'zip':   addr.get('postcode', ''),
        }
    except Exception as exc:
        print(f'  [RevGeocode] {exc}')
        return {'lat': lat, 'lng': lng, 'city': 'Local', 'state': '', 'zip': ''}

# ── Sample meetup generation ──────────────────────────────────────────────────
def generate_sample_meetups(loc, radius_mi, topics, days=7):
    today  = date.today()
    cutoff = today + timedelta(days=days)
    rand   = _make_rand(loc.get('zip') or f'{loc["lat"]:.2f}{loc["lng"]:.2f}')
    city   = loc.get('city', 'Local')
    state  = loc.get('state', '')
    tz_off = '-07:00'
    results, eid = [], 1

    for topic in topics:
        if topic not in TOPIC_EVENTS:
            continue
        color = TOPICS.get(topic, {}).get('color', '#64748b')
        for tmpl in TOPIC_EVENTS[topic]:
            # Always advance rand for every template to keep positions deterministic
            plat, plng = _rand_point(loc['lat'], loc['lng'], radius_mi, rand)
            members    = max(10, int(rand() * 180) + 15)
            attending  = max(3,  int(rand() * min(members, 35)) + 3)

            dist = round(_haversine(loc['lat'], loc['lng'], plat, plng), 1)
            d    = _event_date(tmpl)

            # Filter: must be within radius AND within the next `days` days
            if dist > radius_mi or d > cutoff:
                eid += 1
                continue

            hour  = tmpl['hour']
            dt_s  = f"{d.isoformat()}T{hour:02d}:00:00{tz_off}"

            results.append({
                'id':            eid,
                'topic':         topic,
                'color':         color,
                'name':          tmpl['name'].replace('{city}', city),
                'schedule':      _schedule_label(tmpl),
                'time':          _fmt_time(hour, tmpl.get('duration', 2)),
                'nextDate':      d.strftime('%a, %b %-d, %Y'),
                'eventDatetime': dt_s,
                'venue':         tmpl['venue'].replace('{city}', city),
                'address':       f'{city}, {state}',
                'distanceMi':    dist,
                'members':       members,
                'attending':     attending,
                'lat':           plat,
                'lng':           plng,
                'description':   tmpl['desc'],
                'meetupUrl':     (
                    f'https://www.google.com/search?q={urllib.parse.quote(tmpl["name"].replace("{city}", city))}'
                    f'+{urllib.parse.quote(city)}+events&ibp=htl;events'
                ),
            })
            eid += 1

    return results

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
    color  = TOPICS.get(r.get('topic',''), {}).get('color', '#3b82f6')
    plural = 's' if hours_before != 1 else ''
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',system-ui,sans-serif">
  <div style="max-width:560px;margin:28px auto;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)">
    <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:#fff;padding:26px 28px">
      <div style="font-size:1.05rem;opacity:.7;margin-bottom:4px">Event Finder</div>
      <div style="font-size:1.5rem;font-weight:800">🔔 Event Reminder</div>
    </div>
    <div style="background:#fff;padding:28px">
      <div style="background:#fef9c3;color:#854d0e;border:1px solid #fde68a;border-radius:8px;padding:10px 16px;margin-bottom:20px;font-weight:700;font-size:.95rem">
        ⏰ Starting in {hours_before} hour{plural}
      </div>
      <div style="font-size:.8rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:{color};margin-bottom:6px">
        {r.get('topic','').capitalize()}
      </div>
      <h2 style="margin:0 0 14px;font-size:1.2rem;color:#1e293b">{r['eventName']}</h2>
      <div style="background:#f8fafc;border-radius:10px;padding:16px;margin-bottom:20px">
        <div style="color:#475569;font-size:.9rem;margin-bottom:8px">📅 {r['eventNextDate']} &nbsp;·&nbsp; {r['eventTime']}</div>
        <div style="color:#475569;font-size:.9rem">📍 {r['eventVenue']}</div>
      </div>
      <div style="color:#94a3b8;font-size:.78rem;border-top:1px solid #f1f5f9;padding-top:16px">
        You set this reminder via Event Finder.
        To cancel, open the app and click the bell icon on this event.
      </div>
    </div>
  </div>
</body>
</html>"""

def send_email(to_addr, subject, html_body, plain_body):
    host   = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port   = int(os.environ.get('SMTP_PORT', 587))
    user   = os.environ.get('SMTP_USER', '').strip()
    passwd = os.environ.get('SMTP_PASS', '').strip()
    sender = os.environ.get('SMTP_FROM', user)
    if not user or not passwd:
        print(f'  [Email] SMTP not configured — skipping {to_addr}')
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'Event Finder <{sender}>'
    msg['To']      = to_addr
    msg.attach(MIMEText(plain_body, 'plain'))
    msg.attach(MIMEText(html_body,  'html'))
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo(); smtp.starttls(); smtp.login(user, passwd)
            smtp.send_message(msg)
        print(f'  [Email] Sent "{subject}" → {to_addr}')
        return True
    except Exception as exc:
        print(f'  [Email] Error → {to_addr}: {exc}')
        return False

# ── SMS via Twilio ────────────────────────────────────────────────────────────
def send_sms(to_number, body):
    sid      = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
    token    = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    from_num = os.environ.get('TWILIO_FROM_NUMBER', '').strip()
    if not (sid and token and from_num):
        print(f'  [SMS] Twilio not configured — skipping {to_number}')
        return False
    url  = f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'
    cred = base64.b64encode(f'{sid}:{token}'.encode()).decode()
    data = urllib.parse.urlencode({'From': from_num, 'To': to_number, 'Body': body}).encode()
    req  = urllib.request.Request(url, data=data,
           headers={'Authorization': f'Basic {cred}',
                    'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
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
    return datetime.fromisoformat(iso_str)

def _fire_reminder(r, hours_before):
    plural  = 's' if hours_before != 1 else ''
    subject = f'Reminder: "{r["eventName"]}" starts in {hours_before} hour{plural}'
    plain   = (f'{r["eventName"]}\n{r["eventNextDate"]} · {r["eventTime"]}\n{r["eventVenue"]}')
    sms     = f'Reminder: {r["eventName"]} starts in {hours_before}h. {r["eventVenue"]}.'[:160]
    if r.get('email'): send_email(r['email'], subject, _email_html(r, hours_before), plain)
    if r.get('phone'): send_sms(r['phone'], sms)

def _check_reminders():
    reminders = load_reminders()
    now, changed = datetime.now(timezone.utc), False
    for r in reminders:
        if r.get('cancelled'): continue
        try:
            event_dt = _parse_dt(r['eventDatetime']).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        if event_dt < now: continue
        sent = set(r.get('sentIntervals', []))
        for hours in r.get('intervals', []):
            if hours in sent: continue
            if now >= event_dt - timedelta(hours=hours):
                print(f'  [Scheduler] Firing {hours}h reminder for "{r["eventName"]}"')
                _fire_reminder(r, hours)
                sent.add(hours); r['sentIntervals'] = list(sent); changed = True
    if changed: save_reminders(reminders)

def _scheduler_loop():
    print('  [Scheduler] Started — checking every 60 s')
    while True:
        try: _check_reminders()
        except Exception as exc: print(f'  [Scheduler] Error: {exc}')
        time.sleep(60)

# ── SerpAPI Google Events ─────────────────────────────────────────────────────
_geocode_cache = {}

def _geocode_place(query):
    """Geocode a place string using Nominatim. Results cached in memory."""
    key = query.lower().strip()
    if key in _geocode_cache:
        return _geocode_cache[key]
    url = f'https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1'
    req = urllib.request.Request(url, headers={'User-Agent': 'EventFinder/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data:
            result = (float(data[0]['lat']), float(data[0]['lon']))
            _geocode_cache[key] = result
            return result
    except Exception:
        pass
    _geocode_cache[key] = (None, None)
    return (None, None)

def _haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2-lat1)/2)**2
         + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def _parse_serp_date(when_str):
    """Parse SerpAPI 'when' string → (display_date, time_str, datetime_or_None)."""
    if not when_str:
        return '', '', None
    time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM))', when_str, re.IGNORECASE)
    time_str   = time_match.group(1).upper().replace(' ', '') if time_match else ''
    now        = datetime.now()
    months     = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                  'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    weekdays   = {'mon':0,'tue':1,'wed':2,'thu':3,'fri':4,'sat':5,'sun':6}
    d = None
    if 'today' in when_str.lower():
        d = now.date()
    elif 'tomorrow' in when_str.lower():
        d = (now + timedelta(days=1)).date()
    else:
        # Try full month + day first: "Jun 14" / "June 14"
        m = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})',
                      when_str, re.IGNORECASE)
        if m:
            mn, dy = months[m.group(1).lower()[:3]], int(m.group(2))
            try:
                d = date(now.year, mn, dy)
                if d < now.date():
                    d = date(now.year + 1, mn, dy)
            except ValueError:
                pass
        # Fall back to weekday name: "Tue", "Saturday"
        if not d:
            wd = re.search(r'\b(mon|tue|wed|thu|fri|sat|sun)\w*\b', when_str, re.IGNORECASE)
            if wd:
                wd_num = weekdays[wd.group(1).lower()[:3]]
                delta  = (wd_num - now.weekday()) % 7 or 7
                d = now.date() + timedelta(days=delta)
    if not d:
        return when_str, time_str, None
    next_date = d.strftime('%a, %b %-d, %Y')
    hour = 0
    if time_match:
        raw = time_match.group(1).strip()
        h, rest = raw.split(':', 1)
        ampm = rest[-2:].upper()
        h = int(h)
        if ampm == 'PM' and h != 12: h += 12
        elif ampm == 'AM' and h == 12: h = 0
        hour = h
    try:
        dt = datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)
    except Exception:
        dt = None
    return next_date, time_str, dt

def fetch_serpapi_events(topic, city, state, lat, lng, days=7):
    key = os.environ.get('SERPAPI_KEY', '').strip()
    if not key:
        return None
    location = f'{city}, {state}' if state else city
    query    = f'{topic} events near {location}'
    qs = urllib.parse.urlencode({
        'engine':  'google_events',
        'q':       query,
        'api_key': key,
        'hl':      'en',
        'gl':      'us',
    })
    url = f'https://serpapi.com/search?{qs}'
    req = urllib.request.Request(url, headers={'User-Agent': 'MeetupFinder/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        events_raw = data.get('events_results', [])
        color  = TOPICS.get(topic, {}).get('color', '#64748b')
        cutoff = datetime.now(timezone.utc) + timedelta(days=days)
        # Pre-geocode unique cities so map pins land in the right place
        city_coords = {}
        for ev in events_raw:
            parts = ev.get('address') or []
            city_key = parts[-1] if parts else ''
            if city_key and city_key not in city_coords:
                glat, glng = _geocode_place(city_key)
                city_coords[city_key] = (glat, glng)
                if glat: time.sleep(0.2)   # respect Nominatim 1 req/s limit
        results = []
        for ev in events_raw:
            when = (ev.get('date') or {}).get('when', '')
            next_date, time_str, event_dt = _parse_serp_date(when)
            if event_dt and event_dt > cutoff:
                continue
            address_parts = ev.get('address') or []
            venue_name    = address_parts[0] if address_parts else 'TBD'
            address_str   = ', '.join(address_parts[1:]) if len(address_parts) > 1 else location
            city_key      = address_parts[-1] if address_parts else ''
            glat, glng    = city_coords.get(city_key, (None, None))
            plat          = glat if glat else lat
            plng          = glng if glng else lng
            results.append({
                'id':            f'serp_{topic}_{len(results)}',
                'topic':         topic,
                'color':         color,
                'name':          ev.get('title', 'Event'),
                'description':   (ev.get('description') or '')[:300],
                'nextDate':      next_date,
                'eventDatetime': event_dt.isoformat() if event_dt else '',
                'schedule':      'See event page',
                'time':          time_str,
                'venue':         venue_name,
                'address':       address_str,
                'distanceMi':    round(_haversine(lat, lng, plat, plng), 1),
                'members':       0,
                'attending':     0,
                'lat':           round(plat, 4),
                'lng':           round(plng, 4),
                'meetupUrl':     ev.get('link', ''),
                'thumbnail':     ev.get('thumbnail', ''),
            })
        print(f'  [SerpAPI] topic={topic} → {len(results)} events')
        return results or None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        print(f'  [SerpAPI] HTTP {exc.code} for topic={topic}: {body[:200]}')
        return None
    except Exception as exc:
        print(f'  [SerpAPI] {exc}')
        return None

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f'  {self.address_string()}  {fmt % args}')

    def _redirect(self, url, status=302):
        self.send_response(status)
        self.send_header('Location', url)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

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
            self._send_json({'error': 'Not found'}, 404); return
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
        try:   return json.loads(raw) if raw else {}
        except json.JSONDecodeError: return None

    @staticmethod
    def _qs(raw):
        if '?' not in raw: return {}
        return dict(urllib.parse.parse_qsl(raw.split('?', 1)[1]))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path   = self.path.split('?')[0]
        params = self._qs(self.path)

        # ── /api/auth/status ──────────────────────────────────────────────
        if path == '/api/auth/status':
            token = os.environ.get('SERPAPI_KEY', '').strip()
            self._send_json({
                'connected':  bool(token),
                'configured': bool(token),
                'source':     'serpapi',
            }); return

        # ── /api/topics ──────────────────────────────────────────────────────
        if path == '/api/topics':
            self._send_json({'topics': [
                {'id': k, **v} for k, v in TOPICS.items()
            ]}); return

        # ── /api/geocode?zip=XXXXX ───────────────────────────────────────────
        if path == '/api/geocode':
            zip_code = params.get('zip', '').strip()
            if not re.fullmatch(r'\d{5}', zip_code):
                self._send_json({'error': 'Provide a 5-digit US zip code'}, 400); return
            loc = geocode_zip(zip_code)
            if not loc:
                self._send_json({'error': f'Zip code {zip_code} not found'}, 404); return
            self._send_json(loc); return

        # ── /api/reverse-geocode?lat=X&lng=Y ────────────────────────────────
        if path == '/api/reverse-geocode':
            try:
                lat = float(params['lat']); lng = float(params['lng'])
            except (KeyError, ValueError):
                self._send_json({'error': 'lat and lng required'}, 400); return
            self._send_json(reverse_geocode(lat, lng)); return

        # ── /api/status ──────────────────────────────────────────────────────
        if path == '/api/status':
            self._send_json({
                'liveApi':    bool(os.environ.get('SERPAPI_KEY')),
                'emailReady': bool(os.environ.get('SMTP_USER')),
                'smsReady':   bool(os.environ.get('TWILIO_ACCOUNT_SID')),
                'serverTime': datetime.now(timezone.utc).isoformat()
            }); return

        # ── /api/meetups ─────────────────────────────────────────────────────
        if path == '/api/meetups':
            topics_raw = params.get('topics', 'tennis,science')
            topic_list = [t.strip().lower() for t in topics_raw.split(',') if t.strip()]
            radius     = float(params.get('radius', 5.0))
            radius     = max(1.0, min(radius, 50.0))

            # Resolve location: prefer zip, fallback to lat/lng
            zip_code = params.get('zip', '').strip()
            if zip_code and re.fullmatch(r'\d{5}', zip_code):
                loc = geocode_zip(zip_code)
                if not loc:
                    self._send_json({'error': f'Zip code {zip_code} not found'}, 404); return
            else:
                try:
                    lat = float(params.get('lat', 47.5301))
                    lng = float(params.get('lng', -122.0326))
                except ValueError:
                    self._send_json({'error': 'Invalid lat/lng'}, 400); return
                loc = {'lat': lat, 'lng': lng, 'city': 'Local', 'state': '', 'zip': ''}

            days   = max(1, min(int(params.get('days', 7)), 30))
            source, results = 'sample', []
            if os.environ.get('SERPAPI_KEY', '').strip():
                for t in topic_list:
                    live = fetch_serpapi_events(
                        t, loc.get('city', 'Local'), loc.get('state', ''),
                        loc['lat'], loc['lng'], days
                    )
                    if live: results.extend(live); source = 'live'
            if not results:
                results = generate_sample_meetups(loc, radius, topic_list, days)
            else:
                # Deduplicate by name + date (recurring events appear multiple times)
                seen, deduped = set(), []
                for r in results:
                    key = (r['name'].lower().strip(), r.get('nextDate', ''))
                    if key not in seen:
                        seen.add(key)
                        deduped.append(r)
                results = deduped

            self._send_json({
                'source': source, 'meetups': results, 'count': len(results),
                'location': loc, 'days': days,
                'fetchedAt': datetime.now(timezone.utc).isoformat()
            }); return

        # ── static files ─────────────────────────────────────────────────────
        if path == '/': path = '/index.html'
        fp = PUBLIC_DIR / path.lstrip('/')
        self._send_file(fp) if fp.is_file() else self._send_file(PUBLIC_DIR / 'index.html')

    def do_POST(self):
        path = self.path.split('?')[0]
        data = self._read_body()
        if data is None:
            self._send_json({'error': 'Invalid JSON body'}, 400); return
        if path == '/api/reminders':
            self._create_reminder(data); return
        self._send_json({'error': 'Not found'}, 404)

    def _create_reminder(self, data):
        # Accept all event fields from the body (events are now dynamic)
        event_id   = data.get('eventId')
        email      = (data.get('email') or '').strip().lower()
        phone      = (data.get('phone') or '').strip()
        intervals  = data.get('intervals', [])

        if not event_id:
            self._send_json({'error': 'eventId is required'}, 400); return
        if not email and not phone:
            self._send_json({'error': 'Provide at least an email address or phone number'}, 400); return

        valid_intervals = {h for h in intervals if h in (2, 6, 24)}
        if not valid_intervals:
            self._send_json({'error': 'Select at least one reminder time (2h, 6h, or 24h)'}, 400); return

        if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            self._send_json({'error': 'Invalid email address'}, 400); return

        if phone:
            digits = re.sub(r'\D', '', phone)
            if len(digits) == 10: digits = '1' + digits
            if len(digits) != 11:
                self._send_json({'error': 'Phone must be a 10-digit US number'}, 400); return
            phone = '+' + digits

        # All event metadata comes from the POST body (no server-side lookup needed)
        event_dt_str = data.get('eventDatetime', '')
        try:
            event_dt = _parse_dt(event_dt_str).astimezone(timezone.utc)
            if event_dt < datetime.now(timezone.utc):
                self._send_json({'error': 'This event has already passed'}, 400); return
        except (ValueError, TypeError):
            pass

        reminder = {
            'id':            str(uuid.uuid4()),
            'eventId':       event_id,
            'eventName':     data.get('eventName', 'Event'),
            'eventDatetime': event_dt_str,
            'eventNextDate': data.get('eventNextDate', ''),
            'eventTime':     data.get('eventTime', ''),
            'eventVenue':    data.get('eventVenue', ''),
            'topic':         data.get('topic', ''),
            'email':         email or None,
            'phone':         phone or None,
            'intervals':     sorted(valid_intervals, reverse=True),
            'sentIntervals': [],
            'cancelled':     False,
            'createdAt':     datetime.now(timezone.utc).isoformat()
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

    def do_DELETE(self):
        path = self.path.split('?')[0]
        m = re.fullmatch(r'/api/reminders/([0-9a-f\-]+)', path)
        if not m:
            self._send_json({'error': 'Not found'}, 404); return
        rid = m.group(1)
        reminders = load_reminders()
        rec = next((r for r in reminders if r['id'] == rid), None)
        if not rec:
            self._send_json({'error': 'Reminder not found'}, 404); return
        rec['cancelled'] = True
        save_reminders(reminders)
        self._send_json({'message': 'Reminder cancelled'})

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    httpd = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'\n  Event Finder  →  http://localhost:{PORT}')
    print(f'  SerpAPI     : {"Live (key set)" if os.environ.get("SERPAPI_KEY") else "Sample data (dynamic by zip)"}')
    print(f'  Email       : {"Ready (" + os.environ.get("SMTP_USER","") + ")" if os.environ.get("SMTP_USER") else "Not configured"}')
    print(f'  SMS         : {"Ready" if os.environ.get("TWILIO_ACCOUNT_SID") else "Not configured"}')
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
