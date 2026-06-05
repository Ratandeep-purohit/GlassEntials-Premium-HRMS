(function () {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;

    document.documentElement.classList.add('motion-ready');

    function setupReveal() {
        const selector = [
            '.stat-card',
            '.bento-card',
            '.employee-attendance-card',
            '.announce-item',
            '.compact-item',
            '.card',
            '.dashboard-card',
            '.module-card',
            '.policy-card',
            '.salary-card',
            '.asset-card',
            '.leave-card',
            '.form-card',
            '.table-card'
        ].join(',');

        const items = Array.from(document.querySelectorAll(selector));
        if (!items.length) return;

        items.forEach(function (item, index) {
            item.classList.add('js-reveal');
            item.style.setProperty('--motion-delay', Math.min(index, 8) * 35 + 'ms');
        });

        if (!('IntersectionObserver' in window)) {
            items.forEach(function (item) {
                item.classList.add('is-visible');
            });
            return;
        }

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            });
        }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

        items.forEach(function (item) {
            observer.observe(item);
        });
    }

    function setupRipple() {
        document.addEventListener('pointerdown', function (event) {
            const target = event.target.closest('button, .btn-primary, .btn-secondary, .btn-outline, .nav-pill, .dropdown-item, .action-link');
            if (!target || target.classList.contains('no-ripple')) return;

            const rect = target.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const ripple = document.createElement('span');
            ripple.className = 'ui-ripple';
            ripple.style.width = size + 'px';
            ripple.style.height = size + 'px';
            ripple.style.left = event.clientX - rect.left - size / 2 + 'px';
            ripple.style.top = event.clientY - rect.top - size / 2 + 'px';

            target.appendChild(ripple);
            window.setTimeout(function () {
                ripple.remove();
            }, 650);
        });
    }

    function setupAmbientCursor() {
        let ticking = false;
        document.addEventListener('pointermove', function (event) {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(function () {
                document.documentElement.style.setProperty('--cursor-x', event.clientX + 'px');
                document.documentElement.style.setProperty('--cursor-y', event.clientY + 'px');
                ticking = false;
            });
        }, { passive: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setupReveal();
            setupRipple();
            setupAmbientCursor();
        });
    } else {
        setupReveal();
        setupRipple();
        setupAmbientCursor();
    }
})();
