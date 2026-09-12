/**
 * OmniShorts Auto-Publisher (OSAP) — Frontend Controller
 * 3D Claymorphism Interactive Logic
 */

let currentPage = 1;
let isPipelineActive = false;
let eventSource = null;


// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initLucide();
    loadDashboardData();
    loadPlatformsData();
    loadVideos(1);
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

    if (tabId === 'dashboard') {
        loadDashboardData();
        loadPlatformsData();
    }
    if (tabId === 'urls') loadVideos(currentPage);
    if (tabId === 'config') loadConfigData();
    if (tabId === 'ytdlp') loadYtdlpData();

    setTimeout(initLucide, 50);
}

/**
 * ─────────────────────────────────────────────
 * Modal: Tambah Akun Platform (New Target Card)
 * ─────────────────────────────────────────────
 */
function openAddPlatformTargetModal() {
    const modal = document.getElementById('modal-add-platform-target');
    if (!modal) return;
    const platformSelect = document.getElementById('modal-target-platform');
    const nameInput = document.getElementById('modal-target-name');
    const wmInput = document.getElementById('modal-target-watermark');

    if (platformSelect) platformSelect.value = 'youtube';
    if (nameInput) nameInput.value = 'YouTube 2';
    if (wmInput) wmInput.value = '';

    modal.style.display = 'flex';
    setTimeout(initLucide, 50);
}

function closeAddPlatformTargetModal() {
    const modal = document.getElementById('modal-add-platform-target');
    if (modal) modal.style.display = 'none';
}

function onModalPlatformChange(platformVal) {
    const nameInput = document.getElementById('modal-target-name');
    if (!nameInput) return;
    const labels = {
        'youtube': 'YouTube 2',
        'instagram': 'Instagram 2',
        'tiktok': 'TikTok 2',
        'twitter': 'Twitter 2',
        'facebook': 'Facebook 2',
        'upscrolled': 'Upscrolled 2',
        'febspot': 'Febspot 2'
    };
    nameInput.value = labels[platformVal] || (platformVal.charAt(0).toUpperCase() + platformVal.slice(1) + ' 2');
}

