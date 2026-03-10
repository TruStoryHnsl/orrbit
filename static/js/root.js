/* orrbit root.js — global search + favorites on root page */

(function() {
    'use strict';

    var searchInput = document.getElementById('global-search');
    var searchResults = document.getElementById('search-results');
    var rootContent = document.getElementById('root-content');
    var favSection = document.getElementById('favorites-section');
    var favList = document.getElementById('favorites-list');

    // File type icons
    var icons = {
        dir: '\uD83D\uDCC1', video: '\uD83C\uDFA5', image: '\uD83D\uDDBC',
        audio: '\uD83C\uDFB5', text: '\uD83D\uDCC4', pdf: '\uD83D\uDCC4',
        epub: '\uD83D\uDCD6', comic: '\uD83D\uDCDA', other: '\uD83D\uDCC4',
    };

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

    // --- Global Search ---

    var searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            var q = searchInput.value.trim();
            if (!q) {
                searchResults.hidden = true;
                searchResults.textContent = '';
                rootContent.hidden = false;
                return;
            }
            searchTimeout = setTimeout(function() { doSearch(q); }, 300);
        });
    }

    function doSearch(q) {
        rootContent.hidden = true;
        searchResults.hidden = false;
        searchResults.textContent = '';
        searchResults.appendChild(el('div', {className: 'loading', textContent: 'Searching...'}));

        fetch('/api/search?q=' + encodeURIComponent(q) + '&per_page=50')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                searchResults.textContent = '';
                if (!data.items || data.items.length === 0) {
                    searchResults.appendChild(el('div', {className: 'empty-state', textContent: 'No results for "' + q + '"'}));
                    return;
                }
                searchResults.appendChild(el('div', {className: 'search-count', textContent: data.total + ' result(s)'}));
                var list = el('div', {className: 'items-list'});
                for (var i = 0; i < data.items.length; i++) {
                    var item = data.items[i];
                    var icon = item.is_dir ? icons.dir : (icons[item.file_type] || icons.other);
                    var href = (item.is_dir ? '/browse/' : '/view/') + encodeURI(item.root) + '/' + encodeURI(item.path);
                    var row = el('a', {href: href, className: 'item-row'}, [
                        el('span', {className: 'item-icon', textContent: icon}),
                        el('span', {className: 'item-name'}, [
                            el('span', {textContent: item.name}),
                            el('span', {className: 'item-root-tag', textContent: item.root}),
                        ]),
                        el('span', {className: 'item-size', textContent: item.size_human}),
                        el('span', {className: 'item-date', textContent: item.mtime_human}),
                    ]);
                    list.appendChild(row);
                }
                searchResults.appendChild(list);
            })
            .catch(function() {
                searchResults.textContent = '';
                searchResults.appendChild(el('div', {className: 'empty-state', textContent: 'Search failed'}));
            });
    }

    // --- Favorites ---

    function loadFavorites() {
        fetch('/api/favorites')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.favorites || data.favorites.length === 0) {
                    favSection.hidden = true;
                    return;
                }
                favSection.hidden = false;
                favList.textContent = '';
                for (var i = 0; i < data.favorites.length; i++) {
                    var fav = data.favorites[i];
                    var icon = fav.is_dir ? icons.dir : (icons[fav.file_type] || icons.other);
                    var href = (fav.is_dir ? '/browse/' : '/view/') + encodeURI(fav.root) + '/' + encodeURI(fav.path);
                    var row = el('a', {href: href, className: 'fav-item'}, [
                        el('span', {className: 'fav-icon', textContent: icon}),
                        el('span', {className: 'fav-name', textContent: fav.name}),
                        el('span', {className: 'fav-root', textContent: fav.root}),
                    ]);
                    favList.appendChild(row);
                }
            })
            .catch(function() {});
    }

    loadFavorites();
})();
