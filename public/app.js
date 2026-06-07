'use strict';

const API_BASE  = '';
const CENTER    = [47.5301, -122.0326];
const RADIUS_MI = 5;
const LS_KEY    = 'meetup_reminders_v1';

// ── App state ─────────────────────────────────────────────────────────────────
let allMeetups   = [];
let activeFilter = 'all';
let activeSort   = 'distance';
let map, markers = [];

// ── Modal state ───────────────────────────────────────────────────────────────
let modalMeetup = null;       // meetup object currently in modal

// ══════════════════════════════════════════════════════════════════════════════
// API
// ══════════════════════════════════════════════════════════════════════════════
async function loadMeetups() {
    setLoadingState(true);
    try {
        const url = `${API_BASE}/api/meetups?topics=tennis,science&lat=${CENTER[0]}&lng=${CENTER[1]}&radius=${RADIUS_MI}`;
        const res  = await fetch(url);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const json = await res.json();
        allMeetups = json.meetups || [];
        renderSourceBadge(json.source, json.fetchedAt);
        renderAll();
        setLoadingState(false);
    } catch (err) {
        console.error(err);
        setErrorState(err.message);
    }
}

async function loadStatus() {
    try {
        const res  = await fetch(`${API_BASE}/api/status`);
        const data = await res.json();
        console.info('[status]', data);
    } catch (_) {}
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
        if (activeSort === 'distance') return a.distanceMi - b.distanceMi;
        if (activeSort === 'members')  return b.members - a.members;
        if (activeSort === 'attending')return b.attending - a.attending;
        if (activeSort === 'name')     return a.name.localeCompare(b.name);
        return 0;
    });
}

function renderCards(list) {
    const container = document.getElementById('cards');
    container.innerHTML = '';

    if (!list.length) {
        container.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:2rem">No events found for this filter.</p>';
        return;
    }

    list.forEach(m => {
        const pillClass = m.topic === 'tennis' ? 'tennis-pill' : 'science-pill';
        const linkClass = m.topic === 'tennis' ? 'tennis-link' : 'science-link';
        const icon      = m.topic === 'tennis' ? 'fa-table-tennis-paddle-ball' : 'fa-flask';
        const active    = !!getActiveReminder(m.id);

        const card = document.createElement('div');
        card.className = 'meetup-card';
        card.dataset.id = m.id;

        const nextLabel = m.nextDate
            ? `<span class="next-chip"><i class="fas fa-clock" style="font-size:.62rem"></i> ${m.nextDate}</span>`
            : '';
        const timeRow = m.time
            ? `<div class="meta-row"><i class="fas fa-clock"></i>${m.schedule} &middot; ${m.time}</div>`
            : `<div class="meta-row"><i class="fas fa-calendar-days"></i>${m.schedule}</div>`;

        card.innerHTML = `
            <div class="card-top">
                <div>
                    <div class="card-title">${escHtml(m.name)}</div>
                    ${nextLabel}
                </div>
                <span class="topic-pill ${pillClass}">
                    <i class="fas ${icon}"></i> ${cap(m.topic)}
                </span>
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
                    <i class="fas fa-circle-check" style="color:#10b981"></i> ${m.attending} attending
                </div>
                <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
                    <span class="dist-pill"><i class="fas fa-route"></i> ${m.distanceMi} mi</span>
                    <button class="btn-remind${active ? ' bell-active' : ''}" data-remind="${m.id}">
                        <i class="fas fa-bell"></i>
                        ${active ? 'Reminder Set' : 'Remind Me'}
                    </button>
                    <a href="${m.meetupUrl}" target="_blank" rel="noopener"
                       class="view-link ${linkClass}"
                       onclick="event.stopPropagation()">
                        Meetup.com <i class="fas fa-arrow-up-right-from-square" style="font-size:.65em"></i>
                    </a>
                </div>
            </div>
        `;

        // card click → pan map
        card.addEventListener('click', e => {
            if (e.target.closest('.btn-remind') || e.target.closest('.view-link')) return;
            highlightCard(m.id);
            panToMeetup(m);
        });

        // remind-me button click
        card.querySelector('.btn-remind').addEventListener('click', e => {
            e.stopPropagation();
            openReminderModal(m);
        });

        container.appendChild(card);
    });

    // update stats
    const totalMembers = list.reduce((s, m) => s + (m.members || 0), 0);
    document.getElementById('stat-events').textContent  = list.length;
    document.getElementById('stat-members').textContent = totalMembers.toLocaleString();
}

