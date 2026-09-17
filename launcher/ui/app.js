// ============================================================
// Sin'X Automation — Desktop Client JavaScript Application
// ============================================================

let currentConfig = {
    server_url: 'https://auto.kntl.cc',
    username: '',
    token: '',
    is_authenticated: false,
    proxy_enabled: false,
    proxy_url: ''
};

let eventSource = null;
let pollTimer = null;

// Wait for PyWebView bridge to initialize
window.addEventListener('pywebviewready', () => {
    console.log('PyWebView bridge ready');
    initApp();
});

// Fallback init in case run directly in browser for UI preview
document.addEventListener('DOMContentLoaded', () => {
    if (!window.pywebview) {
        console.warn('PyWebView not detected, waiting or fallback to preview mode.');
        setTimeout(() => {
            if (!window.pywebview) {
                console.log('Running in browser preview mode');
                lucide.createIcons();
            }
        }, 800);
    }
});

async function initApp() {
    try {
        const state = await window.pywebview.api.get_initial_state();
        currentConfig = Object.assign(currentConfig, state);

        const authUrlInput = document.getElementById('auth-server-url');
        const authUserInput = document.getElementById('auth-username');
        const setUrlInput = document.getElementById('setting-server-url');
        const setUserInput = document.getElementById('setting-username');
        const proxyEnabledCheck = document.getElementById('setting-proxy-enabled');
        const proxyUrlInput = document.getElementById('setting-proxy-url');

        if (authUrlInput && currentConfig.server_url) authUrlInput.value = currentConfig.server_url;
        if (authUserInput && currentConfig.username) authUserInput.value = currentConfig.username;
        if (setUrlInput && currentConfig.server_url) setUrlInput.value = currentConfig.server_url;
        if (setUserInput && currentConfig.username) setUserInput.value = currentConfig.username;
        if (proxyEnabledCheck && currentConfig.proxy_enabled !== undefined) {
            proxyEnabledCheck.checked = Boolean(currentConfig.proxy_enabled);
        }
        if (proxyUrlInput && currentConfig.proxy_url) {
            proxyUrlInput.value = currentConfig.proxy_url;
        }

        if (currentConfig.is_authenticated && currentConfig.token) {
            setAuthenticatedState(true);
        } else {
            setAuthenticatedState(false);
        }
        lucide.createIcons();
    } catch (e) {
        console.error('Error during initApp:', e);
        showToast('Gagal memuat status awal: ' + e, 'error');
    }
}

function setAuthenticatedState(isAuth) {
    const authGate = document.getElementById('auth-gate-page');
    const navBar = document.getElementById('nav-bar-container');
    const btnLogout = document.getElementById('btn-nav-logout');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    if (isAuth) {
        authGate.style.display = 'none';
        navBar.style.display = 'block';
        btnLogout.style.display = 'flex';
        statusDot.className = 'status-dot online';
        statusText.innerText = currentConfig.username ? `${currentConfig.username} (Online)` : 'Connected';

        // Switch to dash tab
        switchTab('dash', document.getElementById('tab-btn-dash'));
        refreshDashboardData();

        // Start auto-refresh interval
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(refreshDashboardData, 10000);

        // Connect SSE logs
        startLogStream();
    } else {
        authGate.style.display = 'flex';
        navBar.style.display = 'none';
        btnLogout.style.display = 'none';
        statusDot.className = 'status-dot';
        statusText.innerText = 'Disconnected';

        // Hide all tabs
        document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));

        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        stopLogStream();
    }
    lucide.createIcons();
}

// ─────────────────────────────────────────────────────────────
// Auth Functions (Login / Logout)
// ─────────────────────────────────────────────────────────────
async function doLogin() {
    const url = document.getElementById('auth-server-url').value.trim();
    const user = document.getElementById('auth-username').value.trim();
    const pass = document.getElementById('auth-password').value.trim();
    const btn = document.getElementById('btn-do-login');

    if (!url) {
        showToast('Server URL tidak boleh kosong!', 'error');
        return;
    }
    if (!user || !pass) {
        showToast('Masukkan username dan password!', 'error');
        return;
    }

    const origHtml = btn.innerHTML;
    btn.innerHTML = '<span>Menghubungi Server...</span>';
    btn.style.opacity = '0.7';
    btn.style.pointerEvents = 'none';

    try {
        const res = await window.pywebview.api.login(url, user, pass);
        if (res.success) {
            currentConfig.server_url = url;
            currentConfig.username = user;
            currentConfig.token = res.token;
            currentConfig.is_authenticated = true;

            const setUserInput = document.getElementById('setting-username');
            const setUrlInput = document.getElementById('setting-server-url');
            if (setUserInput) setUserInput.value = user;
            if (setUrlInput) setUrlInput.value = url;

            showToast(res.message || 'Login berhasil!', 'success');
            setAuthenticatedState(true);
        } else {
            showToast(res.error || 'Login gagal. Periksa username/password.', 'error');
        }
    } catch (e) {
        showToast('Error login: ' + e, 'error');
    } finally {
        btn.innerHTML = origHtml;
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
        lucide.createIcons();
    }
}

