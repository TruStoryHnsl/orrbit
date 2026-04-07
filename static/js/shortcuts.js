/* Orrbit keyboard shortcuts — global navigation and page-specific bindings. */

(function() {
    'use strict';

    // Don't fire shortcuts when typing in inputs
    function isEditing() {
        var el = document.activeElement;
        if (!el) return false;
        var tag = el.tagName;
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
    }

    document.addEventListener('keydown', function(e) {
        // Always handle Escape (close overlays, clear search, exit modes)
        if (e.key === 'Escape') {
            // Blur any focused input
            if (isEditing()) {
                document.activeElement.blur();
                return;
            }
            // Exit select mode if active
            var selectBtn = document.getElementById('select-mode-btn');
            if (selectBtn && selectBtn.classList.contains('active')) {
                selectBtn.click();
                return;
            }
            // Exit tag mode if active
            var tagBtn = document.getElementById('tag-mode-btn');
            if (tagBtn && tagBtn.classList.contains('active')) {
                tagBtn.click();
                return;
            }
            return;
        }

        if (isEditing()) return;

        // --- Global shortcuts ---

        // / or Ctrl+K → focus search
        if (e.key === '/' || (e.key === 'k' && (e.ctrlKey || e.metaKey))) {
            e.preventDefault();
            var search = document.getElementById('search-input') || document.getElementById('global-search');
            if (search) {
                search.focus();
                search.select();
            }
            return;
        }

        // g then h → go home (browse root)
        // g then s → go settings
        // g then a → go activity
        // g then t → go staging

        // --- Browse page shortcuts ---

        var itemsContainer = document.getElementById('items-container');
        if (itemsContainer) {
            // j/k → navigate items
            if (e.key === 'j' || e.key === 'k') {
                e.preventDefault();
                navigateItems(e.key === 'j' ? 1 : -1);
                return;
            }

            // Enter → open focused item
            if (e.key === 'Enter') {
                var focused = document.querySelector('.item-row.kb-focused a, a.item-row.kb-focused, a.grid-item.kb-focused');
                if (focused) {
                    e.preventDefault();
                    focused.click();
                }
                return;
            }

            // l → switch to list view
            if (e.key === 'l') {
                var listBtn = document.querySelector('.view-btn[data-view="list"]');
                if (listBtn && !listBtn.classList.contains('active')) listBtn.click();
                return;
            }

            // g → switch to grid view
            if (e.key === 'g') {
                var gridBtn = document.querySelector('.view-btn[data-view="grid"]');
                if (gridBtn && !gridBtn.classList.contains('active')) gridBtn.click();
                return;
            }

            // s → toggle select mode
            if (e.key === 's') {
                var selBtn = document.getElementById('select-mode-btn');
                if (selBtn) selBtn.click();
                return;
            }
        }

        // --- Viewer page shortcuts ---

        var viewerConfig = document.getElementById('viewer-config');
        if (viewerConfig) {
            // Left arrow → previous file
            if (e.key === 'ArrowLeft') {
                var prev = document.querySelector('.nav-prev');
                if (prev) { prev.click(); return; }
            }

            // Right arrow → next file
            if (e.key === 'ArrowRight') {
                var next = document.querySelector('.nav-next');
                if (next) { next.click(); return; }
            }

            // f → toggle favorite
            if (e.key === 'f') {
                var favBtn = document.getElementById('fav-btn');
                if (favBtn) favBtn.click();
                return;
            }

            // d → download
            if (e.key === 'd') {
                var dlLink = document.querySelector('.file-info-bar a[download]');
                if (dlLink) dlLink.click();
                return;
            }
        }
    });

    // --- j/k item navigation ---

    var focusedIndex = -1;

    function navigateItems(direction) {
        var items = document.querySelectorAll('.item-row, .grid-item');
        if (!items.length) return;

        // Remove current focus
        if (focusedIndex >= 0 && focusedIndex < items.length) {
            items[focusedIndex].classList.remove('kb-focused');
        }

        focusedIndex += direction;
        if (focusedIndex < 0) focusedIndex = 0;
        if (focusedIndex >= items.length) focusedIndex = items.length - 1;

        items[focusedIndex].classList.add('kb-focused');
        items[focusedIndex].scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }

    // Reset focus index when items reload
    var observer = new MutationObserver(function() { focusedIndex = -1; });
    var target = document.getElementById('items-container');
    if (target) {
        observer.observe(target, {childList: true});
    }
})();