// ══════════════════════════════════════════════════════════════════════════════
// Map
// ══════════════════════════════════════════════════════════════════════════════
function initMap() {
    map = L.map('map', { zoomControl: true }).setView(CENTER, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(map);
    L.circle(CENTER, {
        radius: RADIUS_MI * 1609.34, color: '#3b82f6', weight: 1.5,
        fillColor: '#3b82f6', fillOpacity: .05, dashArray: '6 4'
    }).addTo(map);
    L.marker(CENTER, { icon: makeIcon('#dc2626') }).addTo(map)
        .bindPopup('<strong>Issaquah, WA</strong><br>Search center');
}

function renderMap(list) {
    markers.forEach(m => map.removeLayer(m));
    markers = [];
    list.forEach(m => {
        const color  = m.topic === 'tennis' ? '#16a34a' : '#2563eb';
        const marker = L.marker([m.lat, m.lng], { icon: makeIcon(color) })
            .addTo(map)
            .bindPopup(`
                <strong>${escHtml(m.name)}</strong><br>
                <span style="color:#64748b;font-size:.82em">${escHtml(m.venue)}</span><br>
                <span style="font-size:.78em">${m.schedule}${m.time ? ' · ' + m.time : ''}</span><br>
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

// ── localStorage helpers ──────────────────────────────────────────────────────
function getActiveReminder(eventId) {
    try {
        const stored = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
        return stored[eventId] || null;
    } catch { return null; }
}

function saveActiveReminder(eventId, data) {
    const stored = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    stored[eventId] = data;
    localStorage.setItem(LS_KEY, JSON.stringify(stored));
}

function removeActiveReminder(eventId) {
    const stored = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    delete stored[eventId];
    localStorage.setItem(LS_KEY, JSON.stringify(stored));
}

// ── Open / close ──────────────────────────────────────────────────────────────
function openReminderModal(meetup) {
    modalMeetup = meetup;

    // populate header
    document.getElementById('modal-event-name').textContent = meetup.name;
    document.getElementById('modal-event-meta').textContent =
        [meetup.nextDate, meetup.time].filter(Boolean).join(' · ');
    document.getElementById('modal-event-venue').textContent = meetup.venue;

    // topic colour on bell
    const bellWrap = document.getElementById('modal-bell-icon');
    bellWrap.style.background = meetup.topic === 'tennis' ? '#dcfce7' : '#dbeafe';
    bellWrap.style.color      = meetup.topic === 'tennis' ? '#16a34a' : '#2563eb';

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

// ── Panel switching ───────────────────────────────────────────────────────────
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

    const ch = document.getElementById('success-channels');
    ch.innerHTML = channels.map(c =>
        `<span><i class="fas ${c.icon}" style="margin-right:.3rem"></i>${escHtml(c.text)}</span>`
    ).join('');
}

function showPanelManage(reminder) {
    document.getElementById('panel-form').classList.add('hidden');
    document.getElementById('panel-success').classList.add('hidden');
    document.getElementById('panel-manage').classList.remove('hidden');

    const labels = (reminder.intervals || []).sort((a,b)=>b-a)
        .map(h => `${h}h before`).join(', ');

    const rows = [`
        <div class="manage-row">
            <i class="fas fa-clock"></i>
            <span>Reminders at: <strong>${labels}</strong></span>
        </div>
    `];
    if (reminder.email)
        rows.push(`<div class="manage-row"><i class="fas fa-envelope"></i><span>${escHtml(reminder.email)}</span></div>`);
    if (reminder.phone)
        rows.push(`<div class="manage-row"><i class="fas fa-mobile-screen-button"></i><span>${escHtml(reminder.phone)}</span></div>`);

    document.getElementById('manage-details').innerHTML = rows.join('');
    document.getElementById('btn-cancel-reminder').disabled = false;
    document.getElementById('btn-cancel-reminder').innerHTML =
        '<i class="fas fa-bell-slash"></i> Cancel Reminder';
}

// ── Submit ────────────────────────────────────────────────────────────────────
async function submitReminder() {
    const email     = document.getElementById('input-email').value.trim();
    const phone     = document.getElementById('input-phone').value.trim();
    const intervals = Array.from(
        document.querySelectorAll('input[name="interval"]:checked')
    ).map(cb => parseInt(cb.value));

    if (!email && !phone) {
        showFormError('Enter an email address or phone number (or both).'); return;
    }
    if (!intervals.length) {
        showFormError('Select at least one reminder time.'); return;
    }

    const btn = document.getElementById('btn-modal-submit');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Setting…';
    hideFormError();

    try {
        const res  = await fetch('/api/reminders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ eventId: modalMeetup.id, email, phone, intervals })
        });
        const data = await res.json();

        if (!res.ok) {
            showFormError(data.error || 'Failed to set reminder. Please try again.');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-bell"></i> Set Reminder';
            return;
        }

        // persist in localStorage
        saveActiveReminder(modalMeetup.id, { id: data.id, intervals, email: email||null, phone: phone||null });
        updateCardBell(modalMeetup.id, true);

        // build channel list for success panel
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

// ── Cancel reminder ───────────────────────────────────────────────────────────
async function cancelReminder() {
    const existing = getActiveReminder(modalMeetup.id);
    if (!existing) return;

    const btn = document.getElementById('btn-cancel-reminder');
    btn.disabled = true;
    btn.textContent = 'Cancelling…';

    try {
        await fetch(`/api/reminders/${existing.id}`, { method: 'DELETE' });
    } catch (_) { /* network error — still clear locally */ }

    removeActiveReminder(modalMeetup.id);
    updateCardBell(modalMeetup.id, false);
    closeModal();
}

// ── Card bell state ───────────────────────────────────────────────────────────
function updateCardBell(eventId, active) {
    const card = document.querySelector(`.meetup-card[data-id="${eventId}"]`);
    if (!card) return;
    const btn = card.querySelector('.btn-remind');
    if (!btn) return;
    if (active) {
        btn.classList.add('bell-active');
        btn.innerHTML = '<i class="fas fa-bell"></i> Reminder Set';
    } else {
        btn.classList.remove('bell-active');
        btn.innerHTML = '<i class="fas fa-bell"></i> Remind Me';
    }
}

// ── Form helpers ──────────────────────────────────────────────────────────────
function showFormError(msg) {
    const el = document.getElementById('form-error');
    el.textContent = msg;
    el.classList.remove('hidden');
}
function hideFormError() {
    document.getElementById('form-error').classList.add('hidden');
}
function resetForm() {
    document.getElementById('input-email').value = '';
    document.getElementById('input-phone').value = '';
    document.querySelectorAll('input[name="interval"]').forEach(cb => { cb.checked = true; });
    hideFormError();
    const btn = document.getElementById('btn-modal-submit');
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-bell"></i> Set Reminder';
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

function updateCounts() {
    const tennis  = allMeetups.filter(m => m.topic === 'tennis').length;
    const science = allMeetups.filter(m => m.topic === 'science').length;
    document.getElementById('cnt-all').textContent     = allMeetups.length;
    document.getElementById('cnt-tennis').textContent  = tennis;
    document.getElementById('cnt-science').textContent = science;
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

function setLoadingState(loading) {
    document.getElementById('loading-state').classList.toggle('hidden', !loading);
    document.getElementById('error-state').classList.add('hidden');
    const btn = document.getElementById('btn-refresh');
    btn.disabled = loading;
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
// Event listeners
// ══════════════════════════════════════════════════════════════════════════════

// Filter tabs
document.getElementById('filter-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.ftab');
    if (!btn) return;
    document.querySelectorAll('.ftab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.topic;
    renderAll();
});

// Sort
document.getElementById('sort-select').addEventListener('change', e => {
    activeSort = e.target.value;
    renderAll();
});

// Refresh
document.getElementById('btn-refresh').addEventListener('click', loadMeetups);

// Modal close
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('btn-modal-cancel').addEventListener('click', closeModal);
document.getElementById('btn-success-done').addEventListener('click', closeModal);
document.getElementById('btn-manage-close').addEventListener('click', closeModal);
document.getElementById('btn-cancel-reminder').addEventListener('click', cancelReminder);
document.getElementById('btn-modal-submit').addEventListener('click', submitReminder);

// Close on overlay click
document.getElementById('reminder-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('reminder-modal')) closeModal();
});

// Close on Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
});

// ══════════════════════════════════════════════════════════════════════════════
// Boot
// ══════════════════════════════════════════════════════════════════════════════
initMap();
loadStatus();
loadMeetups();
