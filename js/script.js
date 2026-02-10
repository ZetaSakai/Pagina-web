document.addEventListener("DOMContentLoaded", function() {


    function initRevealOnScroll() {
        const selectors = [
            '.header-txt',
            '.popular-card',
            '.popular-content img',
            '.product-1',
            '.contact-content'
        ];

        const elements = [];
        selectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => {
                el.classList.add('reveal-on-scroll');
                elements.push(el);
            });
        });

        if (!('IntersectionObserver' in window)) {
            elements.forEach(el => el.classList.add('reveal'));
            return;
        }

        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const el = entry.target;
                    const index = elements.indexOf(el);
                    el.style.transitionDelay = (index >= 0 ? index * 30 : 0) + 'ms';
                    el.classList.add('reveal');
                    obs.unobserve(el);
                }
            });
        }, { threshold: 0.12 });

        elements.forEach(el => observer.observe(el));
    }

    initRevealOnScroll();
    const menuCheckbox = document.getElementById('menu');
    const navLinks = document.querySelectorAll('.navbar ul li a');
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            if (menuCheckbox && menuCheckbox.checked) {
                menuCheckbox.checked = false;
            }
        });
    });
});

