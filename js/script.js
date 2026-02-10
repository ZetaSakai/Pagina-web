document.addEventListener("DOMContentLoaded", function() {

    const enlacesMenu = document.querySelectorAll(".navbar ul li a");

    enlacesMenu.forEach(enlace => {
        enlace.addEventListener("mouseenter", () => {
            enlace.style.transform = "scale(1.15)";
        });

        enlace.addEventListener("mouseleave", () => {
            enlace.style.transform = "scale(1)";
        });
    });

    const productos = document.querySelectorAll(".product-1");

    productos.forEach(producto => {
        producto.addEventListener("mouseenter", () => {
            producto.style.transform = "scale(1.05)";
            producto.style.boxShadow = "0 10px 25px rgba(0,0,0,0.4)";
        });

        producto.addEventListener("mouseleave", () => {
            producto.style.transform = "scale(1)";
            producto.style.boxShadow = "none";
        });
    });

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
                    el.style.transitionDelay = (index >= 0 ? index * 70 : 0) + 'ms';
                    el.classList.add('reveal');
                    obs.unobserve(el);
                }
            });
        }, { threshold: 0.12 });

        elements.forEach(el => observer.observe(el));
    }

    initRevealOnScroll();
    // Close mobile menu when a nav link is clicked
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

