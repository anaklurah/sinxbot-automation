/**
 * OmniShorts Auto-Publisher (OSAP) — Frontend Controller
 * 3D Claymorphism Interactive Logic
 */

let currentPage = 1;
let isPipelineActive = false;
let eventSource = null;
let selectedAccountId = 1;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initLucide();
    loadAccounts();
    loadDashboardData();
    loadPlatformsData();
    loadConfigData();
    setupLogStream();

    // Auto refresh dashboard stats every 5 seconds without UI flicker
    setInterval(() => {
        loadDashboardData(true);
    }, 5000);
});

/**
 * Initialize Lucide SVG icons safely
 */
function initLucide() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

/**
 * Tab Navigation Controller
 */
function switchTab(tabId, el) {
    document.querySelectorAll('.clay-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    if (el) {
        el.classList.add('active');
    } else {
        const targetBtn = document.querySelector(`.clay-tab-btn[data-tab="${tabId}"]`);
        if (targetBtn) targetBtn.classList.add('active');
    }

    const targetContent = document.getElementById(`tab-${tabId}`);
    if (targetContent) {
        targetContent.classList.add('active');
    }

    if (tabId === 'dashboard') loadDashboardData();
    if (tabId === 'platforms') loadPlatformsData();
    if (tabId === 'config') loadConfigData();

    setTimeout(initLucide, 50);
}

/**
 * ─────────────────────────────────────────────
 * Multi-Account Management
 * ─────────────────────────────────────────────
 */
async function loadAccounts() {
    try {
        const res = await fetch('/api/accounts');
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById('select-active-account');
        if (!select) return;

        select.innerHTML = '';
        (data.accounts || []).forEach(acc => {
            const opt = document.createElement('option');
            opt.value = acc.id;
            opt.textContent = acc.name + (acc.is_active ? ' (Aktif)' : '');
            if (acc.is_active) {
                opt.selected = true;
                selectedAccountId = acc.id;
            }
            select.appendChild(opt);
        });
        if (data.active_id) {
            selectedAccountId = data.active_id;
            select.value = data.active_id;
        }
    } catch (err) {
        console.error("Error loading accounts:", err);
    }
}

async function changeActiveAccount(accId) {
    try {
        selectedAccountId = parseInt(accId);
        const res = await fetch(`/api/accounts/active/${accId}`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`Beralih ke ${data.account?.name || 'Akun ' + accId}`, 'info', 2500);
            await loadAccounts();
            await loadPlatformsData();
            await loadDashboardData(true);
        } else {
            showToast(data.detail || 'Gagal mengganti akun aktif', 'error');
        }
    } catch (err) {
        showToast('Network error switching account', 'error');
    }
}

async function promptAddAccount() {
    const name = prompt('Masukkan nama profil akun baru (misal: Akun 2 Gaming):');
    if (!name || !name.trim()) return;

    try {
        const res = await fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim() })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Akun '${data.account?.name}' berhasil ditambahkan!`, 'success');
            await loadAccounts();
            if (data.account?.id) {
                await changeActiveAccount(data.account.id);
            }
        } else {
            showToast(data.detail || 'Gagal menambahkan akun', 'error');
        }
    } catch (err) {
        showToast('Network error adding account', 'error');
    }
}

/**
 * ─────────────────────────────────────────────
 * Dashboard & System Info
 * ─────────────────────────────────────────────
 */
async function loadDashboardData(silent = false) {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('Status endpoint error');
        const data = await res.json();

        // Stats Counters
        const stats = data.queue_stats || {};
        const byStatus = stats.by_status || {};
        
        document.getElementById('stat-total').innerText = stats.total || 0;
        document.getElementById('stat-pending').innerText = byStatus.pending || 0;
        document.getElementById('stat-done').innerText = byStatus.done || 0;
        document.getElementById('stat-failed').innerText = byStatus.failed || 0;

        // Hardware info
        const hw = data.hardware || {};
        document.getElementById('sys-encoder').innerText = `${hw.gpu || 'CPU'} (${hw.encoder || 'libx264'})`;
        document.getElementById('sys-os').innerText = `${hw.os || '-'}`;
        document.getElementById('sys-python').innerText = `Python ${hw.python_version || '-'}`;
        
        const enabledCount = (data.enabled_platforms || []).length;
        document.getElementById('sys-platforms-count').innerText = `${enabledCount} Platforms Active`;

        // Pipeline & Scheduler State
        isPipelineActive = !!data.pipeline_active;
        updatePipelineStatusUI(isPipelineActive, data.scheduler);

        if (!silent) {
            loadVideos(currentPage);
        }
    } catch (err) {
        console.error("Error loading dashboard data:", err);
    }
}

function formatRemaining(secs) {
    if (!secs || secs <= 0) return 'segera';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}j ${m}m`;
    return `${m}m`;
}

