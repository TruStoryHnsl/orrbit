(function() {
    var list = document.getElementById('activity-list');
    var pagination = document.getElementById('activity-pagination');
    var filter = document.getElementById('action-filter');
    var currentPage = 1;

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
            var arr = Array.isArray(children) ? children : [children];
            for (var i = 0; i < arr.length; i++) {
                if (typeof arr[i] === 'string') node.appendChild(document.createTextNode(arr[i]));
                else if (arr[i]) node.appendChild(arr[i]);
            }
        }
        return node;
    }

    function load() {
        var action = filter.value;
        var params = 'page=' + currentPage + '&per_page=50';
        if (action) params += '&action=' + encodeURIComponent(action);

        fetch('/api/activity?' + params)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                list.textContent = '';
                if (!data.entries || data.entries.length === 0) {
                    list.appendChild(el('div', {className: 'empty-state', textContent: 'No activity yet'}));
                    pagination.textContent = '';
                    return;
                }
                for (var i = 0; i < data.entries.length; i++) {
                    var e = data.entries[i];
                    var row = el('div', {className: 'activity-row'}, [
                        el('span', {className: 'activity-time', textContent: e.time_human}),
                        el('span', {className: 'activity-action ' + e.action, textContent: e.action}),
                        el('span', {className: 'activity-details', textContent: e.details || ''}),
                        el('span', {className: 'activity-user', textContent: e.username}),
                    ]);
                    list.appendChild(row);
                }

                // Pagination
                pagination.textContent = '';
                if (data.pages > 1) {
                    if (currentPage > 1) {
                        var prev = el('button', {className: 'page-btn', textContent: '\u2190'});
                        prev.addEventListener('click', function() { currentPage--; load(); });
                        pagination.appendChild(prev);
                    }
                    pagination.appendChild(el('span', {className: 'page-info',
                        textContent: 'Page ' + currentPage + ' / ' + data.pages}));
                    if (currentPage < data.pages) {
                        var next = el('button', {className: 'page-btn', textContent: '\u2192'});
                        next.addEventListener('click', function() { currentPage++; load(); });
                        pagination.appendChild(next);
                    }
                }
            })
            .catch(function() {
                list.textContent = '';
                list.appendChild(el('div', {className: 'empty-state', textContent: 'Failed to load activity'}));
            });
    }

    filter.addEventListener('change', function() { currentPage = 1; load(); });
    load();
})();