async function submitAddPlatformTarget() {
    const platformSelect = document.getElementById('modal-target-platform');
    const nameInput = document.getElementById('modal-target-name');
    const wmInput = document.getElementById('modal-target-watermark');

    const platform = platformSelect ? platformSelect.value : 'youtube';
    const name = nameInput ? nameInput.value.trim() : '';
    const watermark_text = wmInput ? wmInput.value.trim() : '';

    if (!name) {
        showToast('Mohon masukkan nama akun / label kartu', 'error');
        return;
    }

    try {
        const res = await fetch('/api/platform-targets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: platform,
                name: name,
                watermark_text: watermark_text,
                watermark_enabled: true
            })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Kartu '${name}' berhasil ditambahkan!`, 'success');
            closeAddPlatformTargetModal();
            await loadPlatformsData();
        } else {
            showToast(data.detail || 'Gagal menambahkan kartu platform', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
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
            loadPlatformsData();
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
        const tzAbbr = scheduler?.timezone_abbr || 'WIB';
        const nextTime = scheduler?.next_slot ? `Next: ${scheduler.next_slot} ${tzAbbr} (${formatRemaining(scheduler.remaining_seconds)})` : 'Running';
        text.innerText = `Scheduler Aktif • ${nextTime}`;
        text.style.color = 'var(--success)';
        btn.className = 'btn-clay btn-clay-danger';
        btn.innerHTML = `<i data-lucide="square"></i> <span>Stop Scheduler</span>`;
    } else {
        beacon.classList.remove('active');
        const tzAbbr = scheduler?.timezone_abbr || 'WIB';
        const nextSlot = scheduler?.next_slot ? `Next: ${scheduler.next_slot} ${tzAbbr}` : 'Idle';
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
        const res = await fetch(`/api/videos?page=${page}&limit=10&status=${statusFilter}`);

        const data = await res.json();

        tbody.innerHTML = '';
        if (!data.videos || data.videos.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
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
                <td style="text-align: center;">
                    <button class="btn-clay btn-clay-secondary btn-clay-sm" onclick="deleteVideoItem(${v.id})" title="Hapus video #${v.id} dari antrian" style="padding: 4px 8px; color: #ef4444; border-radius: 6px;">
                        <i data-lucide="trash-2" style="width: 13px; height: 13px;"></i>
                    </button>
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
            body: JSON.stringify({ urls: urlsText })

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
function setSchedulePreset(slotsText) {
    const input = document.getElementById('cfg-schedule-slots');
    if (input) {
        input.value = slotsText;
        showToast(`Preset dipilih: ${slotsText}`, 'info', 2000);
    }
}

async function loadConfigData() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();

        const yaml = data.yaml || {};
        const env = data.env || {};

        // Smart Scheduler slots
        const scheduleSlots = data.schedule_slots || yaml.scheduler?.slots || ['12:00', '18:00', '21:00'];
        const scheduleInput = document.getElementById('cfg-schedule-slots');
        if (scheduleInput) {
            scheduleInput.value = Array.isArray(scheduleSlots) ? scheduleSlots.join(', ') : scheduleSlots;
        }

        const tzSelect = document.getElementById('cfg-timezone');
        if (tzSelect) {
            tzSelect.value = env.TIMEZONE || yaml.scheduler?.timezone || 'Asia/Jakarta';
        }

        const elPosts = document.getElementById('cfg-posts-per-hour');
        if (elPosts) elPosts.value = yaml.rate_limits?.posts_per_hour_per_platform || 2;

        const elDelay = document.getElementById('cfg-delay-platforms');
        if (elDelay) elDelay.value = yaml.rate_limits?.delay_between_platforms_sec || 25;

        const elWorkers = document.getElementById('cfg-workers-download');
        if (elWorkers) elWorkers.value = yaml.rate_limits?.workers_downloader || 2;

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
        document.getElementById('cfg-watermark-size').value = env.WATERMARK_FONT_SIZE || yaml.watermark?.font_size || 20;

        const deepseekInput = document.getElementById('cfg-deepseek-key');
        if (deepseekInput) {
            deepseekInput.value = '';
            if (env.DEEPSEEK_HAS_KEY) {
                deepseekInput.placeholder = `(Tersimpan: ${env.DEEPSEEK_API_KEY_MASKED}) - Biarkan kosong jika tidak diubah`;
            } else {
                deepseekInput.placeholder = 'sk-... (masukkan API key baru)';
            }
        }
        const deepseekModel = document.getElementById('cfg-deepseek-model');
        if (deepseekModel) deepseekModel.value = env.DEEPSEEK_MODEL || 'deepseek-chat';

        // Telegram settings
        const isTgEnabled = env.TELEGRAM_ENABLED !== undefined
            ? (env.TELEGRAM_ENABLED === true || env.TELEGRAM_ENABLED === 'true')
            : (yaml.telegram?.enabled ?? true);
        if (document.getElementById('cfg-telegram-enabled')) {
            document.getElementById('cfg-telegram-enabled').value = isTgEnabled ? 'true' : 'false';
        }
        const tgTokenInput = document.getElementById('cfg-telegram-token');
        if (tgTokenInput) {
            tgTokenInput.value = '';
            if (env.TELEGRAM_HAS_TOKEN) {
                tgTokenInput.placeholder = `(Tersimpan: ${env.TELEGRAM_BOT_TOKEN_MASKED}) - Biarkan kosong jika tidak diubah`;
            } else {
                tgTokenInput.placeholder = '123456789:ABCdef... (masukkan bot token)';
            }
        }
        if (document.getElementById('cfg-telegram-chat-id')) {
            document.getElementById('cfg-telegram-chat-id').value = env.TELEGRAM_CHAT_ID || '';
        }

        // Proxy URL
        const proxyInput = document.getElementById('cfg-proxy-url');
        if (proxyInput) {
            proxyInput.value = env.PROXY_URL || yaml.proxy_url || '';
            const badge = document.getElementById('cfg-proxy-status-badge');
            if (badge) {
                if (proxyInput.value) {
                    badge.className = 'badge-clay badge-done';
                    badge.innerHTML = '<i data-lucide="network" style="width: 12px; height: 12px;"></i> Proxy Configured';
                } else {
                    badge.className = 'badge-clay badge-secondary';
                    badge.innerHTML = '<i data-lucide="zap" style="width: 12px; height: 12px;"></i> Direct Mode';
                }
            }
        }
        initLucide();
    } catch (err) {
        console.error("Error loading config:", err);
    }
}

async function saveConfiguration() {
    const rawSlots = (document.getElementById('cfg-schedule-slots')?.value || '12:00, 18:00, 21:00')
        .split(',')
        .map(s => s.trim())
        .filter(s => s.length > 0 && s.includes(':'));

    const payload = {
        schedule_slots: rawSlots.length > 0 ? rawSlots : ['12:00', '18:00', '21:00'],
        posts_per_hour: parseInt(document.getElementById('cfg-posts-per-hour')?.value || '2'),
        delay_between_platforms_sec: parseInt(document.getElementById('cfg-delay-platforms')?.value || '25'),
        workers_downloader: parseInt(document.getElementById('cfg-workers-download')?.value || '2'),
        headless: document.getElementById('cfg-browser-headless').value === 'true',
        ffmpeg_zoom: parseFloat(document.getElementById('cfg-ffmpeg-zoom').value),
        ffmpeg_speed: parseFloat(document.getElementById('cfg-ffmpeg-speed').value),
        ffmpeg_noise: parseInt(document.getElementById('cfg-ffmpeg-noise').value),
        ffmpeg_contrast: parseFloat(document.getElementById('cfg-ffmpeg-contrast').value),
        ffmpeg_saturation: parseFloat(document.getElementById('cfg-ffmpeg-saturation').value),
        watermark_enabled: document.getElementById('cfg-watermark-enabled').value === 'true',
        watermark_text: document.getElementById('cfg-watermark-text').value,
        watermark_font_size: parseInt(document.getElementById('cfg-watermark-size').value) || 20,
        deepseek_api_key: document.getElementById('cfg-deepseek-key')?.value?.trim() || null,
        deepseek_model: document.getElementById('cfg-deepseek-model')?.value || null,
        telegram_enabled: document.getElementById('cfg-telegram-enabled') ? document.getElementById('cfg-telegram-enabled').value === 'true' : true,
        telegram_bot_token: document.getElementById('cfg-telegram-token')?.value?.trim() || null,
        telegram_chat_id: document.getElementById('cfg-telegram-chat-id')?.value?.trim() || null,
        proxy_url: document.getElementById('cfg-proxy-url')?.value?.trim() ?? '',
        timezone: document.getElementById('cfg-timezone')?.value || 'Asia/Jakarta',
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Konfigurasi & jam posting berhasil disimpan!', 'success');
            loadDashboardData(true);
        } else {
            showToast(data.detail || 'Failed to save configuration', 'error');
        }
    } catch (err) {
        showToast('Network error saving configuration', 'error');
    }
}

async function testTelegramConnection() {
    const token = document.getElementById('cfg-telegram-token')?.value?.trim() || null;
    const chatId = document.getElementById('cfg-telegram-chat-id')?.value?.trim() || null;
    const statusEl = document.getElementById('telegram-test-result');
    if (statusEl) {
        statusEl.style.color = 'var(--accent-amber)';
        statusEl.innerHTML = '<i data-lucide="loader-2" class="spin" style="width:14px;height:14px;vertical-align:middle;"></i> Menguji koneksi Telegram...';
        if (window.lucide) lucide.createIcons();
    }

    try {
        const res = await fetch('/api/telegram/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_token: token, chat_id: chatId })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Koneksi Telegram sukses!', 'success');
            if (statusEl) {
                statusEl.style.color = 'var(--accent-emerald)';
                statusEl.innerText = '✓ ' + (data.message || 'Koneksi sukses!');
            }
        } else {
            showToast(data.detail || 'Gagal menguji Telegram', 'error');
            if (statusEl) {
                statusEl.style.color = 'var(--accent-rose)';
                statusEl.innerText = '✗ ' + (data.detail || 'Gagal terhubung.');
            }
        }
    } catch (err) {
        showToast('Terjadi kesalahan jaringan saat tes Telegram', 'error');
        if (statusEl) {
            statusEl.style.color = 'var(--accent-rose)';
            statusEl.innerText = '✗ Error jaringan';
        }
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === 'password') {
        input.type = 'text';
        btn.innerHTML = '<i data-lucide="eye-off"></i>';
    } else {
        input.type = 'password';
        btn.innerHTML = '<i data-lucide="eye"></i>';
    }
    if (window.lucide) lucide.createIcons();
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
        const res = await fetch('/api/platforms');
        const data = await res.json();

        container.innerHTML = '';
        (data.platforms || []).forEach(p => {
            const isConfigured = p.auth_status === 'configured';
            const card = document.createElement('div');
            card.className = 'clay-platform-card';
            card.id = `platform-card-${p.target_key}`;

            card.innerHTML = `
                <div class="clay-platform-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div class="clay-platform-title" style="display: flex; align-items: center; gap: 10px; overflow: hidden;">
                        <div class="platform-clay-badge badge-${p.platform}">
                            ${getPlatformIconSvg(p.platform)}
                        </div>
                        <div style="overflow: hidden;">
                            <div style="font-size: 1.02rem; font-weight: 700; color: var(--text-primary); white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">${escapeHtml(p.name)}</div>
                            <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">${escapeHtml(p.platform)}</div>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        ${p.is_custom ? `
                            <button onclick="deletePlatformTarget('${p.target_key}')" title="Hapus kartu ini" class="btn-clay btn-clay-secondary btn-clay-sm" style="padding: 4px 6px; color: #ff5c5c;">
                                <i data-lucide="trash-2" style="width: 14px; height: 14px;"></i>
                            </button>
                        ` : ''}
                        <label class="clay-switch">
                            <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="togglePlatformTarget('${p.target_key}', this.checked)">
                            <span class="clay-switch-slider"></span>
                        </label>
                    </div>
                </div>

                <div style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4; display: flex; justify-content: space-between; align-items: center; margin: 6px 0;">
                    <span>Auth: <strong style="color: var(--text-primary); font-size: 0.78rem;">${escapeHtml(p.auth_type)}</strong></span>
                    <span class="badge-clay ${isConfigured ? 'badge-done' : 'badge-failed'}" style="font-size: 0.72rem; padding: 2px 8px;">
                        <i data-lucide="${isConfigured ? 'check-circle' : 'alert-triangle'}" style="width: 12px; height: 12px;"></i>
                        ${isConfigured ? 'Configured' : 'Missing'}
                    </span>
                </div>

                <!-- Per-target Watermark Input Row -->
                <div style="margin: 8px 0 12px 0; padding: 6px 10px; background: rgba(0,0,0,0.18); border-radius: 10px; border: 1px solid rgba(255,255,255,0.06);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <label style="font-size: 0.72rem; font-weight: 600; color: var(--text-muted); display: flex; align-items: center; gap: 4px;">
                            <i data-lucide="type" style="width: 12px; height: 12px;"></i> Watermark:
                        </label>
                        <span style="font-size: 0.68rem; color: ${p.watermark_text ? '#10b981' : 'var(--text-muted)'};">
                            ${p.watermark_text ? 'Teks Khusus' : 'Default/Global'}
                        </span>
                    </div>
                    <input type="text" class="clay-input" style="padding: 4px 8px; font-size: 0.78rem; height: 28px; width: 100%;" 
                        placeholder="Contoh: @channel_saya" 
                        value="${escapeHtml(p.watermark_text || '')}" 
                        onchange="updateTargetWatermark('${p.target_key}', this.value)"
                        title="Ubah teks watermark khusus untuk akun ini (otomatis tersimpan)">
                </div>

                <div class="platform-card-footer">
                    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                        <button class="btn-clay btn-clay-secondary btn-clay-sm" onclick="triggerSetupAuth('${p.target_key}')" title="Buka browser tampak untuk login manual">
                            <i data-lucide="log-in"></i> Login Browser
                        </button>
                        <label class="btn-clay btn-clay-secondary btn-clay-sm" style="cursor: pointer; margin: 0;" title="Upload file cookie .json / .txt untuk akun ini">
                            <i data-lucide="upload"></i> Cookie
                            <input type="file" accept=".txt,.json" style="display: none;" onchange="uploadCookies('${p.target_key}', this)">
                        </label>
                        <label class="btn-clay btn-clay-secondary btn-clay-sm" style="cursor: pointer; margin: 0;" title="Upload arsip profil browser (.zip) dari Windows">
                            <i data-lucide="archive"></i> Profile .zip
                            <input type="file" accept=".zip" style="display: none;" onchange="uploadProfileZip('${p.target_key}', this)">
                        </label>
                    </div>
                    <button class="btn-clay btn-clay-primary btn-clay-sm" ${!p.enabled ? 'disabled title="Nyalakan switch kartu ini terlebih dahulu"' : ''} onclick="triggerManualPost('${p.target_key}', this)">
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

async function togglePlatformTarget(targetKey, enabled) {
    try {
        const res = await fetch(`/api/platform-targets/${targetKey}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        if (res.ok) {
            showToast(`Kartu '${targetKey}' ${enabled ? 'diaktifkan' : 'dinonaktifkan'}`, 'info', 2000);
            await loadPlatformsData();
            await loadDashboardData(true);
        } else {
            showToast('Gagal mengubah status kartu target', 'error');
        }
    } catch (err) {
        showToast('Network error toggling target', 'error');
    }
}