/**
 * Update Header Scheduler Status Pill and Toggle Button
 */
function updatePipelineStatusUI(active, scheduler) {
    const beacon = document.getElementById('status-beacon');
    const text = document.getElementById('pipeline-status-text');
    const btn = document.getElementById('btn-pipeline-toggle');

    if (!btn || !beacon || !text) return;

    if (active) {
        beacon.classList.add('active');
        const nextTime = scheduler?.next_slot ? `Next: ${scheduler.next_slot} WIB (${formatRemaining(scheduler.remaining_seconds)})` : 'Running';
        text.innerText = `Scheduler Aktif • ${nextTime}`;
        text.style.color = 'var(--success)';
        btn.className = 'btn-clay btn-clay-danger';
        btn.innerHTML = `<i data-lucide="square"></i> <span>Stop Scheduler</span>`;
    } else {
        beacon.classList.remove('active');
        const nextSlot = scheduler?.next_slot ? `Next: ${scheduler.next_slot} WIB` : 'Idle';
        text.innerText = `Scheduler Idle • ${nextSlot}`;
        text.style.color = 'var(--text-secondary)';
        btn.className = 'btn-clay btn-clay-primary';
        btn.innerHTML = `<i data-lucide="clock"></i> <span>Run Scheduler (3x Daily)</span>`;
    }
    initLucide();
}

/**
 * Toggle Prime-Time Scheduler (Start / Stop)
 */
async function togglePipeline() {
    const endpoint = isPipelineActive ? '/api/pipeline/stop' : '/api/pipeline/start';
    const actionLabel = isPipelineActive ? 'Mematikan prime-time scheduler...' : 'Mengaktifkan prime-time scheduler (3x sehari)...';
    
    showToast(actionLabel, 'info', 2500);

    try {
        const res = await fetch(endpoint, { method: 'POST' });
        const data = await res.json();
        
        if (res.ok) {
            showToast(data.message || 'Pipeline status updated', 'success');
        } else {
            showToast(data.detail || 'Failed to toggle pipeline', 'error');
        }
        await loadDashboardData();
    } catch (err) {
        showToast('Network error toggling pipeline', 'error');
    }
}

/**
 * Reset Stuck Jobs
 */
async function resetStuckJobs() {
    try {
        const res = await fetch('/api/reset-stuck', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Stuck jobs reset successfully', 'success');
            loadDashboardData();
        } else {
            showToast(data.detail || 'Error resetting stuck jobs', 'error');
        }
    } catch (err) {
        showToast('Network error resetting stuck jobs', 'error');
    }
}

/**
 * ─────────────────────────────────────────────
 * Video Queue Table & Pagination
 * ─────────────────────────────────────────────
 */
