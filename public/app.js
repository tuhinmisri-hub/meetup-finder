'use strict';

const LS_KEY      = 'meetup_reminders_v1';
const LS_RSVP_KEY = 'meetup_rsvps_v1';

// ── App state ─────────────────────────────────────────────────────────────────
let allMeetups   = [];
let allTopics    = {};    // { id: {label, icon, color} }
let activeFilter = 'all';
let activeSort   = 'date';
let currentLoc   = null; // { lat, lng, city, state, zip }
let map, centerMarker, radiusCircle;
let markers = [];

// ── Modal state ───────────────────────────────────────────────────────────────
let modalMeetup = null;

// ══════════════════════════════════════════════════════════════════════════════
// Boot
// ══════════════════════════════════════════════════════════════════════════════
async function boot() {
    initMap();
    await loadTopics();

    // Wire up search controls
    document.getElementById('btn-search').addEventListener('click', doSearch);
    document.getElementById('zip-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') doSearch();
    });
    document.getElementById('btn-locate').addEventListener('click', useMyLocation);
    document.getElementById('btn-refresh').addEventListener('click', doSearch);
    document.getElementById('sort-select').addEventListener('change', e => {
        activeSort = e.target.value; renderAll();
    });

    scheduleAutoRefresh();
    await checkAuthStatus();
    handleAuthCallback();

    // Token modal close
    const closeTokenModal = () => {
        document.getElementById('token-modal').classList.add('hidden');
        document.body.style.overflow = '';
    };
    document.getElementById('token-modal-close')?.addEventListener('click', closeTokenModal);
    document.getElementById('token-modal-done')?.addEventListener('click', closeTokenModal);

    // Modal controls
    document.getElementById('modal-close').addEventListener('click', closeModal);
    document.getElementById('btn-modal-cancel').addEventListener('click', closeModal);
    document.getElementById('btn-success-done').addEventListener('click', closeModal);
    document.getElementById('btn-manage-close').addEventListener('click', closeModal);
    document.getElementById('btn-cancel-reminder').addEventListener('click', cancelReminder);
    document.getElementById('btn-modal-submit').addEventListener('click', submitReminder);
    document.getElementById('reminder-modal').addEventListener('click', e => {
        if (e.target === document.getElementById('reminder-modal')) closeModal();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
}

// ══════════════════════════════════════════════════════════════════════════════
// Topics
// ══════════════════════════════════════════════════════════════════════════════
async function loadTopics() {
    try {
        const res  = await fetch('/api/topics');
        const data = await res.json();
        data.topics.forEach(t => { allTopics[t.id] = t; });
        renderTopicCheckboxes();
    } catch (e) {
        console.error('Failed to load topics', e);
        document.getElementById('topic-checks').innerHTML =
            '<span style="color:rgba(255,255,255,.5);font-size:.82rem">Topics unavailable</span>';
    }
}

function renderTopicCheckboxes() {
    const wrap = document.getElementById('topic-checks');
    wrap.innerHTML = '';
    // Default selections
    const defaults = new Set(['tennis', 'science', 'hiking', 'technology']);
    Object.entries(allTopics).forEach(([id, t]) => {
        const lbl = document.createElement('label');
        lbl.className = 'topic-check-label';
        lbl.innerHTML = `
            <input type="checkbox" name="topic" value="${id}" ${defaults.has(id) ? 'checked' : ''}>
            <span class="topic-chip" style="--tc:${t.color}">
                <i class="fas ${t.icon}"></i> ${t.label}
            </span>`;
        wrap.appendChild(lbl);
    });
}

function getSelectedTopics() {
    return Array.from(document.querySelectorAll('input[name="topic"]:checked'))
                .map(cb => cb.value);
}

// ══════════════════════════════════════════════════════════════════════════════
// Search & geocoding
// ══════════════════════════════════════════════════════════════════════════════
async function doSearch() {
    const zip    = document.getElementById('zip-input').value.trim();
    const radius = parseFloat(document.getElementById('radius-select').value);
    const topics = getSelectedTopics();

    if (!currentLoc && !zip) {
        alert('Enter a zip code or use your location first.'); return;
    }
    if (!topics.length) {
        alert('Select at least one topic.'); return;
    }

    showResultsArea(true);

    // If a new zip was typed, geocode it
    if (zip && (!currentLoc || currentLoc.zip !== zip)) {
        if (!/^\d{5}$/.test(zip)) {
            setErrorState('Enter a valid 5-digit zip code.'); return;
        }
        setSearchLoading(true, 'Looking up zip code…');
        try {
            const res = await fetch(`/api/geocode?zip=${zip}`);
            const loc = await res.json();
            if (!res.ok) { setErrorState(loc.error || 'Zip code not found.'); return; }
            currentLoc = loc;
        } catch (e) {
            setErrorState('Failed to look up zip code. Check your connection.'); return;
        }
    }

    await fetchAndRender(radius, topics);
}

async function useMyLocation() {
    if (!navigator.geolocation) {
        alert('Geolocation is not supported by your browser.'); return;
    }
    const btn = document.getElementById('btn-locate');
    const lbl = document.getElementById('locate-label');
    btn.disabled = true;
    lbl.textContent = 'Detecting…';

    navigator.geolocation.getCurrentPosition(
        async pos => {
            const { latitude: lat, longitude: lng } = pos.coords;
            try {
                const res = await fetch(`/api/reverse-geocode?lat=${lat}&lng=${lng}`);
                const loc = await res.json();
                currentLoc = { ...loc, lat, lng };
            } catch (_) {
                currentLoc = { lat, lng, city: 'Your location', state: '', zip: '' };
            }

            if (currentLoc.zip) {
                document.getElementById('zip-input').value = currentLoc.zip;
            }
            setLocationChip(currentLoc);
            btn.disabled = false;
            lbl.textContent = 'Use my location';

            const topics = getSelectedTopics();
            const radius = parseFloat(document.getElementById('radius-select').value);
            if (topics.length) {
                showResultsArea(true);
                await fetchAndRender(radius, topics);
            }
        },
        err => {
            btn.disabled = false;
            lbl.textContent = 'Use my location';
            alert('Could not get your location. Please enter a zip code manually.');
        },
        { timeout: 10000 }
    );
}

async function fetchAndRender(radius, topics) {
    if (!currentLoc) return;
    setLoadingState(true);

    const params = new URLSearchParams({
        zip:    currentLoc.zip || '',
        lat:    currentLoc.lat,
        lng:    currentLoc.lng,
        radius: radius,
        topics: topics.join(','),
    });

    try {
        const res  = await fetch(`/api/meetups?${params}`);
        if (!res.ok) { const d = await res.json(); setErrorState(d.error || `Error ${res.status}`); return; }
        const data = await res.json();
        allMeetups  = data.meetups || [];
        currentLoc  = data.location || currentLoc;
        activeFilter = 'all';

        renderSourceBadge(data.source, data.fetchedAt);
        setLocationChip(currentLoc);
        updateStatRadius(radius);
        renderFilterTabs(topics);
        renderBannerLinks(topics, currentLoc);
        renderAll();
        updateMapCenter(currentLoc, radius);
        document.getElementById('btn-refresh').disabled = false;
        setLoadingState(false);
    } catch (err) {
        setErrorState(err.message);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Rendering
// ══════════════════════════════════════════════════════════════════════════════
function renderAll() {
    const list = sortedFiltered();
    renderCards(list);
    renderMap(list);
    updateCounts();
}

function sortedFiltered() {
    const base = activeFilter === 'all'
        ? allMeetups
        : allMeetups.filter(m => m.topic === activeFilter);
    return [...base].sort((a, b) => {
        if (activeSort === 'date')      return new Date(a.eventDatetime) - new Date(b.eventDatetime);
        if (activeSort === 'distance')  return a.distanceMi - b.distanceMi;
        if (activeSort === 'members')   return b.members - a.members;
        if (activeSort === 'attending') return b.attending - a.attending;
        if (activeSort === 'name')      return a.name.localeCompare(b.name);
        return 0;
    });
}

function renderCards(list) {
    const container = document.getElementById('cards');
    container.innerHTML = '';
    if (!list.length) {
        container.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:2rem">No events found for this filter.</p>';
        document.getElementById('stat-events').textContent  = 0;
        document.getElementById('stat-members').textContent = 0;
        return;
    }

    list.forEach(m => {
        const color     = m.color || allTopics[m.topic]?.color || '#64748b';
        const icon      = allTopics[m.topic]?.icon || 'fa-calendar';
        const active    = !!getActiveReminder(m.id);
        const going     = getRsvp(m.id);

        const card = document.createElement('div');
        card.className = 'meetup-card';
        card.dataset.id = m.id;

        const nextLabel = m.nextDate
            ? `<span class="next-chip"><i class="fas fa-clock" style="font-size:.62rem"></i> ${m.nextDate}</span>` : '';
        const timeRow = m.time
            ? `<div class="meta-row"><i class="fas fa-clock"></i>${escHtml(m.schedule)} &middot; ${escHtml(m.time)}</div>`
            : `<div class="meta-row"><i class="fas fa-calendar-days"></i>${escHtml(m.schedule)}</div>`;

        card.innerHTML = `
            <div class="card-top">
                <div>
                    <div class="card-title">${escHtml(m.name)}</div>
                    ${nextLabel}
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:.3rem;flex-shrink:0">
                    <span class="topic-pill" style="--tc:${color}">
                        <i class="fas ${icon}"></i> ${cap(m.topic)}
                    </span>
                    <span class="going-badge${going ? '' : ' hidden'}">
                        <i class="fas fa-circle-check"></i> Going
                    </span>
                </div>
            </div>
            <div class="card-meta">
                ${timeRow}
                <div class="meta-row"><i class="fas fa-location-dot"></i>${escHtml(m.venue)}</div>
                <div class="meta-row"><i class="fas fa-map-pin"></i>${escHtml(m.address)}</div>
            </div>
            <p class="desc-text">${escHtml(m.description || '')}</p>
            <div class="card-footer">
                <div class="members-row">
                    <i class="fas fa-users"></i> ${m.members} members
                    &nbsp;·&nbsp;
                    <i class="fas fa-circle-check" style="color:#10b981"></i>
                    <span class="attending-count" data-base="${m.attending}">${going ? m.attending + 1 : m.attending}</span> attending
                </div>
                <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
                    <span class="dist-pill"><i class="fas fa-route"></i> ${m.distanceMi} mi</span>
                    <button class="btn-remind${active ? ' bell-active' : ''}" data-remind="${m.id}">
                        <i class="fas fa-bell"></i>
                        ${active ? 'Reminder Set' : 'Remind Me'}
                    </button>
                    <button class="btn-rsvp${going ? ' rsvp-active' : ''}" data-rsvp="${m.id}">
                        ${going
                            ? '<i class="fas fa-circle-check"></i> Going'
                            : '<i class="far fa-circle-check"></i> Going?'}
                    </button>
                    <a href="${escHtml(m.meetupUrl)}" target="_blank" rel="noopener"
                       class="view-link" style="--tc:${color}"
                       onclick="event.stopPropagation()">
                        Sign Up <i class="fas fa-arrow-up-right-from-square" style="font-size:.65em"></i>
                    </a>
                </div>
            </div>`;

        card.addEventListener('click', e => {
            if (e.target.closest('.btn-remind') || e.target.closest('.btn-rsvp') || e.target.closest('.view-link')) return;
            highlightCard(m.id); panToMeetup(m);
        });
        card.querySelector('.btn-remind').addEventListener('click', e => {
            e.stopPropagation(); openReminderModal(m);
        });
        card.querySelector('.btn-rsvp').addEventListener('click', e => {
            e.stopPropagation(); toggleRsvp(m);
        });
        container.appendChild(card);
    });

    const totalMembers = list.reduce((s, m) => s + (m.members || 0), 0);
    document.getElementById('stat-events').textContent  = list.length;
    document.getElementById('stat-members').textContent = totalMembers.toLocaleString();
}

function renderFilterTabs(selectedTopics) {
    const wrap = document.getElementById('filter-tabs');
    wrap.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.className = 'ftab active';
    allBtn.dataset.topic = 'all';
    allBtn.style.setProperty('--tc', '#1e293b');
    allBtn.innerHTML = `<i class="fas fa-border-all"></i> All <span class="ftab-count" id="cnt-all">—</span>`;
    wrap.appendChild(allBtn);

    selectedTopics.forEach(tid => {
        const t = allTopics[tid]; if (!t) return;
        const btn = document.createElement('button');
        btn.className = 'ftab';
        btn.dataset.topic = tid;
        btn.innerHTML = `<i class="fas ${t.icon}"></i> ${t.label} <span class="ftab-count" id="cnt-${tid}">—</span>`;
        wrap.appendChild(btn);
    });

    wrap.addEventListener('click', e => {
        const btn = e.target.closest('.ftab'); if (!btn) return;
        wrap.querySelectorAll('.ftab').forEach(b => {
            b.classList.remove('active');
            b.style.removeProperty('background');
            b.style.removeProperty('border-color');
        });
        btn.classList.add('active');
        const tid = btn.dataset.topic;
        if (tid === 'all') {
            btn.style.background = '#1e293b'; btn.style.borderColor = '#1e293b';
        } else {
            const color = allTopics[tid]?.color || '#3b82f6';
            btn.style.background = color; btn.style.borderColor = color;
        }
        activeFilter = tid; renderAll();
    });
}

function renderBannerLinks(topics, loc) {
    const city  = loc ? `${loc.city}${loc.state ? ', ' + loc.state : ''}` : 'your area';
    const wrap  = document.getElementById('banner-links');
    document.getElementById('banner-location-label').textContent = `Near ${city}`;
    wrap.innerHTML = topics.slice(0, 4).map(tid => {
        const t = allTopics[tid]; if (!t) return '';
        const q = encodeURIComponent(t.label);
        const l = encodeURIComponent(loc?.city || '') + (loc?.state ? '%2C+' + encodeURIComponent(loc.state) : '');
        return `<a href="https://www.meetup.com/find/?keywords=${q}&location=${l}&source=EVENTS"
                   target="_blank" rel="noopener" class="banner-btn">
                    <i class="fas ${t.icon}"></i> ${t.label}
                </a>`;
    }).join('');
}

function updateCounts() {
    document.getElementById('cnt-all').textContent = allMeetups.length;
    document.querySelectorAll('.ftab[data-topic]').forEach(btn => {
        const tid = btn.dataset.topic;
        if (tid === 'all') return;
        const el = document.getElementById(`cnt-${tid}`);
        if (el) el.textContent = allMeetups.filter(m => m.topic === tid).length;
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Map
// ══════════════════════════════════════════════════════════════════════════════
function initMap() {
    map = L.map('map', { zoomControl: true }).setView([39.5, -98.35], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(map);
}

function updateMapCenter(loc, radiusMi) {
    map.invalidateSize();
    if (centerMarker) { map.removeLayer(centerMarker); centerMarker = null; }
    if (radiusCircle) { map.removeLayer(radiusCircle); radiusCircle = null; }

    const latlng = [loc.lat, loc.lng];
    const label  = loc.city ? `${loc.city}${loc.state ? ', ' + loc.state : ''}` : 'Search center';

    radiusCircle = L.circle(latlng, {
        radius: radiusMi * 1609.34, color: '#3b82f6', weight: 1.5,
        fillColor: '#3b82f6', fillOpacity: .05, dashArray: '6 4'
    }).addTo(map);

    centerMarker = L.marker(latlng, { icon: makeIcon('#dc2626') }).addTo(map)
        .bindPopup(`<strong>${escHtml(label)}</strong><br>Search center`);

    map.setView(latlng, 12, { animate: true });
}

function renderMap(list) {
    markers.forEach(m => map.removeLayer(m));
    markers = [];

    // Update legend
    const legend = document.getElementById('map-legend');
    const seenTopics = [...new Set(list.map(m => m.topic))];
    legend.innerHTML = '<div class="leg-row"><span class="ldot red"></span> You</div>';
    seenTopics.forEach(tid => {
        const color = allTopics[tid]?.color || '#64748b';
        const label = allTopics[tid]?.label || cap(tid);
        legend.innerHTML += `<div class="leg-row"><span class="ldot" style="background:${color}"></span> ${label}</div>`;
    });

    list.forEach(m => {
        const color  = m.color || allTopics[m.topic]?.color || '#64748b';
        const marker = L.marker([m.lat, m.lng], { icon: makeIcon(color) })
            .addTo(map)
            .bindPopup(`
                <strong>${escHtml(m.name)}</strong><br>
                <span style="color:#64748b;font-size:.82em">${escHtml(m.venue)}</span><br>
                <span style="font-size:.78em">${escHtml(m.schedule)}${m.time ? ' · ' + m.time : ''}</span><br>
                <span style="font-size:.78em">📍 ${m.distanceMi} mi away</span>
            `);
        marker.on('click', () => highlightCard(m.id));
        marker._meetupId = m.id;
        markers.push(marker);
    });
}

function panToMeetup(m) {
    map.setView([m.lat, m.lng], 14, { animate: true });
    const mk = markers.find(x => x._meetupId === m.id);
    if (mk) mk.openPopup();
}

function makeIcon(color) {
    return L.divIcon({
        className: '',
        html: `<div style="width:16px;height:16px;background:${color};border:2.5px solid #fff;border-radius:50%;box-shadow:0 1px 5px rgba(0,0,0,.4)"></div>`,
        iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -10]
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Reminder Modal
// ══════════════════════════════════════════════════════════════════════════════
// ── RSVP (Going) ──────────────────────────────────────────────────────────────
function getRsvp(eventId) {
    try { return !!JSON.parse(localStorage.getItem(LS_RSVP_KEY) || '{}')[eventId]; }
    catch { return false; }
}
function setRsvp(eventId, going) {
    const s = JSON.parse(localStorage.getItem(LS_RSVP_KEY) || '{}');
    if (going) s[eventId] = true; else delete s[eventId];
    localStorage.setItem(LS_RSVP_KEY, JSON.stringify(s));
}

function toggleRsvp(meetup) {
    const going = !getRsvp(meetup.id);
    setRsvp(meetup.id, going);
    updateCardRsvp(meetup.id, going, meetup.attending);
}

function updateCardRsvp(eventId, going, baseAttending) {
    const card = document.querySelector(`.meetup-card[data-id="${eventId}"]`);
    if (!card) return;

    const btn = card.querySelector('.btn-rsvp');
    if (btn) {
        btn.classList.toggle('rsvp-active', going);
        btn.innerHTML = going
            ? '<i class="fas fa-circle-check"></i> Going'
            : '<i class="far fa-circle-check"></i> Going?';
    }

    // Update attending count optimistically
    const attendEl = card.querySelector('.attending-count');
    if (attendEl) {
        const delta = going ? 1 : -1;
        const current = parseInt(attendEl.dataset.base || baseAttending);
        attendEl.dataset.base = current;
        attendEl.textContent  = (current + delta).toString();
    }

    // Show/hide the Going badge in card header
    const badge = card.querySelector('.going-badge');
    if (badge) badge.classList.toggle('hidden', !going);
}

// ── Reminder localStorage ─────────────────────────────────────────────────────
function getActiveReminder(eventId) {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}')[eventId] || null; }
    catch { return null; }
}
function saveActiveReminder(eventId, data) {
    const s = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    s[eventId] = data; localStorage.setItem(LS_KEY, JSON.stringify(s));
}
function removeActiveReminder(eventId) {
    const s = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    delete s[eventId]; localStorage.setItem(LS_KEY, JSON.stringify(s));
}

function openReminderModal(meetup) {
    modalMeetup = meetup;
    document.getElementById('modal-event-name').textContent  = meetup.name;
    document.getElementById('modal-event-meta').textContent  =
        [meetup.nextDate, meetup.time].filter(Boolean).join(' · ');
    document.getElementById('modal-event-venue').textContent = meetup.venue;

    const color = meetup.color || allTopics[meetup.topic]?.color || '#3b82f6';
    const bellWrap = document.getElementById('modal-bell-icon');
    bellWrap.style.background = color + '22';
    bellWrap.style.color      = color;

    const existing = getActiveReminder(meetup.id);
    existing ? showPanelManage(existing) : showPanelForm();

    document.getElementById('reminder-modal').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('reminder-modal').classList.add('hidden');
    document.body.style.overflow = '';
    modalMeetup = null;
    resetForm();
}

function showPanelForm() {
    document.getElementById('panel-form').classList.remove('hidden');
    document.getElementById('panel-success').classList.add('hidden');
    document.getElementById('panel-manage').classList.add('hidden');
}
function showPanelSuccess(message, channels) {
    document.getElementById('panel-form').classList.add('hidden');
    document.getElementById('panel-success').classList.remove('hidden');
    document.getElementById('panel-manage').classList.add('hidden');
    document.getElementById('success-msg').textContent = message;
    document.getElementById('success-channels').innerHTML = channels.map(c =>
        `<span><i class="fas ${c.icon}" style="margin-right:.3rem"></i>${escHtml(c.text)}</span>`
    ).join('');
}
function showPanelManage(reminder) {
    document.getElementById('panel-form').classList.add('hidden');
    document.getElementById('panel-success').classList.add('hidden');
    document.getElementById('panel-manage').classList.remove('hidden');
    const labels = (reminder.intervals || []).sort((a,b)=>b-a).map(h => `${h}h before`).join(', ');
    const rows = [`<div class="manage-row"><i class="fas fa-clock"></i><span>Reminders at: <strong>${labels}</strong></span></div>`];
    if (reminder.email) rows.push(`<div class="manage-row"><i class="fas fa-envelope"></i><span>${escHtml(reminder.email)}</span></div>`);
    if (reminder.phone) rows.push(`<div class="manage-row"><i class="fas fa-mobile-screen-button"></i><span>${escHtml(reminder.phone)}</span></div>`);
    document.getElementById('manage-details').innerHTML = rows.join('');
    const btn = document.getElementById('btn-cancel-reminder');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-bell-slash"></i> Cancel Reminder';
}

async function submitReminder() {
    const email     = document.getElementById('input-email').value.trim();
    const phone     = document.getElementById('input-phone').value.trim();
    const intervals = Array.from(document.querySelectorAll('input[name="interval"]:checked'))
                          .map(cb => parseInt(cb.value));

    if (!email && !phone) { showFormError('Enter an email address or phone number (or both).'); return; }
    if (!intervals.length) { showFormError('Select at least one reminder time.'); return; }

    const btn = document.getElementById('btn-modal-submit');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Setting…';
    hideFormError();

    try {
        const res  = await fetch('/api/reminders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                eventId:       modalMeetup.id,
                eventName:     modalMeetup.name,
                eventDatetime: modalMeetup.eventDatetime,
                eventNextDate: modalMeetup.nextDate,
                eventTime:     modalMeetup.time,
                eventVenue:    modalMeetup.venue,
                topic:         modalMeetup.topic,
                email, phone, intervals,
            })
        });
        const data = await res.json();
        if (!res.ok) {
            showFormError(data.error || 'Failed to set reminder.');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-bell"></i> Set Reminder';
            return;
        }
        saveActiveReminder(modalMeetup.id, { id: data.id, intervals, email: email||null, phone: phone||null });
        updateCardBell(modalMeetup.id, true);
        const channels = [];
        if (email) channels.push({ icon: 'fa-envelope', text: email });
        if (phone) channels.push({ icon: 'fa-mobile-screen-button', text: phone });
        showPanelSuccess(data.message, channels);
    } catch (err) {
        showFormError('Network error — is the server running?');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-bell"></i> Set Reminder';
    }
}

async function cancelReminder() {
    const existing = getActiveReminder(modalMeetup.id);
    if (!existing) return;
    const btn = document.getElementById('btn-cancel-reminder');
    btn.disabled = true; btn.textContent = 'Cancelling…';
    try { await fetch(`/api/reminders/${existing.id}`, { method: 'DELETE' }); } catch (_) {}
    removeActiveReminder(modalMeetup.id);
    updateCardBell(modalMeetup.id, false);
    closeModal();
}

function updateCardBell(eventId, active) {
    const card = document.querySelector(`.meetup-card[data-id="${eventId}"]`);
    if (!card) return;
    const btn = card.querySelector('.btn-remind');
    if (!btn) return;
    btn.classList.toggle('bell-active', active);
    btn.innerHTML = `<i class="fas fa-bell"></i> ${active ? 'Reminder Set' : 'Remind Me'}`;
}

function showFormError(msg) {
    const el = document.getElementById('form-error');
    el.textContent = msg; el.classList.remove('hidden');
}
function hideFormError() { document.getElementById('form-error').classList.add('hidden'); }
function resetForm() {
    document.getElementById('input-email').value = '';
    document.getElementById('input-phone').value = '';
    document.querySelectorAll('input[name="interval"]').forEach(cb => { cb.checked = true; });
    hideFormError();
    const btn = document.getElementById('btn-modal-submit');
    btn.disabled = false; btn.innerHTML = '<i class="fas fa-bell"></i> Set Reminder';
    showPanelForm();
}

// ══════════════════════════════════════════════════════════════════════════════
// UI helpers
// ══════════════════════════════════════════════════════════════════════════════
function highlightCard(id) {
    document.querySelectorAll('.meetup-card').forEach(c => c.classList.remove('highlighted'));
    const card = document.querySelector(`.meetup-card[data-id="${id}"]`);
    if (card) { card.classList.add('highlighted'); card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
}

function renderSourceBadge(source, fetchedAt) {
    const badge = document.getElementById('source-badge');
    badge.className = `source-badge source-${source === 'live' ? 'live' : 'sample'}`;
    badge.innerHTML = source === 'live'
        ? '<i class="fas fa-circle" style="font-size:.55rem"></i> Live data'
        : '<i class="fas fa-database" style="font-size:.7rem"></i> Sample data';
    if (fetchedAt) {
        const d = new Date(fetchedAt);
        document.getElementById('fetched-at').textContent =
            `Updated ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    }
}

function setLocationChip(loc) {
    if (!loc || !loc.city) return;
    const chip = document.getElementById('location-chip');
    chip.innerHTML = `<i class="fas fa-location-dot"></i> ${escHtml(loc.city)}${loc.state ? ', ' + escHtml(loc.state) : ''}${loc.zip ? ' · ' + loc.zip : ''}`;
    chip.classList.remove('hidden');
}

function updateStatRadius(r) {
    document.getElementById('stat-radius').textContent = `${r} mi`;
}

function showResultsArea(show) {
    document.getElementById('prompt-state').classList.toggle('hidden', show);
    document.getElementById('results-wrap').classList.toggle('hidden', !show);
    if (show) {
        document.getElementById('loading-state').classList.remove('hidden');
        document.getElementById('error-state').classList.add('hidden');
        document.getElementById('cards').innerHTML = '';
        // Let the DOM repaint before telling Leaflet its container is now visible
        setTimeout(() => map && map.invalidateSize(), 0);
    }
}

function setSearchLoading(loading, msg) {
    if (loading) {
        showResultsArea(true);
        document.getElementById('loading-state').classList.remove('hidden');
        document.getElementById('loading-state').querySelector('p').textContent = msg || 'Loading…';
    }
}

function setLoadingState(loading) {
    document.getElementById('loading-state').classList.toggle('hidden', !loading);
    document.getElementById('error-state').classList.add('hidden');
    const btn = document.getElementById('btn-refresh');
    if (!loading) btn.disabled = false;
    btn.querySelector('i').classList.toggle('fa-spin', loading);
}

function setErrorState(msg) {
    document.getElementById('loading-state').classList.add('hidden');
    document.getElementById('error-state').classList.remove('hidden');
    document.getElementById('error-msg').textContent = msg || 'Could not load meetups.';
    document.getElementById('btn-refresh').disabled = false;
}

function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ══════════════════════════════════════════════════════════════════════════════
// Auto-refresh at 9 AM ET daily
// ══════════════════════════════════════════════════════════════════════════════
function msUntilNext9amET() {
    const fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
    const parts = fmt.formatToParts(new Date());
    const h = parseInt(parts.find(p => p.type === 'hour').value);
    const m = parseInt(parts.find(p => p.type === 'minute').value);
    const s = parseInt(parts.find(p => p.type === 'second').value);
    const secNow = h * 3600 + m * 60 + s;
    const sec9am = 9 * 3600;
    const secsUntil = secNow < sec9am ? sec9am - secNow : 86400 - secNow + sec9am;
    return secsUntil * 1000;
}

function scheduleAutoRefresh() {
    const ms   = msUntilNext9amET();
    const next = new Date(Date.now() + ms);
    const el   = document.getElementById('next-refresh-time');
    if (el) el.textContent = next.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
    document.getElementById('stat-refresh-wrap').style.display = '';

    setTimeout(() => {
        if (currentLoc) {
            doSearch();
            showAutoRefreshToast();
        }
        scheduleAutoRefresh();
    }, ms);
}

function showAutoRefreshToast() {
    const t = document.createElement('div');
    t.className = 'auto-refresh-toast';
    t.innerHTML = '<i class="fas fa-rotate-right"></i> Results refreshed — showing next 7 days';
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 3500);
}

// ══════════════════════════════════════════════════════════════════════════════
// Meetup.com auth
// ══════════════════════════════════════════════════════════════════════════════
async function checkAuthStatus() {
    try {
        const res  = await fetch('/api/auth/status');
        const data = await res.json();
        renderAuthStat(data);
        return data;
    } catch (_) { return {}; }
}

function renderAuthStat({ connected, configured }) {
    const el = document.getElementById('stat-meetup-auth');
    if (!el) return;
    if (connected) {
        el.innerHTML = `
            <i class="fas fa-circle" style="color:#10b981;font-size:.55rem"></i>
            <span style="color:#065f46;font-weight:700;font-size:.82rem">Meetup.com Live</span>
            <a href="/auth/disconnect" class="auth-disconnect" title="Disconnect"
               onclick="return confirm('Disconnect Meetup.com?')">
                <i class="fas fa-xmark"></i>
            </a>`;
    } else if (configured) {
        el.innerHTML = `<a href="/auth/meetup" class="btn-connect-meetup">
            <i class="fas fa-plug"></i> Connect Meetup.com
        </a>`;
    }
}

function handleAuthCallback() {
    const sp     = new URLSearchParams(window.location.search);
    const result = sp.get('auth');
    if (!result) return;

    // Remove ?auth=... from URL without reloading
    const clean = window.location.pathname;
    window.history.replaceState({}, '', clean);

    if (result === 'success') {
        // Show post-connect modal with refresh token
        fetch('/api/auth/status').then(r => r.json()).then(data => {
            const cid     = document.getElementById('tv-cid');
            const refresh = document.getElementById('tv-refresh');
            if (cid)     cid.textContent     = '(set in Render dashboard)';
            if (refresh) refresh.textContent = data.refreshToken || '(unavailable)';

            document.getElementById('btn-copy-refresh')?.addEventListener('click', () => {
                navigator.clipboard.writeText(data.refreshToken || '');
                document.getElementById('btn-copy-refresh').innerHTML = '<i class="fas fa-check"></i>';
                setTimeout(() => {
                    document.getElementById('btn-copy-refresh').innerHTML = '<i class="fas fa-copy"></i>';
                }, 2000);
            });

            document.getElementById('token-modal').classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        });
        renderAuthBanner('success', 'Connected to Meetup.com — live events are now active.');
    } else if (result === 'denied') {
        renderAuthBanner('warn', 'Meetup.com authorization was cancelled.');
    } else {
        renderAuthBanner('error', 'Could not connect to Meetup.com. Check your Client ID and Secret.');
    }
}

function renderAuthBanner(type, msg) {
    const el = document.getElementById('auth-banner');
    if (!el) return;
    const colors = { success: '#d1fae5:#065f46', warn: '#fef9c3:#854d0e', error: '#fef2f2:#dc2626' };
    const [bg, fg] = (colors[type] || colors.warn).split(':');
    const icon = type === 'success' ? 'fa-circle-check' : type === 'warn' ? 'fa-triangle-exclamation' : 'fa-circle-xmark';
    el.style.cssText = `background:${bg};color:${fg}`;
    el.innerHTML = `<i class="fas ${icon}"></i> ${msg}
        <button onclick="this.parentElement.classList.add('hidden')" style="background:none;border:none;cursor:pointer;color:inherit;margin-left:.5rem;font-size:1rem">&times;</button>`;
    el.classList.remove('hidden');
    if (type === 'success') setTimeout(() => el.classList.add('hidden'), 8000);
}

// ── Start ──────────────────────────────────────────────────────────────────
boot();
