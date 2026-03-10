/* Orrbit browse.js — async directory listing */

(function() {
    'use strict';

    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    const container = document.getElementById('items-container');
    const pagination = document.getElementById('pagination');
    if (!container) return;

    const slug = container.dataset.slug;
    const basePath = container.dataset.path;

    // State
    let currentPage = 1;
    let currentSort = 'name';
    let currentDesc = false;
    let currentType = '';
    let currentSearch = '';
    let currentView = 'list';
    let currentTag = '';
    let selectMode = false;
    let selectedItems = new Map(); // path -> item data
    let tagMode = false;
    let tagMap = {};      // 'root:path' -> ['tag1', 'tag2']
    let knownTags = [];   // all unique tag names for autocomplete

    // File type icons
    const icons = {
        dir: '\uD83D\uDCC1',
        video: '\uD83C\uDFA5',
        image: '\uD83D\uDDBC',
        audio: '\uD83C\uDFB5',
        text: '\uD83D\uDCC4',
        pdf: '\uD83D\uDCC4',
        epub: '\uD83D\uDCD6',
        comic: '\uD83D\uDCDA',
        other: '\uD83D\uDCC4',
    };

    // Safe element creation helpers
    function el(tag, attrs, children) {
        const node = document.createElement(tag);
        if (attrs) {
            for (const [k, v] of Object.entries(attrs)) {
                if (k === 'className') node.className = v;
                else if (k === 'textContent') node.textContent = v;
                else node.setAttribute(k, v);
            }
        }
        if (children) {
            for (const child of (Array.isArray(children) ? children : [children])) {
                if (typeof child === 'string') node.appendChild(document.createTextNode(child));
                else if (child) node.appendChild(child);
            }
        }
        return node;
    }

    function buildHref(item) {
        const prefix = item.is_dir ? '/browse/' : '/view/';
        return prefix + encodeURI(slug) + '/' + encodeURI(item.path);
    }

    function buildThumbUrl(item) {
        return '/thumb/' + encodeURI(slug) + '/' + encodeURI(item.path);
    }

    // Load user's tags for the filter dropdown
    function loadTagFilter() {
        var tagFilter = document.getElementById('tag-filter');
        if (!tagFilter) return;
        fetch('/api/tags')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var tags = data.tags || [];
                for (var i = 0; i < tags.length; i++) {
                    var opt = el('option', {textContent: tags[i]});
                    opt.value = tags[i];
                    tagFilter.appendChild(opt);
                }
            }).catch(function() {});
    }
    loadTagFilter();

    // === Tag Mode ===

    function getFileTags(item) {
        return tagMap[slug + ':' + item.path] || [];
    }

    function fetchTagData() {
        return Promise.all([
            fetch('/api/tags/all').then(function(r) { return r.json(); }),
            fetch('/api/tags').then(function(r) { return r.json(); }),
        ]).then(function(results) {
            tagMap = results[0].tags_map || {};
            knownTags = results[1].tags || [];
            renderTagPalette();
            updateTagSuggestions();
        }).catch(function() {
            tagMap = {};
            knownTags = [];
        });
    }

    function renderTagPalette() {
        var palette = document.getElementById('tag-palette');
        if (!palette) return;
        palette.textContent = '';
        palette.appendChild(el('span', {className: 'tag-palette-label', textContent: 'Tags:'}));
        for (var i = 0; i < knownTags.length; i++) {
            palette.appendChild(el('span', {className: 'tag-palette-chip', textContent: knownTags[i]}));
        }
        var input = el('input', {
            className: 'tag-palette-input',
            placeholder: 'new tag...',
            type: 'text',
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var val = input.value.trim().toLowerCase();
                if (val && knownTags.indexOf(val) === -1) {
                    knownTags.push(val);
                    knownTags.sort();
                    renderTagPalette();
                    updateTagSuggestions();
                }
                input.value = '';
            }
        });
        palette.appendChild(input);
    }

    function updateTagSuggestions() {
        var dl = document.getElementById('tag-suggestions');
        if (!dl) {
            dl = document.createElement('datalist');
            dl.id = 'tag-suggestions';
            document.body.appendChild(dl);
        }
        dl.textContent = '';
        for (var i = 0; i < knownTags.length; i++) {
            var opt = document.createElement('option');
            opt.value = knownTags[i];
            dl.appendChild(opt);
        }
    }

    function createTagRow(item) {
        var row = el('div', {className: 'tag-row'});
        refreshTagRow(row, item);
        return row;
    }

    function refreshTagRow(row, item) {
        row.textContent = '';
        var tags = getFileTags(item);
        for (var i = 0; i < tags.length; i++) {
            (function(tag) {
                var chip = el('span', {className: 'tag-chip'});
                chip.appendChild(document.createTextNode(tag + ' '));
                var x = el('span', {className: 'tag-chip-x', textContent: '\u00d7'});
                x.addEventListener('click', function(e) {
                    e.stopPropagation();
                    e.preventDefault();
                    removeFileTag(item, tag, row);
                });
                chip.appendChild(x);
                row.appendChild(chip);
            })(tags[i]);
        }
        var input = el('input', {
            className: 'tag-add-input',
            placeholder: '+',
            type: 'text',
            list: 'tag-suggestions',
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                var val = input.value.trim().toLowerCase();
                if (val) {
                    addFileTag(item, val, row);
                    input.value = '';
                }
            }
        });
        row.appendChild(input);
    }

    function addFileTag(item, tag, row) {
        fetch('/api/tags/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({root: slug, path: item.path, tag: tag}),
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.tags) {
                tagMap[slug + ':' + item.path] = data.tags;
                if (knownTags.indexOf(tag) === -1) {
                    knownTags.push(tag);
                    knownTags.sort();
                    renderTagPalette();
                    updateTagSuggestions();
                }
                refreshTagRow(row, item);
            }
        })
        .catch(function() {});
    }

    function removeFileTag(item, tag, row) {
        fetch('/api/tags/remove', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({root: slug, path: item.path, tag: tag}),
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.tags !== undefined) {
                if (data.tags.length === 0) {
                    delete tagMap[slug + ':' + item.path];
                } else {
                    tagMap[slug + ':' + item.path] = data.tags;
                }
                refreshTagRow(row, item);
            }
        })
        .catch(function() {});
    }

    // Fetch and render
    async function loadItems() {
        container.textContent = '';
        container.appendChild(el('div', {className: 'loading', textContent: 'Loading...'}));

        // Tag filter mode: use tag search API
        if (currentTag) {
            try {
                const resp = await fetch('/api/tags/find?tag=' + encodeURIComponent(currentTag));
                if (!resp.ok) throw new Error('Failed');
                const data = await resp.json();

                if (!data.items || data.items.length === 0) {
                    container.textContent = '';
                    container.appendChild(el('div', {className: 'loading', textContent: 'No items with tag "' + currentTag + '"'}));
                    pagination.textContent = '';
                    return;
                }
                // Filter to only items in this slug
                const filtered = data.items.filter(function(item) { return item.root === slug; });
                if (filtered.length === 0) {
                    container.textContent = '';
                    container.appendChild(el('div', {className: 'loading', textContent: 'No items with tag "' + currentTag + '" in this directory'}));
                    pagination.textContent = '';
                    return;
                }
                renderItems(filtered);
                pagination.textContent = '';
                pagination.appendChild(el('span', {className: 'page-info', textContent: filtered.length + ' items'}));
            } catch (err) {
                container.textContent = '';
                container.appendChild(el('div', {className: 'loading', textContent: 'Error loading tagged items'}));
            }
            return;
        }

        const params = new URLSearchParams({
            sort: currentSort,
            desc: currentDesc ? '1' : '0',
            page: currentPage,
            per_page: 100,
        });
        if (currentType) params.set('type', currentType);
        if (currentSearch) params.set('q', currentSearch);

        const apiPath = basePath
            ? '/api/list/' + encodeURI(slug) + '/' + encodeURI(basePath)
            : '/api/list/' + encodeURI(slug) + '/';

        try {
            const resp = await fetch(apiPath + '?' + params);
            if (!resp.ok) throw new Error('Failed to load');
            const data = await resp.json();

            if (data.items.length === 0) {
                container.textContent = '';
                container.appendChild(el('div', {className: 'loading', textContent: 'No items found'}));
                pagination.textContent = '';
                return;
            }

            // Auto-detect view if first load
            if (currentView === 'list' && data.view_mode !== 'list') {
                currentView = 'grid';
                updateViewButtons();
            }

            renderItems(data.items);
            renderPagination(data.page, data.pages, data.total);
        } catch (err) {
            container.textContent = '';
            container.appendChild(el('div', {className: 'loading', textContent: 'Error loading directory'}));
        }
    }

    function renderItems(items) {
        if (currentView === 'grid') {
            renderGrid(items);
        } else {
            renderList(items);
        }
    }

    function renderList(items) {
        container.textContent = '';
        container.className = 'items-list';

        for (const item of items) {
            const icon = item.is_dir ? icons.dir : (icons[item.file_type] || icons.other);
            if (selectMode) {
                const row = el('div', {className: 'item-row' + (selectedItems.has(item.path) ? ' selected' : '')});
                const cb = el('input', {className: 'item-checkbox', type: 'checkbox'});
                cb.checked = selectedItems.has(item.path);
                cb.addEventListener('change', function() {
                    toggleSelect(item, this.checked);
                });
                row.appendChild(cb);
                row.appendChild(el('span', {className: 'item-icon', textContent: icon}));
                var nameLink = el('a', {href: buildHref(item), className: 'item-name', textContent: item.name});
                row.appendChild(nameLink);
                row.appendChild(el('span', {className: 'item-size', textContent: item.size_human}));
                row.appendChild(el('span', {className: 'item-date', textContent: item.mtime_human}));
                container.appendChild(row);
            } else {
                const row = el('a', {href: buildHref(item), className: 'item-row'}, [
                    el('span', {className: 'item-icon', textContent: icon}),
                    el('span', {className: 'item-name', textContent: item.name}),
                    el('span', {className: 'item-size', textContent: item.size_human}),
                    el('span', {className: 'item-date', textContent: item.mtime_human}),
                ]);
                container.appendChild(row);
            }

            // Tag row (tag mode, files only)
            if (tagMode && !item.is_dir) {
                container.appendChild(createTagRow(item));
            }
        }
    }

    function renderGrid(items) {
        container.textContent = '';
        container.className = 'items-grid';

        for (const item of items) {
            const icon = item.is_dir ? icons.dir : (icons[item.file_type] || icons.other);
            const thumbTypes = ['video', 'image', 'pdf', 'epub', 'comic'];
            const hasThumb = !item.is_dir && thumbTypes.includes(item.file_type);

            let thumbEl;
            if (hasThumb) {
                thumbEl = el('img', {
                    className: 'grid-thumb',
                    src: buildThumbUrl(item),
                    alt: '',
                    loading: 'lazy',
                });
                thumbEl.addEventListener('error', function() {
                    const placeholder = el('div', {className: 'grid-thumb-placeholder', textContent: icon});
                    this.replaceWith(placeholder);
                });
            } else {
                thumbEl = el('div', {className: 'grid-thumb-placeholder', textContent: icon});
            }

            const card = el('a', {href: buildHref(item), className: 'grid-item'}, [
                thumbEl,
                el('div', {className: 'grid-info'}, [
                    el('div', {className: 'grid-name', title: item.name, textContent: item.name}),
                    el('div', {className: 'grid-meta', textContent: item.size_human + ' \u00B7 ' + item.mtime_human}),
                ]),
            ]);

            if (tagMode && !item.is_dir) {
                var wrapper = el('div', {className: 'grid-item-wrapper'});
                wrapper.appendChild(card);
                var tagRow = createTagRow(item);
                tagRow.addEventListener('click', function(e) { e.preventDefault(); e.stopPropagation(); });
                wrapper.appendChild(tagRow);
                container.appendChild(wrapper);
            } else {
                container.appendChild(card);
            }
        }
    }

    function renderPagination(page, pages, total) {
        pagination.textContent = '';

        if (pages <= 1) {
            pagination.appendChild(el('span', {className: 'page-info', textContent: total + ' items'}));
            return;
        }

        if (page > 1) {
            const prev = el('button', {className: 'page-btn', textContent: '\u2190'});
            prev.addEventListener('click', () => { currentPage = page - 1; loadItems(); });
            pagination.appendChild(prev);
        }

        const start = Math.max(1, page - 3);
        const end = Math.min(pages, start + 6);
        for (let i = start; i <= end; i++) {
            const btn = el('button', {
                className: 'page-btn' + (i === page ? ' active' : ''),
                textContent: String(i),
            });
            const pageNum = i;
            btn.addEventListener('click', () => { currentPage = pageNum; loadItems(); });
            pagination.appendChild(btn);
        }

        if (page < pages) {
            const next = el('button', {className: 'page-btn', textContent: '\u2192'});
            next.addEventListener('click', () => { currentPage = page + 1; loadItems(); });
            pagination.appendChild(next);
        }

        pagination.appendChild(el('span', {className: 'page-info', textContent: total + ' items'}));
    }

    function updateViewButtons() {
        document.querySelectorAll('.view-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === currentView);
        });
    }

    // --- Event bindings ---

    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            currentSort = sortSelect.value;
            currentPage = 1;
            loadItems();
        });
    }

    const sortDirBtn = document.getElementById('sort-dir-btn');
    if (sortDirBtn) {
        sortDirBtn.addEventListener('click', () => {
            currentDesc = !currentDesc;
            sortDirBtn.textContent = currentDesc ? '\u25BC' : '\u25B2';
            currentPage = 1;
            loadItems();
        });
    }

    const typeFilter = document.getElementById('type-filter');
    if (typeFilter) {
        typeFilter.addEventListener('change', () => {
            currentType = typeFilter.value;
            currentPage = 1;
            loadItems();
        });
    }

    const tagFilter = document.getElementById('tag-filter');
    if (tagFilter) {
        tagFilter.addEventListener('change', () => {
            currentTag = tagFilter.value;
            currentPage = 1;
            loadItems();
        });
    }

    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        let searchTimeout;
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                currentSearch = searchInput.value.trim();
                currentPage = 1;
                loadItems();
            }, 300);
        });
    }

    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentView = btn.dataset.view;
            updateViewButtons();
            loadItems();
        });
    });

    // Tag mode toggle
    var tagModeBtn = document.getElementById('tag-mode-btn');
    if (tagModeBtn) {
        tagModeBtn.addEventListener('click', function() {
            tagMode = !tagMode;
            tagModeBtn.classList.toggle('active', tagMode);
            var palette = document.getElementById('tag-palette');
            if (tagMode) {
                fetchTagData().then(function() {
                    if (palette) palette.classList.remove('hidden');
                    loadItems();
                });
            } else {
                if (palette) palette.classList.add('hidden');
                loadItems();
            }
        });
    }

    const selectModeBtn = document.getElementById('select-mode-btn');
    if (selectModeBtn) {
        selectModeBtn.addEventListener('click', () => {
            selectMode = !selectMode;
            selectModeBtn.classList.toggle('active', selectMode);
            if (!selectMode) {
                selectedItems.clear();
                if (batchToolbar && batchToolbar.parentNode) batchToolbar.remove();
            }
            loadItems();
        });
    }

    // --- Batch Selection ---

    var batchToolbar = null;

    function toggleSelect(item, checked) {
        if (checked) {
            selectedItems.set(item.path, {root: slug, path: item.path, name: item.name, is_dir: item.is_dir});
        } else {
            selectedItems.delete(item.path);
        }
        updateBatchToolbar();
    }

    function updateBatchToolbar() {
        if (selectedItems.size === 0 && batchToolbar && batchToolbar.parentNode) {
            batchToolbar.remove();
            return;
        }
        if (selectedItems.size === 0) return;

        if (!batchToolbar) {
            batchToolbar = el('div', {className: 'batch-toolbar'});
        }
        batchToolbar.textContent = '';
        batchToolbar.appendChild(el('span', {className: 'batch-count',
            textContent: selectedItems.size + ' selected'}));

        var dlBtn = el('button', {className: 'btn btn-sm', textContent: 'Download ZIP'});
        dlBtn.addEventListener('click', batchDownload);
        batchToolbar.appendChild(dlBtn);

        var delBtn = el('button', {className: 'btn btn-sm', textContent: 'Delete'});
        delBtn.addEventListener('click', batchDelete);
        batchToolbar.appendChild(delBtn);

        var cancelBtn = el('button', {className: 'btn btn-sm', textContent: 'Cancel'});
        cancelBtn.addEventListener('click', function() {
            selectMode = false;
            selectedItems.clear();
            if (batchToolbar && batchToolbar.parentNode) batchToolbar.remove();
            loadItems();
        });
        batchToolbar.appendChild(cancelBtn);

        if (!batchToolbar.parentNode) {
            container.parentNode.insertBefore(batchToolbar, container);
        }
    }

    function batchDownload() {
        var files = Array.from(selectedItems.values()).filter(function(f) { return !f.is_dir; });
        if (!files.length) return;

        fetch('/api/batch/download', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({files: files})
        })
        .then(function(r) {
            if (!r.ok) throw new Error('Download failed');
            return r.blob();
        })
        .then(function(blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'orrbit-download.zip';
            a.click();
            URL.revokeObjectURL(url);
        })
        .catch(function(err) { alert('Download failed: ' + err.message); });
    }

    function batchDelete() {
        var files = Array.from(selectedItems.values());
        if (!files.length) return;
        if (!confirm('Delete ' + files.length + ' item(s)?')) return;

        fetch('/api/batch/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
            body: JSON.stringify({files: files})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            selectedItems.clear();
            selectMode = false;
            if (batchToolbar && batchToolbar.parentNode) batchToolbar.remove();
            loadItems();
        })
        .catch(function() { alert('Delete failed'); });
    }

    // --- Drag-and-drop upload ---

    var browseView = document.querySelector('.browse-view');
    var dragCounter = 0;

    if (browseView) {
        // Create overlay and status bar dynamically (never in DOM until needed)
        var dropOverlay = el('div', {className: 'drop-overlay'}, [
            el('div', {className: 'drop-overlay-text', textContent: 'Drop files to upload'})
        ]);

        var progressFill = el('div', {className: 'progress-fill'});
        var progressText = el('span', {className: 'progress-text'});
        var statusBar = el('div', {className: 'browse-upload-status visible'}, [
            el('div', {className: 'progress-bar'}, [progressFill]),
            progressText,
        ]);

        browseView.addEventListener('dragenter', function(e) {
            e.preventDefault();
            dragCounter++;
            if (!dropOverlay.parentNode) browseView.appendChild(dropOverlay);
        });

        browseView.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dragCounter--;
            if (dragCounter <= 0) {
                dragCounter = 0;
                if (dropOverlay.parentNode) dropOverlay.remove();
            }
        });

        browseView.addEventListener('dragover', function(e) {
            e.preventDefault();
        });

        browseView.addEventListener('drop', function(e) {
            e.preventDefault();
            dragCounter = 0;
            if (dropOverlay.parentNode) dropOverlay.remove();

            var files = e.dataTransfer.files;
            if (!files.length) return;

            var formData = new FormData();
            for (var i = 0; i < files.length; i++) {
                formData.append('file', files[i]);
            }

            progressFill.style.width = '0%';
            progressText.textContent = 'Uploading ' + files.length + ' file(s)...';
            if (!statusBar.parentNode) browseView.appendChild(statusBar);

            var uploadUrl = '/api/upload/' + encodeURIComponent(slug) + '/';
            if (basePath) uploadUrl += encodeURI(basePath);

            var xhr = new XMLHttpRequest();
            xhr.open('POST', uploadUrl);
            xhr.setRequestHeader('X-CSRFToken', csrfToken);

            xhr.upload.addEventListener('progress', function(ev) {
                if (ev.lengthComputable) {
                    var pct = Math.round((ev.loaded / ev.total) * 100);
                    progressFill.style.width = pct + '%';
                    progressText.textContent = pct + '%';
                }
            });

            xhr.addEventListener('load', function() {
                if (xhr.status === 200) {
                    progressText.textContent = 'Done!';
                    setTimeout(function() {
                        if (statusBar.parentNode) statusBar.remove();
                        loadItems();
                    }, 1000);
                } else {
                    progressText.textContent = 'Upload failed';
                }
            });

            xhr.addEventListener('error', function() {
                progressText.textContent = 'Upload failed';
            });

            xhr.send(formData);
        });
    }

    // Initial load
    loadItems();
})();