async function loadVideos(page = 1) {
    currentPage = page;
    const filterEl = document.getElementById('filter-status');
    const statusFilter = filterEl ? filterEl.value : '';
    const tbody = document.getElementById('videos-table-body');
    if (!tbody) return;

    try {
        const accParam = selectedAccountId ? `&account_id=${selectedAccountId}` : '';
        const res = await fetch(`/api/videos?page=${page}&limit=10&status=${statusFilter}${accParam}`);
        const data = await res.json();

        tbody.innerHTML = '';
        if (!data.videos || data.videos.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
                        <i data-lucide="inbox" style="width: 38px; height: 38px; opacity: 0.4; margin-bottom: 8px; display: block; margin-left: auto; margin-right: auto;"></i>
                        No video jobs found in queue.
                    </td>
                </tr>
            `;
            initLucide();
            return;
        }

        data.videos.forEach(v => {
            let platformHtml = '';
            if (v.platforms && Object.keys(v.platforms).length > 0) {
                for (const [pName, pData] of Object.entries(v.platforms)) {
                    platformHtml += `<span class="platform-pill ${pData.status}">${pName}: ${pData.status}</span> `;
                }
            } else {
                platformHtml = `<span style="color: var(--text-muted); font-size: 0.78rem;">-</span>`;
            }

            const videoDisplayLink = v.video_id 
                ? `<a href="${v.url}" target="_blank" style="color: var(--primary-light); font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
                     ${escapeHtml(v.video_id)} <i data-lucide="external-link" style="width: 12px; height: 12px;"></i>
                   </a>`
                : `<a href="${v.url}" target="_blank" style="color: var(--primary-light); text-decoration: none;">Watch</a>`;

            const row = document.createElement('tr');
            row.innerHTML = `
                <td style="font-weight: 700; color: var(--text-muted); font-family: var(--font-mono);">#${v.id}</td>
                <td>${videoDisplayLink}</td>
                <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(v.ai_title || v.title || '')}">
                    ${escapeHtml(v.ai_title || v.title || 'Processing...')}
                </td>
                <td><span class="badge-clay badge-${v.status}">${v.status}</span></td>
                <td><div class="platform-pills">${platformHtml}</div></td>
                <td style="color: var(--text-muted); font-size: 0.78rem; font-family: var(--font-mono); white-space: nowrap;">
                    ${escapeHtml(v.created_at || '')}
                </td>
            `;
            tbody.appendChild(row);
        });

        const pageInfo = document.getElementById('page-info');
        if (pageInfo) pageInfo.innerText = `Page ${data.page} of ${data.pages || 1}`;

        const prevBtn = document.getElementById('btn-prev-page');
        const nextBtn = document.getElementById('btn-next-page');
        if (prevBtn) prevBtn.disabled = (data.page <= 1);
        if (nextBtn) nextBtn.disabled = (data.page >= data.pages);

        initLucide();
    } catch (err) {
        console.error("Error loading videos:", err);
    }
}

function changePage(delta) {
    loadVideos(currentPage + delta);
}

/**
 * ─────────────────────────────────────────────
 * URL Manager (Batch Ingestion)
 * ─────────────────────────────────────────────
 */
async function submitIngest() {
    const textarea = document.getElementById('urls-input');
    if (!textarea) return;
    const urlsText = textarea.value.trim();

    if (!urlsText) {
        showToast('Please enter at least one valid YouTube URL', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls: urlsText, account_id: selectedAccountId })
        });
        const data = await res.json();

        if (res.ok) {
            showToast(`Berhasil menyimpan ${data.added} link ke Gudang Konten (${data.skipped} duplikat diabaikan)!`, 'success');
            textarea.value = '';
            loadDashboardData();
        } else {
            showToast(data.detail || 'Gagal menyimpan URL ke Gudang Konten', 'error');
        }
    } catch (err) {
        showToast('Network error submitting URLs', 'error');
    }
}

/**
 * ─────────────────────────────────────────────
 * Configuration (Load & Save)
 * ─────────────────────────────────────────────
 */
async function loadConfigData() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();

        const yaml = data.yaml || {};
        const env = data.env || {};

        document.getElementById('cfg-posts-per-hour').value = yaml.rate_limits?.posts_per_hour_per_platform || 2;
        document.getElementById('cfg-delay-platforms').value = yaml.rate_limits?.delay_between_platforms_sec || 30;
        document.getElementById('cfg-workers-download').value = yaml.rate_limits?.workers_downloader || 2;

        const isHeadless = env.HEADLESS !== undefined 
            ? (env.HEADLESS === true || env.HEADLESS === 'true') 
            : (yaml.browser?.headless || false);
        document.getElementById('cfg-browser-headless').value = isHeadless ? 'true' : 'false';

        document.getElementById('cfg-ffmpeg-zoom').value = yaml.ffmpeg?.zoom_factor || 1.10;
        document.getElementById('cfg-ffmpeg-speed').value = yaml.ffmpeg?.speed_factor || 1.05;
        document.getElementById('cfg-ffmpeg-noise').value = yaml.ffmpeg?.noise_amount || 3;
        document.getElementById('cfg-ffmpeg-contrast').value = yaml.ffmpeg?.contrast || 1.05;
        document.getElementById('cfg-ffmpeg-saturation').value = yaml.ffmpeg?.saturation || 1.08;

        // Watermark settings
        const isWmEnabled = env.WATERMARK_ENABLED !== undefined
            ? (env.WATERMARK_ENABLED === true || env.WATERMARK_ENABLED === 'true')
            : (yaml.watermark?.enabled ?? true);
        document.getElementById('cfg-watermark-enabled').value = isWmEnabled ? 'true' : 'false';
        document.getElementById('cfg-watermark-text').value = env.WATERMARK_TEXT || yaml.watermark?.text || 'SINXBOT';
        document.getElementById('cfg-watermark-size').value = env.WATERMARK_FONT_SIZE || yaml.watermark?.font_size || 32;

        document.getElementById('cfg-deepseek-key').value = env.DEEPSEEK_API_KEY_MASKED || '';
        document.getElementById('cfg-deepseek-model').value = env.DEEPSEEK_MODEL || 'deepseek-chat';
    } catch (err) {
        console.error("Error loading config:", err);
    }
}

async function saveConfiguration() {
    const payload = {
        posts_per_hour: parseInt(document.getElementById('cfg-posts-per-hour').value),
        delay_between_platforms_sec: parseInt(document.getElementById('cfg-delay-platforms').value),
        workers_downloader: parseInt(document.getElementById('cfg-workers-download').value),
        headless: document.getElementById('cfg-browser-headless').value === 'true',
        ffmpeg_zoom: parseFloat(document.getElementById('cfg-ffmpeg-zoom').value),
        ffmpeg_speed: parseFloat(document.getElementById('cfg-ffmpeg-speed').value),
        ffmpeg_noise: parseInt(document.getElementById('cfg-ffmpeg-noise').value),
        ffmpeg_contrast: parseFloat(document.getElementById('cfg-ffmpeg-contrast').value),
        ffmpeg_saturation: parseFloat(document.getElementById('cfg-ffmpeg-saturation').value),
        watermark_enabled: document.getElementById('cfg-watermark-enabled').value === 'true',
        watermark_text: document.getElementById('cfg-watermark-text').value,
        watermark_font_size: parseInt(document.getElementById('cfg-watermark-size').value) || 32,
        deepseek_api_key: document.getElementById('cfg-deepseek-key').value,
        deepseek_model: document.getElementById('cfg-deepseek-model').value
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Configuration saved successfully!', 'success');
        } else {
            showToast(data.detail || 'Failed to save configuration', 'error');
        }
    } catch (err) {
        showToast('Network error saving configuration', 'error');
    }
}

/**
 * ─────────────────────────────────────────────
 * Social Media Platforms Management
 * ─────────────────────────────────────────────
 */
async function loadPlatformsData() {
    const container = document.getElementById('platforms-grid');
    if (!container) return;

    try {
        const res = await fetch(`/api/platforms?account_id=${selectedAccountId}`);
        const data = await res.json();

        container.innerHTML = '';
        (data.platforms || []).forEach(p => {
            const isConfigured = p.auth_status === 'configured';
            const card = document.createElement('div');
            card.className = 'clay-platform-card';

            card.innerHTML = `
                <div class="clay-platform-header">
                    <div class="clay-platform-title">
                        <div class="platform-clay-badge badge-${p.id}">
                            ${getPlatformIconSvg(p.id)}
                        </div>
                        <span>${escapeHtml(p.name)}</span>
                    </div>
                    <label class="clay-switch">
                        <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="togglePlatform('${p.id}', this.checked)">
                        <span class="clay-switch-slider"></span>
                    </label>
                </div>

                <div style="font-size: 0.82rem; color: var(--text-muted); line-height: 1.5;">
                    Auth Type: <strong style="color: var(--text-primary);">${escapeHtml(p.auth_type)}</strong>
                </div>

                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="badge-clay ${isConfigured ? 'badge-done' : 'badge-failed'}">
                        <i data-lucide="${isConfigured ? 'check-circle' : 'alert-triangle'}" style="width: 14px; height: 14px;"></i>
                        ${isConfigured ? 'Auth Configured' : 'Auth Missing'}
                    </span>
                </div>

                <div class="platform-card-footer">
                    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                        <button class="btn-clay btn-clay-secondary btn-clay-sm" onclick="triggerSetupAuth('${p.id}')" title="Buka browser untuk login manual (cookies kadaluarsa / fresh login)">
                            <i data-lucide="log-in"></i> Login Browser
                        </button>
                        ${p.auth_type === 'cookies' ? `
                            <label class="btn-clay btn-clay-secondary btn-clay-sm" style="cursor: pointer; margin: 0;" title="Upload file cookie .json / .txt">
                                <i data-lucide="upload"></i> Cookie
                                <input type="file" accept=".txt,.json" style="display: none;" onchange="uploadCookies('${p.id}', this)">
                            </label>
                        ` : ''}
                    </div>
                    <button class="btn-clay btn-clay-primary btn-clay-sm" ${!p.enabled ? 'disabled title="Nyalakan switch platform ini terlebih dahulu"' : ''} onclick="triggerManualPost('${p.id}', this)">
                        <i data-lucide="send"></i> Post Now
                    </button>
                </div>
            `;
            container.appendChild(card);
        });

        initLucide();
    } catch (err) {
        console.error("Error loading platforms:", err);
    }
}

/**
 * Platform SVG helper
 */
function getPlatformIconSvg(id) {
    switch (id) {
        case 'youtube':
            return `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>`;
        case 'facebook':
            return `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>`;
        case 'instagram':
            return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>`;
        case 'tiktok':
            return `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1.04-.1z"/></svg>`;
        default:
            return `<i data-lucide="share-2" style="width: 18px; height: 18px;"></i>`;
    }
}