async function updateTargetWatermark(targetKey, newWatermark) {
    try {
        const res = await fetch(`/api/platform-targets/${targetKey}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ watermark_text: newWatermark.trim() })
        });
        if (res.ok) {
            showToast(`Watermark '${targetKey}' tersimpan: "${newWatermark.trim() || '(Default)'}"`, 'success', 2500);
        } else {
            showToast('Gagal menyimpan watermark target', 'error');
        }
    } catch (err) {
        showToast('Network error saving watermark', 'error');
    }
}

async function deletePlatformTarget(targetKey) {
    if (!confirm(`Apakah Anda yakin ingin menghapus kartu target '${targetKey}'?`)) return;

    try {
        const res = await fetch(`/api/platform-targets/${targetKey}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Kartu '${targetKey}' berhasil dihapus!`, 'success');
            await loadPlatformsData();
        } else {
            showToast(data.detail || 'Gagal menghapus kartu target', 'error');
        }
    } catch (err) {
        showToast('Error deleting platform target', 'error');
    }
}

async function triggerSetupAuth(targetKey) {
    try {
        const res = await fetch(`/api/setup-auth/${targetKey}`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message || `Jendela auth dibuka untuk ${targetKey}`, 'info', 5000);
    } catch (err) {
        showToast('Gagal membuka jendela browser auth', 'error');
    }
}

async function uploadCookies(targetKey, inputElement) {
    if (!inputElement.files || inputElement.files.length === 0) return;
    const file = inputElement.files[0];
    const formData = new FormData();
    formData.append('file', file);
    inputElement.value = '';

    showToast(`Mengunggah cookies untuk ${targetKey}...`, 'info', 2500);

    try {
        const res = await fetch(`/api/upload-cookies/${targetKey}`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Cookies tersimpan untuk ${targetKey}`, 'success');
            await loadPlatformsData();
        } else {
            showToast(data.detail || `Upload gagal untuk ${targetKey}`, 'error');
        }
    } catch (err) {
        showToast(`Error uploading cookie: ${err.message}`, 'error');
    }
}

