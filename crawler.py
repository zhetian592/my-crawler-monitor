<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>🛡️ 内容安全舆情监控系统</title>
    <style>
        * { box-sizing: border-box; }
        :root {
            --bg-body: #f0f2f5;
            --bg-card: #ffffff;
            --text-primary: #1e2a3a;
            --text-secondary: #555;
            --border: #e0e0e0;
            --link: #1e3a8a;
            --link-hover: #0f2b6d;
            --btn-primary: #1e3a8a;
            --btn-primary-hover: #0f2b6d;
            --btn-danger: #dc3545;
            --btn-danger-hover: #b02a37;
            --btn-history: #28a745;
            --btn-history-hover: #218838;
            --btn-secondary: #6c757d;
            --btn-secondary-hover: #5a6268;
            --table-header-bg: #f8f9fc;
            --banner-bg: #ff9800;
            --banner-text: #fff;
            --error-bg: #ffebee;
            --error-text: #c62828;
            --login-overlay-bg: rgba(0,0,0,0.7);
            --login-card-bg: #fff;
            --login-input-border: #ccc;
        }
        @media (prefers-color-scheme: dark) {
            :root:not(.light-mode):not(.dark-mode) {
                --bg-body: #1a1a2e;
                --bg-card: #16213e;
                --text-primary: #eaeef2;
                --text-secondary: #aaa;
                --border: #2a3a5e;
                --link: #6ea8fe;
                --link-hover: #9ec8ff;
                --btn-primary: #4a6fa5;
                --btn-primary-hover: #6c8ebf;
                --btn-danger: #c82333;
                --btn-danger-hover: #bd2130;
                --btn-history: #2e8b57;
                --btn-history-hover: #3cb371;
                --btn-secondary: #5a6268;
                --btn-secondary-hover: #6c757d;
                --table-header-bg: #1f2a44;
                --banner-bg: #d9661a;
                --banner-text: #f0f0f0;
                --error-bg: #3a1f1f;
                --error-text: #ff8a7a;
                --login-card-bg: #1e2a3a;
                --login-input-border: #4a6fa5;
            }
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--bg-body);
            color: var(--text-primary);
            line-height: 1.5;
            transition: background 0.2s, color 0.2s;
        }
        .container {
            max-width: 1300px;
            margin: 0 auto;
            position: relative;
        }
        .card {
            background: var(--bg-card);
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            padding: 20px 24px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
        }
        h1 {
            font-size: 1.8rem;
            margin-top: 0;
            color: var(--link);
        }
        .info-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 20px;
        }
        .update-time {
            color: var(--text-secondary);
            font-size: 0.9rem;
        }
        button {
            background: var(--btn-primary);
            color: white;
            border: none;
            padding: 6px 14px;
            border-radius: 30px;
            cursor: pointer;
            font-size: 0.85rem;
            transition: 0.2s;
        }
        button:hover {
            background: var(--btn-primary-hover);
        }
        .history-btn {
            background: var(--btn-history);
        }
        .history-btn:hover {
            background: var(--btn-history-hover);
        }
        .danger-btn {
            background: var(--btn-danger);
        }
        .danger-btn:hover {
            background: var(--btn-danger-hover);
        }
        .secondary-btn {
            background: var(--btn-secondary);
        }
        .secondary-btn:hover {
            background: var(--btn-secondary-hover);
        }
        .theme-toggle {
            background: #6c757d;
        }
        .new-report-banner {
            background: var(--banner-bg);
            color: var(--banner-text);
            padding: 12px 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: bold;
        }
        .new-report-banner button {
            background: rgba(0,0,0,0.2);
            padding: 4px 12px;
        }
        .report {
            overflow-x: auto;
            position: relative;
        }
        .report table {
            border-collapse: collapse;
            width: 100%;
            font-size: 14px;
            margin: 16px 0;
        }
        .report th, .report td {
            border: 1px solid var(--border);
            padding: 8px 10px;
            text-align: left;
            vertical-align: top;
        }
        .report th {
            background-color: var(--table-header-bg);
            font-weight: 600;
        }
        .report a {
            color: var(--link);
            text-decoration: none;
        }
        .report a:hover {
            text-decoration: underline;
            color: var(--link-hover);
        }
        .scroll-hint {
            text-align: right;
            font-size: 0.7rem;
            color: var(--text-secondary);
            margin-top: -10px;
            margin-bottom: 10px;
        }
        .loader {
            border: 3px solid var(--border);
            border-top: 3px solid var(--link);
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .stats {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 10px 16px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
            font-size: 0.9rem;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .stats span {
            color: var(--link);
            font-weight: bold;
        }
        .footer-links {
            margin-top: 20px;
            text-align: center;
            font-size: 0.85rem;
            color: var(--text-secondary);
            display: flex;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
        }
        .back-to-top {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: var(--btn-primary);
            color: white;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            cursor: pointer;
            opacity: 0;
            transition: opacity 0.3s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            border: none;
            z-index: 100;
        }
        .back-to-top.show {
            opacity: 0.8;
        }
        .back-to-top:hover {
            opacity: 1;
        }
        .login-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: var(--login-overlay-bg);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            backdrop-filter: blur(5px);
        }
        .login-card {
            background: var(--login-card-bg);
            padding: 30px;
            border-radius: 20px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
            text-align: center;
            width: 300px;
            border: 1px solid var(--border);
        }
        .login-card h2 {
            margin-top: 0;
            color: var(--link);
        }
        .login-card input {
            width: 100%;
            padding: 10px;
            margin: 15px 0;
            border: 1px solid var(--login-input-border);
            border-radius: 8px;
            background: var(--bg-card);
            color: var(--text-primary);
            font-size: 1rem;
        }
        .login-card button {
            width: 100%;
            background: var(--btn-primary);
            color: white;
            border: none;
            padding: 10px;
            border-radius: 30px;
            cursor: pointer;
            font-size: 1rem;
        }
        .error-msg {
            color: var(--error-text);
            margin-top: 10px;
            font-size: 0.9rem;
        }
        @media (max-width: 700px) {
            body { padding: 12px; }
            .card { padding: 16px; }
            .report td, .report th { font-size: 12px; padding: 6px; }
            .back-to-top { width: 36px; height: 36px; font-size: 20px; bottom: 20px; right: 20px; }
            .stats { flex-direction: column; gap: 8px; }
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
</head>
<body>
<div id="app" style="display: none;">
    <div class="container">
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <h1>🛡️ 内容安全行业舆情监控系统</h1>
                <div>
                    <button id="themeToggleBtn" class="theme-toggle" style="margin-right: 8px;">🌓 深色/浅色</button>
                    <button id="logoutBtn" class="secondary-btn" style="margin-left: 8px;">🚪 退出登录</button>
                </div>
            </div>
            <div class="info-bar">
                <div class="update-time">📅 报告时间：<span id="report-time">--</span></div>
                <div>
                    <button id="refresh-btn">🔄 刷新报告</button>
                    <button id="trigger-action-btn" class="danger-btn" style="margin-left: 8px;">🚀 立即更新</button>
                    <button id="history-btn" class="history-btn" style="margin-left: 8px;">📚 历史报告</button>
                    <button id="clearTokenBtn" class="secondary-btn" style="margin-left: 8px;">🗑️ 清除令牌</button>
                </div>
            </div>
            <div id="stats" class="stats" style="display: none;"></div>
            <div id="report-content">
                <div class="loader"></div>
            </div>
            <div class="footer-links">
                <span id="trigger-limit-info"></span>
                <span>⚡ 数据来自定期爬取 | 自动生成涉华负面报告</span>
            </div>
        </div>
    </div>
    <button id="backToTop" class="back-to-top" title="回到顶部">↑</button>
</div>

<script>
    // ---------- 登录验证 ----------
    const PASSWORD = 'yangge233';
    const SESSION_KEY = 'logged_in';

    function checkLogin() {
        if (sessionStorage.getItem(SESSION_KEY) === 'true') {
            document.getElementById('app').style.display = 'block';
            initApp();
        } else {
            showLoginDialog();
        }
    }

    function showLoginDialog() {
        const overlay = document.createElement('div');
        overlay.className = 'login-overlay';
        overlay.innerHTML = `
            <div class="login-card">
                <h2>🔐 系统登录</h2>
                <input type="password" id="passwordInput" placeholder="请输入访问密码" autofocus>
                <button id="loginBtn">确认</button>
                <div id="loginError" class="error-msg"></div>
            </div>
        `;
        document.body.appendChild(overlay);
        const input = overlay.querySelector('#passwordInput');
        const btn = overlay.querySelector('#loginBtn');
        const errorDiv = overlay.querySelector('#loginError');
        const doLogin = () => {
            if (input.value === PASSWORD) {
                sessionStorage.setItem(SESSION_KEY, 'true');
                overlay.remove();
                document.getElementById('app').style.display = 'block';
                initApp();
            } else {
                errorDiv.textContent = '密码错误，请重试。';
                input.value = '';
                input.focus();
            }
        };
        btn.addEventListener('click', doLogin);
        input.addEventListener('keypress', (e) => { if (e.key === 'Enter') doLogin(); });
    }

    // ---------- 应用初始化 ----------
    function initApp() {
        // 主题管理（代码与之前相同，省略详细代码以保持简洁，实际已包含完整功能）
        let currentTheme = localStorage.getItem('theme') || 'auto';
        function setDarkModeVariables() {
            const root = document.documentElement.style;
            root.setProperty('--bg-body', '#1a1a2e');
            root.setProperty('--bg-card', '#16213e');
            root.setProperty('--text-primary', '#eaeef2');
            root.setProperty('--text-secondary', '#aaa');
            root.setProperty('--border', '#2a3a5e');
            root.setProperty('--link', '#6ea8fe');
            root.setProperty('--link-hover', '#9ec8ff');
            root.setProperty('--btn-primary', '#4a6fa5');
            root.setProperty('--btn-primary-hover', '#6c8ebf');
            root.setProperty('--btn-danger', '#c82333');
            root.setProperty('--btn-danger-hover', '#bd2130');
            root.setProperty('--btn-history', '#2e8b57');
            root.setProperty('--btn-history-hover', '#3cb371');
            root.setProperty('--btn-secondary', '#5a6268');
            root.setProperty('--btn-secondary-hover', '#6c757d');
            root.setProperty('--table-header-bg', '#1f2a44');
            root.setProperty('--banner-bg', '#d9661a');
            root.setProperty('--banner-text', '#f0f0f0');
            root.setProperty('--error-bg', '#3a1f1f');
            root.setProperty('--error-text', '#ff8a7a');
            root.setProperty('--login-card-bg', '#1e2a3a');
            root.setProperty('--login-input-border', '#4a6fa5');
        }
        function setLightModeVariables() {
            const root = document.documentElement.style;
            root.setProperty('--bg-body', '#f0f2f5');
            root.setProperty('--bg-card', '#ffffff');
            root.setProperty('--text-primary', '#1e2a3a');
            root.setProperty('--text-secondary', '#555');
            root.setProperty('--border', '#e0e0e0');
            root.setProperty('--link', '#1e3a8a');
            root.setProperty('--link-hover', '#0f2b6d');
            root.setProperty('--btn-primary', '#1e3a8a');
            root.setProperty('--btn-primary-hover', '#0f2b6d');
            root.setProperty('--btn-danger', '#dc3545');
            root.setProperty('--btn-danger-hover', '#b02a37');
            root.setProperty('--btn-history', '#28a745');
            root.setProperty('--btn-history-hover', '#218838');
            root.setProperty('--btn-secondary', '#6c757d');
            root.setProperty('--btn-secondary-hover', '#5a6268');
            root.setProperty('--table-header-bg', '#f8f9fc');
            root.setProperty('--banner-bg', '#ff9800');
            root.setProperty('--banner-text', '#fff');
            root.setProperty('--error-bg', '#ffebee');
            root.setProperty('--error-text', '#c62828');
            root.setProperty('--login-card-bg', '#ffffff');
            root.setProperty('--login-input-border', '#ccc');
        }
        function resetVariablesToCSS() {
            const root = document.documentElement.style;
            root.removeProperty('--bg-body');
            root.removeProperty('--bg-card');
            root.removeProperty('--text-primary');
            root.removeProperty('--text-secondary');
            root.removeProperty('--border');
            root.removeProperty('--link');
            root.removeProperty('--link-hover');
            root.removeProperty('--btn-primary');
            root.removeProperty('--btn-primary-hover');
            root.removeProperty('--btn-danger');
            root.removeProperty('--btn-danger-hover');
            root.removeProperty('--btn-history');
            root.removeProperty('--btn-history-hover');
            root.removeProperty('--btn-secondary');
            root.removeProperty('--btn-secondary-hover');
            root.removeProperty('--table-header-bg');
            root.removeProperty('--banner-bg');
            root.removeProperty('--banner-text');
            root.removeProperty('--error-bg');
            root.removeProperty('--error-text');
            root.removeProperty('--login-card-bg');
            root.removeProperty('--login-input-border');
        }
        function applyTheme() {
            if (currentTheme === 'dark') {
                document.documentElement.classList.add('dark-mode');
                document.documentElement.classList.remove('light-mode');
                setDarkModeVariables();
            } else if (currentTheme === 'light') {
                document.documentElement.classList.add('light-mode');
                document.documentElement.classList.remove('dark-mode');
                setLightModeVariables();
            } else {
                document.documentElement.classList.remove('light-mode', 'dark-mode');
                resetVariablesToCSS();
            }
            localStorage.setItem('theme', currentTheme);
        }
        document.getElementById('themeToggleBtn').addEventListener('click', () => {
            if (currentTheme === 'auto') currentTheme = 'light';
            else if (currentTheme === 'light') currentTheme = 'dark';
            else currentTheme = 'auto';
            applyTheme();
        });
        applyTheme();

        // 退出登录
        document.getElementById('logoutBtn').addEventListener('click', () => {
            sessionStorage.removeItem(SESSION_KEY);
            location.reload();
        });

        // 清除令牌
        document.getElementById('clearTokenBtn').addEventListener('click', () => {
            localStorage.removeItem('github_pat');
            alert('已清除 GitHub 令牌，下次触发任务需重新输入。');
            updateTriggerLimitDisplay();
        });

        // 回到顶部
        const backBtn = document.getElementById('backToTop');
        window.addEventListener('scroll', () => {
            if (window.scrollY > 300) backBtn.classList.add('show');
            else backBtn.classList.remove('show');
        });
        backBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

        // 报告加载与统计（增加内容变化检测）
        let lastReportTime = localStorage.getItem('lastReportTime') || '';
        let lastReportHash = localStorage.getItem('lastReportHash') || '';

        function extractReportTime(markdownText) {
            const match = markdownText.match(/生成时间：([^\n]+)/);
            return match ? match[1].trim() : null;
        }

        function simpleHash(text) {
            return text.slice(0, 200) + text.length;
        }

        async function loadReport(showAlertIfChanged = true) {
            const reportDiv = document.getElementById('report-content');
            reportDiv.innerHTML = '<div class="loader"></div>';
            const statsDiv = document.getElementById('stats');
            if (statsDiv) statsDiv.style.display = 'none';
            try {
                const response = await fetch('https://raw.githubusercontent.com/zhetian592/my-crawler-monitor/main/report.md');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const text = await response.text();
                const currentHash = simpleHash(text);
                const reportTime = extractReportTime(text);
                if (reportTime) document.getElementById('report-time').textContent = reportTime;
                else document.getElementById('report-time').textContent = new Date().toLocaleString();

                let html = marked.parse(text);
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = html;
                tempDiv.querySelectorAll('a').forEach(link => {
                    if (link.href && !link.href.startsWith('#')) {
                        link.setAttribute('target', '_blank');
                        link.setAttribute('rel', 'noopener noreferrer');
                    }
                });
                html = tempDiv.innerHTML;
                reportDiv.innerHTML = `<div class="report">${html}</div>`;

                const tableRows = reportDiv.querySelectorAll('table tbody tr');
                const total = tableRows.length;
                let newCount = 0;
                tableRows.forEach(row => {
                    const firstCell = row.cells[0]?.innerText || '';
                    if (firstCell.includes('🆕')) newCount++;
                });
                if (statsDiv) {
                    statsDiv.style.display = 'flex';
                    statsDiv.innerHTML = `<span>📊 本次报告共 ${total} 条涉华事件</span><span>🆕 其中新增 ${newCount} 条</span>`;
                }

                const isUpdated = (currentHash !== lastReportHash);
                if (isUpdated) {
                    if (showAlertIfChanged) alert('✅ 报告已刷新！');
                    localStorage.setItem('lastReportTime', reportTime || '');
                    localStorage.setItem('lastReportHash', currentHash);
                    lastReportTime = reportTime || '';
                    lastReportHash = currentHash;
                    if (reportTime && lastReportTime !== reportTime && lastReportTime !== '') {
                        if (!document.querySelector('.new-report-banner')) {
                            const banner = document.createElement('div');
                            banner.className = 'new-report-banner';
                            banner.innerHTML = `<span>📢 新舆情报告已生成！（${reportTime}）</span><button onclick="this.parentElement.remove()">关闭</button>`;
                            document.querySelector('.container').insertBefore(banner, document.querySelector('.card'));
                        }
                    }
                } else {
                    if (showAlertIfChanged) {
                        console.log('报告内容未变化，静默刷新');
                    }
                }

                const reportContainer = reportDiv.querySelector('.report');
                if (reportContainer && reportContainer.scrollWidth > reportContainer.clientWidth) {
                    if (!reportDiv.querySelector('.scroll-hint')) {
                        const hint = document.createElement('div');
                        hint.className = 'scroll-hint';
                        hint.innerHTML = '👉 表格较宽，可左右滑动 👈';
                        reportDiv.insertBefore(hint, reportDiv.firstChild);
                    }
                }
            } catch (err) {
                reportDiv.innerHTML = `<div style="color: var(--error-text); background: var(--error-bg); padding: 20px; border-radius: 12px;">
                    <strong>⚠️ 加载失败</strong><br>${err.message}<br><br>
                    <button onclick="loadReport()">🔄 重试</button>
                    <p style="margin-top: 12px;">👉 请确认 <strong>report.md</strong> 文件已生成。<br>
                    若尚未运行爬虫，请点击上方“立即更新”按钮触发任务。</p>
                </div>`;
                alert(`❌ 报告刷新失败：${err.message}`);
            }
        }

        // 每日触发次数限制（已修改为10次）
        const MAX_TRIGGERS_PER_DAY = 10;
        const GITHUB_TOKEN_KEY = 'github_pat';
        const REPO_OWNER = 'zhetian592';
        const REPO_NAME = 'my-crawler-monitor';
        const WORKFLOW_ID = 'crawler-tier1.yml';

        function getTodayKey() {
            return new Date().toISOString().slice(0, 10);
        }
        function canTriggerToday() {
            const today = getTodayKey();
            const stored = localStorage.getItem('trigger_counts');
            let counts = {};
            if (stored) {
                try { counts = JSON.parse(stored); } catch(e) {}
            }
            const todayCount = counts[today] || 0;
            return todayCount < MAX_TRIGGERS_PER_DAY;
        }
        function incrementTriggerCount() {
            const today = getTodayKey();
            const stored = localStorage.getItem('trigger_counts');
            let counts = {};
            if (stored) {
                try { counts = JSON.parse(stored); } catch(e) {}
            }
            counts[today] = (counts[today] || 0) + 1;
            localStorage.setItem('trigger_counts', JSON.stringify(counts));
            updateTriggerLimitDisplay();
        }
        function updateTriggerLimitDisplay() {
            const today = getTodayKey();
            const stored = localStorage.getItem('trigger_counts');
            let counts = {};
            if (stored) {
                try { counts = JSON.parse(stored); } catch(e) {}
            }
            const used = counts[today] || 0;
            const remaining = MAX_TRIGGERS_PER_DAY - used;
            const infoSpan = document.getElementById('trigger-limit-info');
            if (infoSpan) {
                infoSpan.textContent = `今日还可手动触发 ${remaining} 次`;
            }
        }
        async function triggerWorkflow() {
            if (!canTriggerToday()) {
                alert(`已达到今日手动触发上限（${MAX_TRIGGERS_PER_DAY}次）。请明天再试，或等待自动任务执行。`);
                return;
            }
            let token = localStorage.getItem(GITHUB_TOKEN_KEY);
            if (!token) {
                token = prompt('请输入你的 GitHub Personal Access Token (需要 repo 权限)：\n生成地址：https://github.com/settings/tokens\n注意：令牌将保存在浏览器本地，不会上传。');
                if (!token) return;
                localStorage.setItem(GITHUB_TOKEN_KEY, token);
            }
            const btn = document.getElementById('trigger-action-btn');
            const originalText = btn.innerText;
            btn.innerText = '⏳ 触发中...';
            btn.disabled = true;
            try {
                const response = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Accept': 'application/vnd.github.v3+json',
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ ref: 'main' })
                });
                if (response.ok) {
                    incrementTriggerCount();
                    alert('✅ 已触发爬虫任务！\n请稍等几分钟，然后点击“刷新报告”查看结果。');
                } else {
                    const error = await response.json();
                    if (response.status === 401 || response.status === 403) {
                        localStorage.removeItem(GITHUB_TOKEN_KEY);
                        alert('令牌无效或已过期，请重新输入。');
                    } else {
                        alert(`❌ 触发失败 (${response.status}): ${error.message || '未知错误'}`);
                    }
                }
            } catch (err) {
                alert(`网络错误：${err.message}`);
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }

        async function openHistory() {
            const btn = document.getElementById('history-btn');
            const originalText = btn.innerText;
            btn.innerText = '⏳ 检查中...';
            btn.disabled = true;
            try {
                const response = await fetch('https://raw.githubusercontent.com/zhetian592/my-crawler-monitor/main/reports/index.html');
                if (response.ok) {
                    window.open('reports/index.html', '_blank');
                } else {
                    alert('历史报告目录尚未生成。请先运行爬虫任务，生成至少一份报告后再查看历史。');
                }
            } catch (err) {
                alert('无法访问历史报告目录。请确认爬虫已成功运行并提交了 reports/ 目录。');
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }

        document.getElementById('refresh-btn').addEventListener('click', () => loadReport(true));
        document.getElementById('trigger-action-btn').addEventListener('click', triggerWorkflow);
        document.getElementById('history-btn').addEventListener('click', openHistory);
        updateTriggerLimitDisplay();
        // 首次加载不弹窗（静默）
        loadReport(false);
    }

    checkLogin();
</script>
</body>
</html>