async function togglePlatform(platformId, enabled) {
    const enabledMap = {};
    enabledMap[platformId] = enabled;
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled_platforms: enabledMap })
        });
        showToast(`Platform ${platformId} ${enabled ? 'enabled' : 'disabled'}`, 'info', 2000);
        await loadPlatformsData();
        await loadDashboardData(true);
    } catch (err) {
        showToast('Failed to toggle platform state', 'error');
    }
}

async function triggerSetupAuth(platformId) {
    try {
        const res = await fetch(`/api/setup-auth/${platformId}?account_id=${selectedAccountId}`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message || `Auth window opened for ${platformId}`, 'info', 5000);
    } catch (err) {
        showToast('Failed to launch auth browser window', 'error');
    }
}

async function uploadCookies(platformId, inputElement) {
    if (!inputElement.files || inputElement.files.length === 0) return;
    const file = inputElement.files[0];
    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`/api/upload-cookies/${platformId}?account_id=${selectedAccountId}`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Cookies loaded for ${platformId}`, 'success');
            await loadPlatformsData();
        } else {
            showToast(data.detail || `Upload failed for ${platformId}`, 'error');
        }
    } catch (err) {
        showToast(`Error uploading cookie file: ${err.message}`, 'error');
    }
}

async function triggerManualPost(platformId, btnElement) {
    const btn = btnElement || (typeof event !== 'undefined' ? event?.currentTarget : null) || document.querySelector(`[onclick*="triggerManualPost('${platformId}'"]`);
    const originalHTML = btn ? btn.innerHTML : null;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Posting...`;
    }

    try {
        const res = await fetch(`/api/publish/${platformId}?account_id=${selectedAccountId}`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`🚀 ${data.message}`, 'success', 8000);
            loadDashboardData(true);
            setTimeout(() => loadDashboardData(true), 3000);
            setTimeout(() => loadDashboardData(true), 8000);
        } else {
            showToast(`❌ ${data.detail || `Gagal memulai on-demand post untuk ${platformId}`}`, 'error', 7000);
        }
    } catch (err) {
        if (err.message && err.message.includes('fetch')) {
            showToast('⚠️ Cannot connect to server. Is the OSAP server running?', 'error', 8000);
        } else {
            showToast(`Error: ${err.message}`, 'error', 6000);
        }
    } finally {
        if (btn && originalHTML) {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }
}

