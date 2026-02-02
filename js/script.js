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

});

