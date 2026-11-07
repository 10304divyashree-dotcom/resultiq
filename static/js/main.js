/**
 * ResultIQ - Main JavaScript Foundation
 * Enhanced responsive interactions & mobile navigation
 */

document.addEventListener('DOMContentLoaded', () => {
    // -------------------------------------------------------------------------
    // 1. Mobile Navigation Toggle
    // -------------------------------------------------------------------------
    const navToggle = document.getElementById('nav-toggle');
    const navLinks = document.getElementById('nav-links');

    if (navToggle && navLinks) {
        navToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = navLinks.classList.toggle('nav-open');
            navToggle.classList.toggle('active', isOpen);
            navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });

        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!navLinks.contains(e.target) && !navToggle.contains(e.target)) {
                if (navLinks.classList.contains('nav-open')) {
                    navLinks.classList.remove('nav-open');
                    navToggle.classList.remove('active');
                    navToggle.setAttribute('aria-expanded', 'false');
                }
            }
        });

        // Close menu on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && navLinks.classList.contains('nav-open')) {
                navLinks.classList.remove('nav-open');
                navToggle.classList.remove('active');
                navToggle.setAttribute('aria-expanded', 'false');
                navToggle.focus();
            }
        });

        // Close menu when a link inside is clicked
        navLinks.querySelectorAll('a').forEach((link) => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('nav-open');
                navToggle.classList.remove('active');
                navToggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // -------------------------------------------------------------------------
    // 2. Responsive Table Scroll Indicators for Mobile
    // -------------------------------------------------------------------------
    const tableWrappers = document.querySelectorAll('.table-wrapper, .file-table-wrapper');
    tableWrappers.forEach((wrapper) => {
        // If content overflows horizontally, attach a subtle indicator
        const checkOverflow = () => {
            if (wrapper.scrollWidth > wrapper.clientWidth + 10) {
                wrapper.classList.add('has-horizontal-scroll');
            } else {
                wrapper.classList.remove('has-horizontal-scroll');
            }
        };

        checkOverflow();
        window.addEventListener('resize', checkOverflow);

        wrapper.addEventListener('scroll', () => {
            if (wrapper.scrollLeft > 20) {
                wrapper.classList.add('scrolled-horizontally');
            } else {
                wrapper.classList.remove('scrolled-horizontally');
            }
        });
    });

    // -------------------------------------------------------------------------
    // 3. Auto-dismiss alerts after 5 seconds
    // -------------------------------------------------------------------------
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach((alert) => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-6px)';
            setTimeout(() => {
                if (alert.parentNode) {
                    alert.remove();
                }
            }, 400);
        }, 6000);
    });
});
