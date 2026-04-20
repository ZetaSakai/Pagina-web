document.addEventListener("DOMContentLoaded", function () {


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
                    el.style.transitionDelay = '30ms';
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

    function styleFlashElements(elements) {
        elements.forEach((el, index) => {
            const finalTop = 20 + index * 75;

            // Main floating appearance
            el.style.position = 'fixed';
            el.style.left = '50%';
            el.style.top = '-80px';
            el.style.transform = 'translateX(-50%)';
            el.style.zIndex = '9999';
            el.style.minWidth = '250px';
            el.style.maxWidth = '90vw';
            el.style.width = 'auto';
            el.style.margin = '0';
            el.style.borderRadius = '14px';
            el.style.boxShadow = '0 14px 26px rgba(0,0,0,0.35)';
            el.style.opacity = '0';
            el.style.pointerEvents = 'auto';
            el.style.color = '#fff';
            el.style.border = '1px solid rgba(255,255,255,0.3)';
            el.style.backgroundColor = 'rgba(255, 0, 200, 0.88)';
            el.style.backdropFilter = 'blur(8px)';
            el.style.transition = 'opacity 0.45s ease, top 0.45s ease';

            requestAnimationFrame(() => {
                el.style.top = `${finalTop}px`;
                el.style.opacity = '1';
            });
        });
    }

    function autoHideFlash() {
        const flashSelectors = ['.alert', '.flash-msg'];
        const flashElements = Array.from(document.querySelectorAll(flashSelectors.join(',')));
        if (!flashElements.length) return;

        styleFlashElements(flashElements);

        setTimeout(() => {
            flashElements.forEach(el => {
                el.style.opacity = '0';
                el.style.transform = 'translateX(-50%) translateY(-10px)';
                setTimeout(() => {
                    if (el.parentNode) {
                        el.parentNode.removeChild(el);
                    }
                }, 400);
            });
        }, 4100);
    }

    autoHideFlash();
});

