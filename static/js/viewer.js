(function() {
    var cfg = document.getElementById('viewer-config');
    if (!cfg) return;

    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    var slug = cfg.dataset.slug;
    var filePath = cfg.dataset.path;
    var fileType = cfg.dataset.fileType;
    var pdfWorkerUrl = cfg.dataset.pdfWorker || '';
    var rawUrl = cfg.dataset.rawUrl || '';

    // --- Share ---
    var btn = document.getElementById('share-btn');
    var status = document.getElementById('share-status');
    var ttlSelect = document.getElementById('share-ttl');
    if (btn) {
        btn.addEventListener('click', function() {
            btn.disabled = true;
            btn.textContent = 'Creating...';
            status.textContent = '';
            status.className = 'share-status';

            var ttl = ttlSelect ? parseInt(ttlSelect.value, 10) : 1800;

            fetch('/api/share', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({slug: slug, path: filePath, ttl: ttl})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.url) {
                    status.className = 'share-status success';
                    var mins = data.remaining_minutes || Math.round(ttl / 60);
                    var label = mins >= 60 ? Math.round(mins / 60) + ' hr' : mins + ' min';
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(data.url).then(function() {
                            status.textContent = 'Link copied! Expires in ' + label + '.';
                        }, function() {
                            status.textContent = data.url;
                        });
                    } else {
                        status.textContent = data.url;
                    }
                } else {
                    status.className = 'share-status error';
                    status.textContent = data.error || 'Error creating link';
                }
                btn.disabled = false;
                btn.textContent = 'Share';
            })
            .catch(function() {
                status.className = 'share-status error';
                status.textContent = 'Error creating link';
                btn.disabled = false;
                btn.textContent = 'Share';
            });
        });
    }

    // --- Favorite ---
    var favBtn = document.getElementById('fav-btn');
    if (favBtn) {
        fetch('/api/favorites/check?root=' + encodeURIComponent(slug) + '&path=' + encodeURIComponent(filePath))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.favorited) {
                    favBtn.classList.add('active');
                    favBtn.textContent = '\u2605';
                }
            }).catch(function() {});

        favBtn.addEventListener('click', function() {
            fetch('/api/favorites', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({
                    root: slug,
                    path: filePath,
                    name: favBtn.dataset.name,
                    file_type: favBtn.dataset.type,
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.favorited) {
                    favBtn.classList.add('active');
                    favBtn.textContent = '\u2605';
                } else {
                    favBtn.classList.remove('active');
                    favBtn.textContent = '\u2606';
                }
            }).catch(function() {});
        });
    }

    // --- Tags ---
    var tagsList = document.getElementById('tags-list');
    var tagInput = document.getElementById('tag-input');

    function renderTags(tags) {
        tagsList.textContent = '';
        for (var i = 0; i < tags.length; i++) {
            var chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = tags[i];
            var removeBtn = document.createElement('button');
            removeBtn.className = 'tag-remove';
            removeBtn.textContent = '\u00d7';
            removeBtn.dataset.tag = tags[i];
            removeBtn.addEventListener('click', function() {
                removeTag(this.dataset.tag);
            });
            chip.appendChild(removeBtn);
            tagsList.appendChild(chip);
        }
    }

    function loadTags() {
        fetch('/api/tags/file?root=' + encodeURIComponent(slug) + '&path=' + encodeURIComponent(filePath))
            .then(function(r) { return r.json(); })
            .then(function(data) { renderTags(data.tags || []); })
            .catch(function() {});
    }

    function removeTag(tag) {
        fetch('/api/tags/remove', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({root: slug, path: filePath, tag: tag})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) { renderTags(data.tags || []); })
        .catch(function() {});
    }

    if (tagInput) {
        tagInput.addEventListener('keydown', function(e) {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            var tag = tagInput.value.trim();
            if (!tag) return;
            tagInput.value = '';

            fetch('/api/tags/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({root: slug, path: filePath, tag: tag})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) { renderTags(data.tags || []); })
            .catch(function() {});
        });
    }

    loadTags();

    // --- Playhead Persistence ---
    var video = document.querySelector('.video-viewer video');
    var audio = document.querySelector('.audio-viewer audio');
    var mediaEl = video || audio;

    if (mediaEl) {
        // Restore position
        fetch('/api/playhead?root=' + encodeURIComponent(slug) + '&path=' + encodeURIComponent(filePath))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.position && data.position > 2) {
                    mediaEl.currentTime = data.position;
                }
            }).catch(function() {});

        // Save position periodically during playback
        var saveInterval;
        mediaEl.addEventListener('play', function() {
            saveInterval = setInterval(function() {
                if (mediaEl.currentTime > 0) {
                    fetch('/api/playhead', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                        body: JSON.stringify({root: slug, path: filePath, position: mediaEl.currentTime})
                    }).catch(function() {});
                }
            }, 10000);
        });

        mediaEl.addEventListener('pause', function() {
            clearInterval(saveInterval);
            if (mediaEl.currentTime > 0) {
                fetch('/api/playhead', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                    body: JSON.stringify({root: slug, path: filePath, position: mediaEl.currentTime})
                }).catch(function() {});
            }
        });

        window.addEventListener('beforeunload', function() {
            if (mediaEl.currentTime > 0) {
                fetch('/api/playhead', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                    body: JSON.stringify({root: slug, path: filePath, position: mediaEl.currentTime}),
                    keepalive: true,
                });
            }
        });
    }

    // --- PDF viewer ---
    if (fileType === 'pdf' && typeof pdfjsLib !== 'undefined') {
        pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        var pdfDoc = null, pageNum = 1, rendering = false;
        var canvas = document.getElementById('pdf-canvas');
        var ctx = canvas ? canvas.getContext('2d') : null;

        function renderPage(num) {
            rendering = true;
            pdfDoc.getPage(num).then(function(page) {
                var vw = Math.min(window.innerWidth - 40, 1200);
                var unscaledViewport = page.getViewport({scale: 1});
                var scale = vw / unscaledViewport.width;
                var viewport = page.getViewport({scale: scale});
                canvas.height = viewport.height;
                canvas.width = viewport.width;
                page.render({canvasContext: ctx, viewport: viewport}).promise.then(function() {
                    rendering = false;
                });
                document.getElementById('pdf-page-info').textContent = 'Page ' + num + ' / ' + pdfDoc.numPages;
            });
        }

        // Restore PDF page from playhead
        fetch('/api/playhead?root=' + encodeURIComponent(slug) + '&path=' + encodeURIComponent(filePath))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var startPage = 1;
                if (data.position && data.position > 1) {
                    startPage = Math.floor(data.position);
                }

                pdfjsLib.getDocument(rawUrl).promise.then(function(pdf) {
                    pdfDoc = pdf;
                    if (startPage > pdf.numPages) startPage = 1;
                    pageNum = startPage;
                    renderPage(pageNum);
                });
            }).catch(function() {
                pdfjsLib.getDocument(rawUrl).promise.then(function(pdf) {
                    pdfDoc = pdf;
                    renderPage(1);
                });
            });

        var prevBtn = document.getElementById('pdf-prev');
        var nextBtn = document.getElementById('pdf-next');
        if (prevBtn) {
            prevBtn.addEventListener('click', function() {
                if (pageNum <= 1 || rendering) return;
                pageNum--;
                renderPage(pageNum);
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function() {
                if (!pdfDoc || pageNum >= pdfDoc.numPages || rendering) return;
                pageNum++;
                renderPage(pageNum);
            });
        }

        // Tap navigation: left third = prev, right third = next
        if (canvas) {
            canvas.addEventListener('click', function(e) {
                var rect = canvas.getBoundingClientRect();
                var x = e.clientX - rect.left;
                var third = rect.width / 3;
                if (x < third) {
                    if (pageNum > 1 && !rendering) { pageNum--; renderPage(pageNum); }
                } else if (x > third * 2) {
                    if (pdfDoc && pageNum < pdfDoc.numPages && !rendering) { pageNum++; renderPage(pageNum); }
                }
            });
        }

        // Save PDF page via playhead on page change
        var pageInfoEl = document.getElementById('pdf-page-info');
        if (pageInfoEl) {
            var observer = new MutationObserver(function() {
                var text = pageInfoEl.textContent;
                var match = text.match(/Page (\d+)/);
                if (match) {
                    var pn = parseInt(match[1], 10);
                    fetch('/api/playhead', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                        body: JSON.stringify({root: slug, path: filePath, position: pn})
                    }).catch(function() {});
                }
            });
            observer.observe(pageInfoEl, {childList: true, characterData: true, subtree: true});
        }
    }
})();
