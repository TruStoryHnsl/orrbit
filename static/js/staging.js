(function() {
    'use strict';

    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    // --- Upload zone ---
    var zone = document.getElementById('upload-zone');
    var fileInput = document.getElementById('file-input');

    // Build progress bar dynamically (only shown during upload)
    var progressFill = document.createElement('div');
    progressFill.className = 'progress-fill';
    var progressBar = document.createElement('div');
    progressBar.className = 'progress-bar';
    progressBar.appendChild(progressFill);
    var progressText = document.createElement('span');
    progressText.className = 'progress-text';
    var progressDiv = document.createElement('div');
    progressDiv.className = 'upload-progress';
    progressDiv.appendChild(progressBar);
    progressDiv.appendChild(progressText);

    function uploadFiles(files) {
        if (!files.length) return;

        var formData = new FormData();
        for (var i = 0; i < files.length; i++) {
            formData.append('file', files[i]);
        }

        progressFill.style.width = '0%';
        progressText.textContent = 'Uploading ' + files.length + ' file(s)...';
        if (zone && !progressDiv.parentNode) zone.appendChild(progressDiv);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload');
        xhr.setRequestHeader('X-CSRFToken', csrfToken);

        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                var pct = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = pct + '%';
                progressText.textContent = pct + '%';
            }
        });

        xhr.addEventListener('load', function() {
            if (xhr.status === 200) {
                progressText.textContent = 'Done!';
                setTimeout(function() { location.reload(); }, 500);
            } else {
                progressText.textContent = 'Upload failed';
            }
        });

        xhr.addEventListener('error', function() {
            progressText.textContent = 'Upload failed';
        });

        xhr.send(formData);
    }

    if (zone) {
        zone.addEventListener('dragover', function(e) {
            e.preventDefault();
            zone.classList.add('drag-over');
        });
        zone.addEventListener('dragleave', function() {
            zone.classList.remove('drag-over');
        });
        zone.addEventListener('drop', function(e) {
            e.preventDefault();
            zone.classList.remove('drag-over');
            uploadFiles(e.dataTransfer.files);
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', function() {
            uploadFiles(fileInput.files);
        });
    }

    // --- Move / Delete ---
    document.querySelectorAll('.move-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var row = btn.closest('.staging-row');
            var filename = row.dataset.filename;
            var slug = row.querySelector('.move-dest').value;

            fetch('/api/staging/move', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({filename: filename, slug: slug})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    row.remove();
                    checkEmpty();
                }
            });
        });
    });

    document.querySelectorAll('.delete-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var row = btn.closest('.staging-row');
            var filename = row.dataset.filename;

            fetch('/api/staging/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
                body: JSON.stringify({filename: filename})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    row.remove();
                    checkEmpty();
                }
            });
        });
    });

    function checkEmpty() {
        var list = document.getElementById('staging-list');
        if (list && list.children.length === 0) {
            list.remove();
            var p = document.createElement('p');
            p.className = 'empty-state';
            p.id = 'empty-state';
            p.textContent = 'No files in staging. Upload files or use the share sheet on your device.';
            document.querySelector('.staging-page').appendChild(p);
        }
    }
})();
