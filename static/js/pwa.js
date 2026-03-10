(function() {
    // Service worker registration
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js').catch(function() {});
    }

    // PWA install prompt
    var installPrompt = null;
    var installBtn = document.getElementById('pwa-install-btn');

    window.addEventListener('beforeinstallprompt', function(e) {
        e.preventDefault();
        installPrompt = e;
        if (installBtn) installBtn.hidden = false;
    });

    if (installBtn) {
        installBtn.addEventListener('click', function() {
            if (!installPrompt) return;
            installPrompt.prompt();
            installPrompt.userChoice.then(function(result) {
                installPrompt = null;
                installBtn.hidden = true;
            });
        });
    }

    window.addEventListener('appinstalled', function() {
        installPrompt = null;
        if (installBtn) installBtn.hidden = true;
    });
})();