async function uploadProfileZip(targetKey, inputElement) {
    if (!inputElement.files || inputElement.files.length === 0) return;
    const file = inputElement.files[0];
    const formData = new FormData();
    formData.append('file', file);
    inputElement.value = '';

    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
    showToast(`Mengunggah profil '${file.name}' (${sizeMb} MB)... Mohon tunggu ekstraksi...`, 'info', 10000);

    try {
        const res = await fetch(`/api/upload-profile/${targetKey}`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Profil ${targetKey} berhasil dipasang di server!`, 'success', 6000);
            if (typeof loadPlatformsData === 'function') await loadPlatformsData();
            if (typeof loadYtdlpData === 'function') await loadYtdlpData();
        } else {
            showToast(data.detail || `Upload profile gagal untuk ${targetKey}`, 'error', 6000);
        }
    } catch (err) {
        showToast(`Error uploading profile zip: ${err.message}`, 'error', 6000);
    }
}

async function triggerManualPost(targetKey, btnElement) {
    const btn = btnElement || (typeof event !== 'undefined' ? event?.currentTarget : null) || document.querySelector(`[onclick*="triggerManualPost('${targetKey}'"]`);
    const originalHTML = btn ? btn.innerHTML : null;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Posting...`;
    }

    try {
        const res = await fetch(`/api/publish/${targetKey}`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`🚀 ${data.message}`, 'success', 8000);
            loadDashboardData(true);
            setTimeout(() => loadDashboardData(true), 3000);
            setTimeout(() => loadDashboardData(true), 8000);
        } else {
            showToast(`❌ ${data.detail || `Gagal memulai post untuk ${targetKey}`}`, 'error', 7000);
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
        const res = await fetch('/api/pipeline/publish-all', { method: 'POST' });
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

async function triggerFetchAllLatestLinks(btnElement) {
    const btn = btnElement || (typeof event !== 'undefined' ? event?.currentTarget : null);
    const originalHTML = btn ? btn.innerHTML : null;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Memindai...`;
    }

    showToast('🔍 Memulai scan link postingan terakhir dari semua platform... Pantau Live Logs dan Telegram!', 'info', 6000);

    try {
        const res = await fetch('/api/fetch-latest-posts', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`✓ ${data.message}`, 'success', 8000);
        } else {
            showToast(`❌ ${data.detail || data.message || 'Gagal memulai scan link'}`, 'error', 7000);
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 6000);
    } finally {
        if (btn && originalHTML) {
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalHTML;
            }, 3000);
        }
    }
}



/**
 * ─────────────────────────────────────────────
 * Live Logs SSE Stream
 * ─────────────────────────────────────────────
 */
let logReconnectTimer = null;
const seenLogSignatures = new Set();

function appendLogLine(data) {
    const term = document.getElementById('terminal-log');
    if (!term || !data || !data.message) return;

    // Deduplicate identical replayed logs
    const sig = `${data.timestamp || ''}|${data.level || ''}|${data.message}`;
    if (seenLogSignatures.has(sig)) return;
    seenLogSignatures.add(sig);
    if (seenLogSignatures.size > 300) {
        const first = seenLogSignatures.values().next().value;
        seenLogSignatures.delete(first);
    }

    const line = document.createElement('div');
    line.className = `terminal-line ${data.level || 'INFO'}`;
    line.innerHTML = `
        <span class="term-time">[${data.timestamp || new Date().toLocaleTimeString()}]</span>
        <span class="term-level">${data.level || 'INFO'}</span>
        <span class="term-msg">${escapeHtml(data.message)}</span>
    `;
    term.appendChild(line);
    term.scrollTop = term.scrollHeight;
}

function setupLogStream() {
    if (eventSource) {
        try { eventSource.close(); } catch(e) {}
        eventSource = null;
    }
    if (logReconnectTimer) {
        clearTimeout(logReconnectTimer);
        logReconnectTimer = null;
    }

    const term = document.getElementById('terminal-log');
    if (!term) return;

    try {
        eventSource = new EventSource('/api/logs/stream');
    } catch (err) {
        console.error("Failed to init EventSource:", err);
        fallbackPollLogs();
        return;
    }

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            appendLogLine(data);
        } catch (e) {
            console.error("SSE parse error", e);
        }
    };

    eventSource.onerror = (err) => {
        // Starlette/FastAPI dropped or network interrupted
        if (eventSource && (eventSource.readyState === EventSource.CLOSED || eventSource.readyState === 2)) {
            try { eventSource.close(); } catch(e) {}
            eventSource = null;
            if (!logReconnectTimer) {
                logReconnectTimer = setTimeout(() => {
                    logReconnectTimer = null;
                    setupLogStream();
                }, 3000);
            }
        }
    };
}

async function fallbackPollLogs() {
    try {
        const res = await fetch('/api/logs/recent?limit=40');
        if (res.ok) {
            const data = await res.json();
            (data.logs || []).forEach(appendLogLine);
        }
    } catch (e) {}
}

function clearLogs() {
    const term = document.getElementById('terminal-log');
    if (term) term.innerHTML = '';
    seenLogSignatures.clear();
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


/**
 * ─────────────────────────────────────────────
 * yt-dlp & YouTube Cookies Management
 * ─────────────────────────────────────────────
 */

async function loadYtdlpData() {
    try {
        const res = await fetch('/api/ytdlp/status');
        if (!res.ok) return;
        const data = await res.json();

        // Update version
        const verEl = document.getElementById('ytdlp-version-display');
        if (verEl) verEl.innerText = `v${data.version || 'unknown'}`;

        // Update proxy
        const proxyEl = document.getElementById('ytdlp-proxy-display');
        const proxyBubbleEl = document.getElementById('ytdlp-proxy-bubble');
        if (proxyEl) {
            if (data.proxy && data.proxy.configured) {
                if (data.proxy.alive === true) {
                    proxyEl.innerText = `Online (${data.proxy.url})`;
                    proxyEl.style.color = '#10b981';
                    if (proxyBubbleEl) proxyBubbleEl.className = 'stat-icon-bubble stat-bubble-done';
                } else if (data.proxy.alive === false) {
                    proxyEl.innerText = `OFFLINE / Refused (${data.proxy.url})`;
                    proxyEl.style.color = '#f43f5e';
                    if (proxyBubbleEl) proxyBubbleEl.className = 'stat-icon-bubble stat-bubble-failed';
                } else {
                    proxyEl.innerText = data.proxy.url || 'Configured';
                    proxyEl.style.color = '#38bdf8';
                }
            } else {
                proxyEl.innerText = 'Direct (Tanpa Proxy)';
                proxyEl.style.color = 'var(--text-secondary)';
                if (proxyBubbleEl) proxyBubbleEl.className = 'stat-icon-bubble stat-bubble-total';
            }
        }

        // Update cookies
        const cStatusEl = document.getElementById('ytdlp-cookie-status-display');
        const cBubbleEl = document.getElementById('ytdlp-cookie-bubble');
        const cFileEl = document.getElementById('ytdlp-cookie-file-name');
        const cSizeEl = document.getElementById('ytdlp-cookie-size');
        const cCountEl = document.getElementById('ytdlp-cookie-count');
        const cUpdatedEl = document.getElementById('ytdlp-cookie-updated');

        if (data.cookies && data.cookies.exists) {
            if (cStatusEl) {
                cStatusEl.innerText = `Aktif (${data.cookies.cookie_count} cookies)`;
                cStatusEl.style.color = '#10b981';
            }
            if (cBubbleEl) {
                cBubbleEl.className = 'stat-icon-bubble stat-bubble-done';
            }
            if (cFileEl) cFileEl.innerText = data.cookies.filename;
            if (cSizeEl) cSizeEl.innerText = `${(data.cookies.size_bytes / 1024).toFixed(1)} KB`;
            if (cCountEl) cCountEl.innerText = data.cookies.cookie_count;
            if (cUpdatedEl) cUpdatedEl.innerText = data.cookies.updated_at || '-';
        } else {
            if (cStatusEl) {
                cStatusEl.innerText = 'Belum Ada Cookies';
                cStatusEl.style.color = '#f43f5e';
            }
            if (cBubbleEl) {
                cBubbleEl.className = 'stat-icon-bubble stat-bubble-failed';
            }
            if (cFileEl) cFileEl.innerText = 'Belum ada file';
            if (cSizeEl) cSizeEl.innerText = '0 KB';
            if (cCountEl) cCountEl.innerText = '0';
            if (cUpdatedEl) cUpdatedEl.innerText = '-';
        }
    } catch (err) {
        console.error('Error loading yt-dlp status:', err);
    }
}

async function updateYtdlp(btn) {
    if (btn) btn.disabled = true;
    const consoleBox = document.getElementById('ytdlp-update-console');
    if (consoleBox) {
        consoleBox.style.display = 'block';
        consoleBox.innerText = 'Menjalankan pip install -U yt-dlp... Mohon tunggu...';
    }
    showToast('Sedang memperbarui yt-dlp...', 'info', 5000);

    try {
        const res = await fetch('/api/ytdlp/update', { method: 'POST' });
        const data = await res.json();
        if (consoleBox) {
            consoleBox.innerText = data.output || data.message || 'Selesai.';
        }
        if (data.success) {
            showToast(data.message, 'success', 5000);
            loadYtdlpData();
        } else {
            showToast(data.message || 'Gagal update yt-dlp', 'error', 5000);
        }
    } catch (err) {
        if (consoleBox) consoleBox.innerText = `Error: ${err.message}`;
        showToast(`Error: ${err.message}`, 'error', 5000);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function uploadYtdlpCookieFile(input) {
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);

    showToast(`Mengunggah cookies: ${file.name}...`, 'info', 3000);
    try {
        const res = await fetch('/api/ytdlp/cookies/upload', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success', 4000);
            loadYtdlpData();
            input.value = '';
        } else {
            showToast(data.detail || 'Gagal upload cookies', 'error', 4000);
        }
    } catch (err) {
        showToast(`Error upload cookies: ${err.message}`, 'error', 4000);
    }
}

async function saveYtdlpCookieText() {
    const textEl = document.getElementById('ytdlp-cookie-text');
    if (!textEl || !textEl.value.trim()) {
        showToast('Tempel teks cookies Netscape terlebih dahulu!', 'warning', 3000);
        return;
    }
    const content = textEl.value.trim();
    showToast('Menyimpan cookies teks...', 'info', 3000);

    try {
        const res = await fetch('/api/ytdlp/cookies/save-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success', 4000);
            textEl.value = '';
            loadYtdlpData();
        } else {
            showToast(data.detail || 'Gagal menyimpan cookies teks', 'error', 4000);
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 4000);
    }
}

async function deleteYtdlpCookies() {
    if (!confirm('Yakin ingin menghapus file cookies YouTube?')) return;
    try {
        const res = await fetch('/api/ytdlp/cookies', { method: 'DELETE' });
        const data = await res.json();
        showToast(data.message || 'Cookies berhasil dihapus', 'info', 3000);
        loadYtdlpData();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 4000);
    }
}

async function testYtdlpUrl(btn) {
    const urlInput = document.getElementById('ytdlp-test-url');
    if (!urlInput || !urlInput.value.trim()) {
        showToast('Masukkan URL YouTube/Shorts yang ingin dites!', 'warning', 3000);
        return;
    }
    const url = urlInput.value.trim();
    const resultBox = document.getElementById('ytdlp-test-result');
    if (resultBox) {
        resultBox.style.display = 'block';
        resultBox.innerText = 'Menguji strategi ekstraksi yt-dlp... Mohon tunggu...';
    }
    if (btn) btn.disabled = true;
    showToast('Menguji URL YouTube...', 'info', 3000);

    try {
        const res = await fetch('/api/ytdlp/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
        const data = await res.json();
        if (resultBox) {
            let output = `HASIL TES:\nStatus: ${data.success ? 'BERHASIL' : 'SEMUA STRATEGI GAGAL'}\n\n`;
            if (data.video) {
                output += `Judul: ${data.video.title}\nChannel: ${data.video.uploader}\nDurasi: ${data.video.duration} detik\nID: ${data.video.id}\n\n`;
            }
            output += `LOG STRATEGI:\n` + (data.logs || []).join('\n');
            resultBox.innerText = output;
        }
        if (data.success) {
            showToast(data.message, 'success', 5000);
        } else {
            showToast(data.message, 'error', 5000);
        }
    } catch (err) {
        if (resultBox) resultBox.innerText = `Error: ${err.message}`;
        showToast(`Error: ${err.message}`, 'error', 5000);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function testProxyManual(btn) {
    const inputEl = document.getElementById('proxy-test-url');
    const proxyUrl = inputEl ? inputEl.value.trim() : '';
    const resultBox = document.getElementById('proxy-test-result');
    if (resultBox) {
        resultBox.style.display = 'block';
        resultBox.innerText = 'Menguji koneksi proxy... Mohon tunggu...';
    }
    if (btn) btn.disabled = true;
    showToast('Menguji koneksi proxy...', 'info', 3000);

    try {
        const res = await fetch('/api/proxy/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_url: proxyUrl || null }),
        });
        const data = await res.json();
        if (resultBox) {
            let output = `HASIL DIAGNOSTIK PROXY:\n`;
            output += `Status: ${data.success ? 'ONLINE & SIAP PAKAI' : 'GAGAL / OFFLINE'}\n`;
            if (data.url) output += `Target: ${data.url}\n`;
            if (data.exit_ip) output += `Public Exit IP: ${data.exit_ip}\n`;
            if (data.latency_ms) output += `Latency/Ping: ${data.latency_ms} ms\n`;
            output += `\nDetail: ${data.message || ''}\n`;
            resultBox.innerText = output;
        }
        if (data.success) {
            showToast(data.message, 'success', 5000);
            loadYtdlpData();
        } else {
            showToast(data.message, 'error', 5000);
        }
    } catch (err) {
        if (resultBox) resultBox.innerText = `Error: ${err.message}`;
        showToast(`Error: ${err.message}`, 'error', 5000);
    } finally {
        if (btn) btn.disabled = false;
    }
}

function openDebugScreenshot(platform = 'youtube') {
    const url = `/api/debug/screenshot/${platform}?t=${Date.now()}`;
    window.open(url, '_blank');
}

async function confirmClearQueue(scope = 'pending') {
    let confirmMsg = 'Yakin ingin mengosongkan antrian stok pending? Video yang belum diproses akan dihapus dari antrian.';
    if (scope === 'all') {
        confirmMsg = '⚠️ PERINGATAN: Reset Total akan menghapus SEMUA antrian stok video dan riwayat posting di Gudang Konten, serta membersihkan file video di server. Yakin ingin melanjutkan?';
    } else if (scope === 'failed') {
        confirmMsg = 'Yakin ingin menghapus semua video yang gagal diproses?';
    }

    if (!confirm(confirmMsg)) return;

    try {
        const res = await fetch('/api/queue/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scope: scope }),
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Stok konten berhasil dibersihkan!', 'success', 5000);
            loadDashboardData(true);
        } else {
            showToast(data.detail || 'Gagal membersihkan antrian konten', 'error', 5000);
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 5000);
    }
}

async function deleteVideoItem(videoId) {
    if (!confirm(`Hapus video #${videoId} dari antrian Gudang Konten?`)) return;

    try {
        const res = await fetch(`/api/videos/${videoId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || `Video #${videoId} berhasil dihapus.`, 'success', 3000);
            loadVideos(currentPage);
            loadDashboardData(true);
        } else {
            showToast(data.detail || 'Gagal menghapus video', 'error', 4000);
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error', 4000);
    }
}

async function testProxyFromConfig() {
    const inputEl = document.getElementById('cfg-proxy-url');
    const proxyUrl = inputEl ? inputEl.value.trim() : '';
    const statusEl = document.getElementById('cfg-proxy-test-result');
    const badgeEl = document.getElementById('cfg-proxy-status-badge');

    if (statusEl) {
        statusEl.style.color = 'var(--accent-amber)';
        statusEl.innerHTML = '<i data-lucide="loader-2" class="spin" style="width:14px;height:14px;vertical-align:middle;"></i> Menguji koneksi proxy...';
        if (window.lucide) lucide.createIcons();
    }

    try {
        const res = await fetch('/api/proxy/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_url: proxyUrl || null }),
        });
        const data = await res.json();
        if (statusEl) {
            if (data.success) {
                statusEl.style.color = 'var(--success)';
                statusEl.innerText = `✅ ONLINE! Exit IP: ${data.exit_ip || '-'} (${data.latency_ms || 0}ms)`;
                if (badgeEl) {
                    badgeEl.className = 'badge-clay badge-done';
                    badgeEl.innerHTML = '<i data-lucide="check-circle" style="width: 12px; height: 12px;"></i> Proxy Online';
                }
            } else {
                statusEl.style.color = '#ef4444';
                statusEl.innerText = `❌ ${data.message || 'Gagal terhubung ke proxy'}`;
                if (badgeEl) {
                    badgeEl.className = 'badge-clay badge-failed';
                    badgeEl.innerHTML = '<i data-lucide="alert-circle" style="width: 12px; height: 12px;"></i> Proxy Offline';
                }
            }
            if (window.lucide) lucide.createIcons();
        }
    } catch (err) {
        if (statusEl) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = `Error: ${err.message}`;
        }
    }
}


