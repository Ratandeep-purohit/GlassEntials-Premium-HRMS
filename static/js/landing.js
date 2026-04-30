/* ── landing.js v2.0 ────────────────────────────────────── */

// ── Navbar scroll ─────────────────────────────────────────
const navbar = document.getElementById('navbar');
if (navbar) {
    window.addEventListener('scroll', () => {
        navbar.classList.toggle('scrolled', window.scrollY > 40);
    }, { passive: true });
}

// ── Mobile menu ────────────────────────────────────────────
const menuToggle = document.getElementById('menuToggle');
const navLinks   = document.getElementById('navLinks');
if (menuToggle && navLinks) {
    menuToggle.addEventListener('click', () => {
        menuToggle.classList.toggle('open');
        navLinks.classList.toggle('open');
    });
}
// close on link click
if (navLinks) {
    navLinks.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            if (menuToggle) menuToggle.classList.remove('open');
            navLinks.classList.remove('open');
        });
    });
}

// ── Scroll Reveal ─────────────────────────────────────────
const revealEls = document.querySelectorAll('.reveal');
const revealObs = new IntersectionObserver(
    (entries) => entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('active'); revealObs.unobserve(e.target); } }),
    { threshold: 0.12, rootMargin: '0px 0px -60px 0px' }
);
revealEls.forEach(el => revealObs.observe(el));

// ── Number counter ────────────────────────────────────────
const counters = document.querySelectorAll('.counter');
let counterDone = false;

function animateCounters() {
    if (counterDone) return;
    counterDone = true;
    counters.forEach(counter => {
        const target = parseInt(counter.dataset.target, 10);
        const suffix = counter.dataset.suffix || '';
        const duration = 2000;
        const steps = 60;
        const stepMs = duration / steps;
        let current = 0;
        const inc = target / steps;
        const timer = setInterval(() => {
            current = Math.min(current + inc, target);
            counter.textContent = Math.floor(current) + suffix;
            if (current >= target) clearInterval(timer);
        }, stepMs);
    });
}

const statsObs = new IntersectionObserver(
    (entries) => entries.forEach(e => { if (e.isIntersecting) animateCounters(); }),
    { threshold: 0.3 }
);
const statsSection = document.querySelector('.stats-section');
if (statsSection) statsObs.observe(statsSection);

// ── Animate analytics bars when features come into view ───
document.querySelectorAll('.bar-fill').forEach(bar => {
    const targetWidth = bar.style.width;
    bar.style.width = '0%';
    const obs = new IntersectionObserver(entries => {
        entries.forEach(e => { if (e.isIntersecting) { bar.style.width = targetWidth; obs.unobserve(e.target); } });
    }, { threshold: 0.5 });
    obs.observe(bar);
});

// ── FAQ accordion ─────────────────────────────────────────
document.querySelectorAll('.faq-item').forEach(item => {
    item.querySelector('.faq-q').addEventListener('click', () => {
        const isOpen = item.classList.contains('active');
        document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('active'));
        if (!isOpen) item.classList.add('active');
    });
});


// ── Subtle particle canvas ────────────────────────────────
(function initParticles() {
    const canvas = document.getElementById('particleCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
    resize();
    window.addEventListener('resize', resize, { passive: true });

    const COUNT = 55;
    const particles = Array.from({ length: COUNT }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 2 + 0.5,
        dx: (Math.random() - 0.5) * 0.4,
        dy: (Math.random() - 0.5) * 0.4,
        opacity: Math.random() * 0.3 + 0.08
    }));

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(37,99,235,${p.opacity})`;
            ctx.fill();
            p.x += p.dx; p.y += p.dy;
            if (p.x < 0 || p.x > canvas.width)  p.dx *= -1;
            if (p.y < 0 || p.y > canvas.height) p.dy *= -1;
        });

        // Draw connecting lines
        for (let i = 0; i < COUNT; i++) {
            for (let j = i + 1; j < COUNT; j++) {
                const dist = Math.hypot(particles[i].x - particles[j].x, particles[i].y - particles[j].y);
                if (dist < 130) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(37,99,235,${0.06 * (1 - dist / 130)})`;
                    ctx.lineWidth = .7;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(draw);
    }
    draw();
})();

// ── 3D Parallax Mouse Tilt Effect ─────────────────────────
const tiltElements = document.querySelectorAll('.feat-card, .workflow-card, .testi-card');
tiltElements.forEach(card => {
    card.addEventListener('mousemove', e => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        
        // Calculate tilt
        const rotateX = ((y - centerY) / centerY) * -4; // Max 4 deg
        const rotateY = ((x - centerX) / centerX) * 4;
        
        card.style.transform = `perspective(1000px) translateY(-4px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.01, 1.01, 1.01)`;
        card.style.transition = 'none'; // Snappy tracking
        
        // Spotlight calculation
        card.style.setProperty('--px', `${x}px`);
        card.style.setProperty('--py', `${y}px`);
    });
    
    card.addEventListener('mouseleave', () => {
        card.style.transform = '';
        card.style.transition = 'transform 0.5s var(--ease), box-shadow 0.5s var(--ease)';
    });
});
// -- Toast System -------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const toasts = document.querySelectorAll('.toast');
    
    toasts.forEach(toast => {
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => {
                toast.remove();
                // If container is empty, remove it too
                const container = document.querySelector('.toast-container');
                if (container && container.children.length === 0) {
                    container.remove();
                }
            }, 400);
        }, 5000);

        // Click to dismiss immediately
        toast.addEventListener('click', () => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 400);
        });
    });
});