async function doLogout() {
    if (!confirm('Apakah Anda yakin ingin logout dari sesi desktop?')) return;
    try {
        await window.pywebview.api.logout();
        currentConfig.token = '';
        currentConfig.is_authenticated = false;
        setAuthenticatedState(false);
        showToast('Anda telah logout.', 'info');
    } catch (e) {
        showToast('Error logout: ' + e, 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// Tab Navigation
// ─────────────────────────────────────────────────────────────
function switchTab(tabId, el) {
    document.querySelectorAll('.nav-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));

    if (el) el.classList.add('active');
    const target = document.getElementById(`view-${tabId}`);
    if (target) target.classList.add('active');

    if (tabId === 'dash') {
        refreshDashboardData();
    }
    lucide.createIcons();
}

// ─────────────────────────────────────────────────────────────
// Dashboard Data Refresh
// ─────────────────────────────────────────────────────────────
async function refreshDashboardData() {
    if (!currentConfig.is_authenticated) return;
    try {
        const data = await window.pywebview.api.get_dashboard_stats();
        if (!data || data.error) {
            console.warn('Stats fetch warning:', data ? data.error : 'Empty data');
            return;
        }

        const stats = data.queue_stats || {};
        const by_st = stats.by_status || {};
        const sch = data.scheduler || {};

        const total = stats.total ?? 0;
        const ready = stats.pending ?? by_st.pending ?? 0;
        const proc = stats.processing ?? ((by_st.downloading || 0) + (by_st.rendering || 0) + (by_st.uploading || 0));
        const done = stats.done ?? ((by_st.done || 0) + (by_st.published || 0));
        const fail = stats.failed ?? ((by_st.failed || 0) + (by_st.error || 0));

        document.getElementById('stat-total').innerText = total;
        document.getElementById('stat-ready').innerText = ready;
        document.getElementById('stat-proc').innerText = proc;
        document.getElementById('stat-done').innerText = done;
        document.getElementById('stat-fail').innerText = fail;

        const nextSlot = sch.next_slot || '-';
        const rem = sch.remaining_seconds || 0;
        const remStr = rem > 0 ? ` (${Math.floor(rem / 3600)}j ${Math.floor((rem % 3600) / 60)}m lagi)` : '';
        const slotsStr = (sch.slots || []).join(', ') || '-';
        const tzStr = `${sch.timezone || 'Asia/Jakarta'} (${sch.timezone_abbr || 'WIB'}) — Jam Server: ${sch.current_time || '-'}`;

        document.getElementById('dash-sch-next').innerText = `Jadwal Berikutnya: ${nextSlot}${remStr}`;
        document.getElementById('dash-sch-slots').innerText = `Jam Tayang Aktif: ${slotsStr}`;
        document.getElementById('dash-sch-tz').innerText = `Timezone Acuan: ${tzStr}`;
    } catch (e) {
        console.error('Error refreshing stats:', e);
    }
}

// ─────────────────────────────────────────────────────────────
// Cookies & Profile Actions
// ─────────────────────────────────────────────────────────────
function onPlatformChange() {
    const sel = document.getElementById('sel-cookie-platform');
    const custom = document.getElementById('input-cookie-target');
    if (!custom.value.trim()) {
        custom.placeholder = `Default: ${sel.value}`;
    }
}

function getActivePlatformAndTarget() {
    const platform = document.getElementById('sel-cookie-platform').value;
    const customTarget = document.getElementById('input-cookie-target').value.trim();
    const target = customTarget || platform;
    return { platform, target };
}

async function startLocalBrowserLogin() {
    const { platform, target } = getActivePlatformAndTarget();
    showToast(`Membuka browser lokal untuk login ${platform}...`, 'info');
    try {
        const res = await window.pywebview.api.launch_local_browser(platform, target);
        if (res.success) {
            showToast(res.message || 'Login browser selesai!', 'success');
        } else {
            showToast(res.error || 'Browser login dibatalkan atau gagal.', 'error');
        }
    } catch (e) {
        showToast('Error browser login: ' + e, 'error');
    }
}

async function pickAndUploadCookieFile() {
    const { platform, target } = getActivePlatformAndTarget();
    showToast('Membuka file picker cookie...', 'info');
    try {
        const res = await window.pywebview.api.pick_and_upload_cookie(platform, target);
        if (res.success) {
            showToast(res.message || 'Cookie berhasil diupload!', 'success');
        } else if (res.cancelled) {
            // Pemilihan dibatalkan user
        } else {
            showToast(res.error || 'Gagal upload cookie.', 'error');
        }
    } catch (e) {
        showToast('Error upload cookie: ' + e, 'error');
    }
}

async function pickAndUploadProfileZip() {
    const { platform, target } = getActivePlatformAndTarget();
    showToast('Membuka file picker arsip profil zip...', 'info');
    try {
        const res = await window.pywebview.api.pick_and_upload_zip(platform, target);
        if (res.success) {
            showToast(res.message || 'Profil ZIP berhasil diupload!', 'success');
        } else if (res.cancelled) {
            // Pemilihan dibatalkan user
        } else {
            showToast(res.error || 'Gagal upload profil.', 'error');
        }
    } catch (e) {
        showToast('Error upload zip: ' + e, 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// Realtime Live Logs Stream
// ─────────────────────────────────────────────────────────────
function startLogStream() {
    stopLogStream();
    if (!currentConfig.server_url || !currentConfig.token) return;

    const base = currentConfig.server_url.replace(/\/+$/, '');
    const url = `${base}/api/logs/stream?token=${encodeURIComponent(currentConfig.token)}`;

    try {
        eventSource = new EventSource(url);
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.action === 'clear') {
                    const terminal = document.getElementById('log-terminal');
                    if (terminal) terminal.innerHTML = '';
                    appendLogToTerminal(new Date().toLocaleTimeString(), 'INFO', '--- Log dibersihkan oleh server ---');
                    return;
                }
                const msg = data.message || data.line || JSON.stringify(data);
                const lvl = (data.level || 'INFO').toUpperCase();
                appendLogToTerminal(new Date().toLocaleTimeString(), lvl, msg);
            } catch (err) {
                appendLogToTerminal(new Date().toLocaleTimeString(), 'INFO', event.data);
            }
        };

        eventSource.onerror = (err) => {
            console.warn('SSE stream reconnecting...');
        };
    } catch (e) {
        console.error('Failed to init EventSource:', e);
    }
}

function stopLogStream() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

function appendLogToTerminal(timeStr, level, text) {
    const terminal = document.getElementById('log-terminal');
    if (!terminal) return;

    const line = document.createElement('div');
    line.className = 'log-line';

    let levelClass = 'log-level-INFO';
    if (level.includes('WARN')) levelClass = 'log-level-WARN';
    else if (level.includes('ERR') || level.includes('FAIL')) levelClass = 'log-level-ERROR';
    else if (level.includes('SUCC')) levelClass = 'log-level-SUCCESS';

    line.innerHTML = `<span class="log-time">[${timeStr}]</span> <span class="${levelClass}">${escapeHtml(text)}</span>`;
    terminal.appendChild(line);

    // Limit buffer to 500 lines to prevent DOM bloat
    if (terminal.childNodes.length > 500) {
        terminal.removeChild(terminal.firstChild);
    }

    const autoScroll = document.getElementById('chk-log-autoscroll');
    if (autoScroll && autoScroll.checked) {
        terminal.scrollTop = terminal.scrollHeight;
    }
}

async function clearLiveLogs() {
    try {
        const res = await window.pywebview.api.clear_logs();
        const terminal = document.getElementById('log-terminal');
        if (terminal) terminal.innerHTML = '';
        if (res.success) {
            showToast('Log server berhasil dibersihkan!', 'success');
        } else {
            showToast(res.error || 'Gagal membersihkan log server.', 'error');
        }
    } catch (e) {
        showToast('Error clear logs: ' + e, 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// Modals: On-Demand Publish & Screenshot
// ─────────────────────────────────────────────────────────────
function openPublishModal() {
    document.getElementById('modal-publish').style.display = 'flex';
    lucide.createIcons();
}

function openScreenshotModal() {
    document.getElementById('modal-screenshot').style.display = 'flex';
    lucide.createIcons();
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

async function confirmPublishNow() {
    const target = document.getElementById('sel-modal-publish-target').value;
    closeModal('modal-publish');
    showToast(`Memicu On-Demand Publish untuk '${target}'...`, 'info');

    // Switch to logs tab to view progress
    switchTab('logs', document.getElementById('tab-btn-logs'));

    try {
        const res = await window.pywebview.api.trigger_publish(target);
        if (res.success) {
            showToast(res.message || 'Publikasi berhasil dimulai!', 'success');
            refreshDashboardData();
        } else {
            showToast(res.error || 'Gagal memulai publikasi.', 'error');
        }
    } catch (e) {
        showToast('Error publish: ' + e, 'error');
    }
}

async function confirmOpenScreenshot() {
    const platform = document.getElementById('sel-modal-screenshot-platform').value;
    closeModal('modal-screenshot');
    showToast(`Membuka screenshot debug ${platform}...`, 'info');
    try {
        await window.pywebview.api.open_debug_screenshot(platform);
    } catch (e) {
        showToast('Error open screenshot: ' + e, 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// Settings & System Actions
// ─────────────────────────────────────────────────────────────
async function saveSettings() {
    const newUrl = document.getElementById('setting-server-url').value.trim();
    if (!newUrl) {
        showToast('Server URL tidak boleh kosong!', 'error');
        return;
    }
    try {
        const res = await window.pywebview.api.save_server_url(newUrl);
        if (res.success) {
            currentConfig.server_url = newUrl;
            document.getElementById('auth-server-url').value = newUrl;
            showToast('Konfigurasi URL server disimpan!', 'success');
        } else {
            showToast(res.error || 'Gagal menyimpan URL.', 'error');
        }
    } catch (e) {
        showToast('Error saving settings: ' + e, 'error');
    }
}

async function saveProxySettings() {
    const enabled = document.getElementById('setting-proxy-enabled').checked;
    const proxyUrl = document.getElementById('setting-proxy-url').value.trim();

    if (enabled && !proxyUrl) {
        showToast('Masukkan URL proxy jika ingin mengaktifkannya!', 'error');
        return;
    }

    try {
        const res = await window.pywebview.api.save_proxy(enabled, proxyUrl);
        if (res.success) {
            currentConfig.proxy_enabled = enabled;
            currentConfig.proxy_url = proxyUrl;
            showToast(res.message || 'Pengaturan proxy pribadi disimpan!', 'success');
        } else {
            showToast(res.error || 'Gagal menyimpan proxy.', 'error');
        }
    } catch (e) {
        showToast('Error save proxy: ' + e, 'error');
    }
}

async function testProxy() {
    const proxyUrl = document.getElementById('setting-proxy-url').value.trim();
    const resultBox = document.getElementById('proxy-test-result');
    const btn = document.getElementById('btn-test-proxy');

    if (!proxyUrl) {
        showToast('Masukkan URL proxy terlebih dahulu untuk diuji!', 'error');
        return;
    }

    const origHtml = btn.innerHTML;
    btn.innerHTML = '<span>Menguji Proxy...</span>';
    btn.style.pointerEvents = 'none';
    btn.style.opacity = '0.7';

    resultBox.style.display = 'block';
    resultBox.style.background = 'rgba(56, 189, 248, 0.15)';
    resultBox.style.border = '1px solid rgba(56, 189, 248, 0.3)';
    resultBox.style.color = '#38bdf8';
    resultBox.innerText = 'Menghubungi layanan tes IP publik via proxy...';

    try {
        const res = await window.pywebview.api.test_proxy(proxyUrl);
        if (res.success) {
            resultBox.style.background = 'rgba(16, 185, 129, 0.15)';
            resultBox.style.border = '1px solid rgba(16, 185, 129, 0.3)';
            resultBox.style.color = '#34d399';
            resultBox.innerText = `✓ ${res.message}`;
            showToast('Proxy valid & aktif!', 'success');
        } else {
            resultBox.style.background = 'rgba(239, 68, 68, 0.15)';
            resultBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            resultBox.style.color = '#f87171';
            resultBox.innerText = `✗ ${res.error}`;
            showToast('Tes proxy gagal: ' + res.error, 'error');
        }
    } catch (e) {
        resultBox.style.background = 'rgba(239, 68, 68, 0.15)';
        resultBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
        resultBox.style.color = '#f87171';
        resultBox.innerText = `✗ Error: ${e}`;
        showToast('Error tes proxy: ' + e, 'error');
    } finally {
        btn.innerHTML = origHtml;
        btn.style.pointerEvents = 'auto';
        btn.style.opacity = '1';
        lucide.createIcons();
    }
}

async function checkUpdates(manual = false) {
    showToast('Memeriksa pembaruan versi...', 'info');
    try {
        const res = await window.pywebview.api.check_updates(manual);
        if (res.has_update) {
            if (confirm(`Pembaruan Baru Tersedia!\n\nVersi server: ${res.remote_version}\nVersi lokal: ${res.current_version}\n\nCatatan:\n${res.changelog}\n\nUnduh pembaruan sekarang?`)) {
                window.pywebview.api.download_latest_exe();
            }
        } else if (manual) {
            showToast('Aplikasi Anda sudah versi terbaru!', 'success');
        }
    } catch (e) {
        showToast('Error cek update: ' + e, 'error');
    }
}

async function downloadLatestExe() {
    showToast('Membuka tautan unduhan Sin\'X Launcher...', 'info');
    try {
        await window.pywebview.api.download_latest_exe();
    } catch (e) {
        showToast('Error download: ' + e, 'error');
    }
}

// ─────────────────────────────────────────────────────────────
// Helper Utilities: Toasts & HTML Escaping
// ─────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function escapeHtml(text) {
    if (!text) return '';
    return text.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