async function triggerPublishAllPlatforms(btnElement) {
    const btn = btnElement || (typeof event !== 'undefined' ? event?.currentTarget : null);
    const originalHTML = btn ? btn.innerHTML : null;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Memproses...`;
    }

    try {
        const res = await fetch(`/api/pipeline/publish-all?account_id=${selectedAccountId}`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`🚀 ${data.message}`, 'success', 8000);
            loadDashboardData(true);
            setTimeout(() => loadDashboardData(true), 3000);
            setTimeout(() => loadDashboardData(true), 8000);
        } else {
            showToast(`❌ ${data.detail || 'Gagal memulai publikasi video ke semua platform'}`, 'error', 7000);
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 6000);
    } finally {
        if (btn && originalHTML) {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    }
}

/**
 * ─────────────────────────────────────────────
 * Live Logs SSE Stream
 * ─────────────────────────────────────────────
 */
function setupLogStream() {
    if (eventSource) eventSource.close();

    eventSource = new EventSource('/api/logs/stream');
    const term = document.getElementById('terminal-log');
    if (!term) return;

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (!data.message) return;

            const line = document.createElement('div');
            line.className = `terminal-line ${data.level || 'INFO'}`;
            line.innerHTML = `
                <span class="term-time">[${data.timestamp || new Date().toLocaleTimeString()}]</span>
                <span class="term-level">${data.level || 'INFO'}</span>
                <span class="term-msg">${escapeHtml(data.message)}</span>
            `;
            
            term.appendChild(line);
            term.scrollTop = term.scrollHeight;
        } catch (e) {
            console.error("SSE parse error", e);
        }
    };

    eventSource.onerror = () => {
        // SSE disconnected, will auto-reconnect
    };
}

function clearLogs() {
    const term = document.getElementById('terminal-log');
    if (term) term.innerHTML = '';
    showToast('Terminal logs cleared', 'info', 2000);
}

/**
 * Security: HTML entity escaper
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
