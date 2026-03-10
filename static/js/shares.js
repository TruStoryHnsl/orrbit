(function() {
    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    document.querySelectorAll('.copy-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            navigator.clipboard.writeText(btn.dataset.url).then(function() {
                btn.textContent = 'Copied!';
                setTimeout(function() { btn.textContent = 'Copy Link'; }, 2000);
            });
        });
    });

    document.querySelectorAll('.revoke-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var token = btn.dataset.token;
            fetch('/api/share/' + token, { method: 'DELETE', headers: {'X-CSRFToken': csrfToken} })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    var row = document.getElementById('share-' + token);
                    if (row) row.remove();
                }
            });
        });
    });
})();
