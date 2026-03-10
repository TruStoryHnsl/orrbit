/* Orrbit settings.js — settings page logic */

(function() {
    'use strict';

    // --- Helpers ---

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            for (var k in attrs) {
                if (k === 'className') node.className = attrs[k];
                else if (k === 'textContent') node.textContent = attrs[k];
                else node.setAttribute(k, attrs[k]);
            }
        }
        if (children) {
            var list = Array.isArray(children) ? children : [children];
            for (var i = 0; i < list.length; i++) {
                if (typeof list[i] === 'string') node.appendChild(document.createTextNode(list[i]));
                else if (list[i]) node.appendChild(list[i]);
            }
        }
        return node;
    }

    function showStatus(id, msg, isError) {
        var span = document.getElementById(id);
        if (!span) return;
        span.textContent = msg;
        span.className = 'save-status ' + (isError ? 'status-error' : 'status-success');
        setTimeout(function() { span.textContent = ''; span.className = 'save-status'; }, 3000);
    }

    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    async function api(url, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        opts.headers['X-CSRFToken'] = csrfToken;
        if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(opts.body);
        }
        var resp = await fetch(url, opts);
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Request failed');
        return data;
    }

    // --- Section collapse/expand ---

    document.querySelectorAll('.settings-section-title').forEach(function(title) {
        title.addEventListener('click', function() {
            var body = this.nextElementSibling;
            var arrow = this.querySelector('.section-arrow');
            body.classList.toggle('collapsed');
            arrow.textContent = body.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
        });
    });

    // --- Load settings ---

    var settingsData = null;

    async function loadSettings() {
        try {
            settingsData = await api('/api/settings');
            populateGeneral(settingsData.general);
            renderThemes(settingsData.theme);
            renderDirectories(settingsData.directories);
            renderUsers(settingsData.users);
            populateIndexer(settingsData.indexer);
            populateSftp(settingsData.sftp);
            populateThumbnails(settingsData.thumbnails);
        } catch (err) {
            console.error('Failed to load settings:', err);
        }
    }

    function populateGeneral(g) {
        document.getElementById('setting-app-name').value = g.app_name || '';
        document.getElementById('setting-tab-title').value = g.tab_title || '';
        document.getElementById('setting-tab-subtitle').checked = !!g.tab_subtitle;
        var portInput = document.getElementById('setting-port');
        portInput.value = g.port || 5000;
        portInput.dataset.original = portInput.value;
        portInput.addEventListener('input', function() {
            var badge = document.getElementById('port-restart-badge');
            if (badge) badge.hidden = (portInput.value === portInput.dataset.original);
        });
        document.getElementById('setting-max-upload').value = g.max_upload_mb || 500;
        document.getElementById('setting-data-dir').textContent = g.data_dir || '';
    }

    // --- Theme ---

    function applyTheme(themeId) {
        var html = document.documentElement;
        if (themeId === 'midnight') {
            html.removeAttribute('data-theme');
        } else {
            html.setAttribute('data-theme', themeId);
        }

        // Load/remove third-party theme CSS
        var existing = document.getElementById('third-party-theme');
        if (existing) existing.remove();

        // Built-in themes don't need extra CSS
        var builtins = ['midnight', 'slate', 'oled', 'dawn'];
        if (builtins.indexOf(themeId) === -1) {
            var link = document.createElement('link');
            link.id = 'third-party-theme';
            link.rel = 'stylesheet';
            link.href = '/static/themes/' + encodeURIComponent(themeId) + '.css';
            document.head.appendChild(link);
        }
    }

    function renderThemes(themeData) {
        var grid = document.getElementById('theme-grid');
        grid.textContent = '';
        var current = themeData.current;
        var themes = themeData.available;

        for (var i = 0; i < themes.length; i++) {
            var t = themes[i];
            var card = el('div', {className: 'theme-card' + (t.id === current ? ' active' : '')});
            card.dataset.themeId = t.id;

            card.appendChild(el('div', {className: 'theme-card-name', textContent: t.name}));

            if (t.colors && t.colors.length) {
                var swatches = el('div', {className: 'theme-card-swatches'});
                for (var j = 0; j < t.colors.length; j++) {
                    var swatch = el('div', {className: 'theme-swatch'});
                    swatch.style.backgroundColor = t.colors[j];
                    swatches.appendChild(swatch);
                }
                card.appendChild(swatches);
            }

            if (!t.builtin) {
                card.appendChild(el('span', {className: 'theme-card-badge', textContent: 'custom'}));
            }

            card.addEventListener('click', function() {
                var id = this.dataset.themeId;
                // Visual feedback immediately
                grid.querySelectorAll('.theme-card').forEach(function(c) {
                    c.classList.toggle('active', c.dataset.themeId === id);
                });
                applyTheme(id);

                // Persist
                api('/api/settings/theme', {method: 'POST', body: {theme: id}})
                    .then(function() { showStatus('theme-status', 'Theme applied', false); })
                    .catch(function(e) { showStatus('theme-status', e.message, true); });
            });

            grid.appendChild(card);
        }
    }

    // --- Directories ---

    function renderDirectories(dirs) {
        var list = document.getElementById('directories-list');
        list.textContent = '';
        if (!dirs || !dirs.length) {
            list.appendChild(el('div', {className: 'empty-state', textContent: 'No directories configured'}));
            return;
        }
        for (var i = 0; i < dirs.length; i++) {
            var d = dirs[i];
            var row = el('div', {className: 'settings-row'});

            var info = el('div', {className: 'settings-row-info'});
            info.appendChild(el('span', {className: 'settings-row-name', textContent: d.name}));
            info.appendChild(el('span', {className: 'settings-row-detail', textContent: d.path}));
            if (!d.valid) {
                info.appendChild(el('span', {className: 'restart-badge', textContent: 'invalid path'}));
            }
            row.appendChild(info);

            var actions = el('div', {className: 'settings-row-actions'});
            var rmBtn = el('button', {className: 'btn btn-sm btn-danger', textContent: 'Remove'});
            rmBtn.dataset.slug = d.slug;
            rmBtn.addEventListener('click', function() {
                var slug = this.dataset.slug;
                if (!confirm('Remove directory "' + slug + '"? Its index entries will be deleted.')) return;
                api('/api/settings/directories/' + encodeURIComponent(slug), {method: 'DELETE'})
                    .then(function() {
                        showStatus('dir-status', 'Removed', false);
                        loadSettings();
                    })
                    .catch(function(e) { showStatus('dir-status', e.message, true); });
            });
            actions.appendChild(rmBtn);
            row.appendChild(actions);
            list.appendChild(row);
        }
    }

    document.getElementById('add-directory').addEventListener('click', function() {
        var name = document.getElementById('new-dir-name').value.trim();
        var path = document.getElementById('new-dir-path').value.trim();
        if (!name || !path) { showStatus('dir-status', 'Name and path required', true); return; }

        api('/api/settings/directories', {method: 'POST', body: {name: name, path: path}})
            .then(function() {
                document.getElementById('new-dir-name').value = '';
                document.getElementById('new-dir-path').value = '';
                showStatus('dir-status', 'Added', false);
                loadSettings();
            })
            .catch(function(e) { showStatus('dir-status', e.message, true); });
    });

    // --- Users ---

    function renderUsers(users) {
        var list = document.getElementById('users-list');
        list.textContent = '';
        if (!users || !users.length) {
            list.appendChild(el('div', {className: 'empty-state', textContent: 'No users'}));
            return;
        }
        for (var i = 0; i < users.length; i++) {
            var u = users[i];
            var row = el('div', {className: 'settings-row'});

            var info = el('div', {className: 'settings-row-info'});
            var nameText = u.username + (u.is_current ? ' (you)' : '');
            info.appendChild(el('span', {className: 'settings-row-name', textContent: nameText}));
            row.appendChild(info);

            var actions = el('div', {className: 'settings-row-actions'});

            // Change password button
            var pwBtn = el('button', {className: 'btn btn-sm', textContent: 'Change Password'});
            pwBtn.dataset.uid = u.id;
            pwBtn.dataset.username = u.username;
            pwBtn.addEventListener('click', function() {
                var uid = this.dataset.uid;
                var username = this.dataset.username;
                showPasswordForm(uid, username, this.closest('.settings-row'));
            });
            actions.appendChild(pwBtn);

            // Delete button (disabled for self)
            if (!u.is_current) {
                var delBtn = el('button', {className: 'btn btn-sm btn-danger', textContent: 'Delete'});
                delBtn.dataset.uid = u.id;
                delBtn.dataset.username = u.username;
                delBtn.addEventListener('click', function() {
                    var uid = this.dataset.uid;
                    var username = this.dataset.username;
                    if (!confirm('Delete user "' + username + '"?')) return;
                    api('/api/settings/users/' + uid, {method: 'DELETE'})
                        .then(function() {
                            showStatus('user-status', 'Deleted', false);
                            loadSettings();
                        })
                        .catch(function(e) { showStatus('user-status', e.message, true); });
                });
                actions.appendChild(delBtn);
            }

            row.appendChild(actions);
            list.appendChild(row);
        }
    }

    function showPasswordForm(uid, username, rowEl) {
        // Don't add if already showing
        if (rowEl.querySelector('.inline-password-form')) return;

        var form = el('div', {className: 'inline-password-form'});
        var input = el('input', {type: 'password', placeholder: 'New password', className: 'inline-input'});
        var saveBtn = el('button', {className: 'btn btn-primary btn-sm', textContent: 'Save'});
        var cancelBtn = el('button', {className: 'btn btn-sm', textContent: 'Cancel'});

        saveBtn.addEventListener('click', function() {
            var pw = input.value;
            if (!pw || pw.length < 4) { showStatus('user-status', 'Password must be 4+ chars', true); return; }
            api('/api/settings/users/' + uid, {method: 'PUT', body: {password: pw}})
                .then(function() {
                    form.remove();
                    showStatus('user-status', 'Password changed for ' + username, false);
                })
                .catch(function(e) { showStatus('user-status', e.message, true); });
        });

        cancelBtn.addEventListener('click', function() { form.remove(); });

        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') saveBtn.click();
            if (e.key === 'Escape') cancelBtn.click();
        });

        form.appendChild(input);
        form.appendChild(saveBtn);
        form.appendChild(cancelBtn);
        rowEl.appendChild(form);
        input.focus();
    }

    document.getElementById('add-user').addEventListener('click', function() {
        var username = document.getElementById('new-user-name').value.trim();
        var password = document.getElementById('new-user-pass').value;
        if (!username || !password) { showStatus('user-status', 'Username and password required', true); return; }

        api('/api/settings/users', {method: 'POST', body: {username: username, password: password}})
            .then(function() {
                document.getElementById('new-user-name').value = '';
                document.getElementById('new-user-pass').value = '';
                showStatus('user-status', 'User added', false);
                loadSettings();
            })
            .catch(function(e) { showStatus('user-status', e.message, true); });
    });

    // --- General save ---

    document.getElementById('save-general').addEventListener('click', function() {
        var body = {
            app_name: document.getElementById('setting-app-name').value.trim(),
            tab_title: document.getElementById('setting-tab-title').value.trim(),
            tab_subtitle: document.getElementById('setting-tab-subtitle').checked,
            port: parseInt(document.getElementById('setting-port').value, 10),
            max_upload_mb: parseInt(document.getElementById('setting-max-upload').value, 10),
        };

        api('/api/settings/general', {method: 'POST', body: body})
            .then(function(data) {
                var msg = 'Saved';
                if (data.requires_restart && data.requires_restart.length) {
                    msg += ' (restart required for: ' + data.requires_restart.join(', ') + ')';
                }
                showStatus('general-status', msg, false);

                // Update navbar logo and page title live
                var logo = document.querySelector('.app-logo');
                if (logo) logo.textContent = body.app_name;
                var base = body.tab_title || body.app_name;
                document.title = body.tab_subtitle ? 'Settings \u2014 ' + base : base;
            })
            .catch(function(e) { showStatus('general-status', e.message, true); });
    });

    // --- Indexer ---

    function populateIndexer(idx) {
        document.getElementById('setting-indexer-enabled').checked = idx.enabled;
        document.getElementById('setting-indexer-interval').value = idx.interval;

        var stats = document.getElementById('indexer-stats');
        stats.textContent = '';
        var s = idx.status;
        stats.appendChild(el('div', {className: 'indexer-stat'}, [
            el('div', {className: 'stat-label', textContent: 'Status'}),
            el('div', {className: 'stat-value ' + (s.running ? 'status-success' : ''),
                textContent: s.running ? 'Running' : 'Stopped'}),
        ]));
        stats.appendChild(el('div', {className: 'indexer-stat'}, [
            el('div', {className: 'stat-label', textContent: 'Files Indexed'}),
            el('div', {className: 'stat-value', textContent: String(s.total_indexed)}),
        ]));
        stats.appendChild(el('div', {className: 'indexer-stat'}, [
            el('div', {className: 'stat-label', textContent: 'Last Scan'}),
            el('div', {className: 'stat-value', textContent: s.last_scan_human}),
        ]));
    }

    document.getElementById('save-indexer').addEventListener('click', function() {
        var body = {
            enabled: document.getElementById('setting-indexer-enabled').checked,
            interval: parseInt(document.getElementById('setting-indexer-interval').value, 10),
        };

        api('/api/settings/indexer', {method: 'POST', body: body})
            .then(function() {
                showStatus('indexer-status', 'Saved', false);
                setTimeout(loadSettings, 1000);
            })
            .catch(function(e) { showStatus('indexer-status', e.message, true); });
    });

    document.getElementById('trigger-scan').addEventListener('click', function() {
        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Scanning...';

        api('/api/settings/indexer/scan', {method: 'POST'})
            .then(function() {
                showStatus('indexer-status', 'Scan started', false);
                btn.textContent = 'Trigger Scan';
                btn.disabled = false;
                setTimeout(loadSettings, 3000);
            })
            .catch(function(e) {
                showStatus('indexer-status', e.message, true);
                btn.textContent = 'Trigger Scan';
                btn.disabled = false;
            });
    });

    // --- SFTP ---

    function populateSftp(sftp) {
        document.getElementById('setting-sftp-enabled').checked = sftp.enabled;
        document.getElementById('setting-sftp-port').value = sftp.port || 2222;
        document.getElementById('setting-sftp-readonly').checked = sftp.read_only !== false;

        var stats = document.getElementById('sftp-stats');
        stats.textContent = '';
        var s = sftp.status;
        stats.appendChild(el('div', {className: 'indexer-stat'}, [
            el('div', {className: 'stat-label', textContent: 'Status'}),
            el('div', {className: 'stat-value ' + (s.running ? 'status-success' : ''),
                textContent: s.running ? 'Running on port ' + s.port : 'Stopped'}),
        ]));

        var fpGroup = document.getElementById('sftp-fingerprint-group');
        var fpEl = document.getElementById('sftp-fingerprint');
        if (s.host_key_fingerprint) {
            fpEl.textContent = s.host_key_fingerprint;
            fpGroup.style.display = '';
        } else {
            fpGroup.style.display = 'none';
        }
    }

    document.getElementById('save-sftp').addEventListener('click', function() {
        var body = {
            enabled: document.getElementById('setting-sftp-enabled').checked,
            port: parseInt(document.getElementById('setting-sftp-port').value, 10),
            read_only: document.getElementById('setting-sftp-readonly').checked,
        };

        api('/api/settings/sftp', {method: 'POST', body: body})
            .then(function() {
                showStatus('sftp-status', 'Saved', false);
                setTimeout(loadSettings, 1500);
            })
            .catch(function(e) { showStatus('sftp-status', e.message, true); });
    });

    // --- Thumbnails ---

    function populateThumbnails(t) {
        document.getElementById('setting-thumb-enabled').checked = t.enabled;
        document.getElementById('setting-thumb-width').value = t.width;
        document.getElementById('setting-thumb-height').value = t.height;
    }

    document.getElementById('save-thumbnails').addEventListener('click', function() {
        var body = {
            enabled: document.getElementById('setting-thumb-enabled').checked,
            width: parseInt(document.getElementById('setting-thumb-width').value, 10),
            height: parseInt(document.getElementById('setting-thumb-height').value, 10),
        };

        api('/api/settings/thumbnails', {method: 'POST', body: body})
            .then(function() { showStatus('thumb-status', 'Saved', false); })
            .catch(function(e) { showStatus('thumb-status', e.message, true); });
    });

    // --- Init ---
    loadSettings();
})();
