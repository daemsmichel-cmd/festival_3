(function () {
    document.querySelectorAll(".geo-button").forEach((button) => {
        button.addEventListener("click", () => {
            const latInput = document.getElementById(button.dataset.latInput);
            const lngInput = document.getElementById(button.dataset.lngInput);
            const statusNode = button.parentElement.querySelector("[data-geo-status]");

            const setStatus = (message, state = "") => {
                if (statusNode) {
                    statusNode.textContent = message;
                    statusNode.dataset.state = state;
                }
            };

            if (!navigator.geolocation) {
                setStatus("Location access is not available here.", "error");
                return;
            }

            if (!window.isSecureContext) {
                setStatus("Location access is not available here.", "error");
                return;
            }

            setStatus("Finding your position...", "pending");
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    latInput.value = position.coords.latitude.toFixed(6);
                    lngInput.value = position.coords.longitude.toFixed(6);
                    setStatus("Position added.", "success");
                },
                (error) => {
                    setStatus(error.message || "Could not fetch your position.", "error");
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                }
            );
        });
    });

    document.querySelectorAll(".native-maps-app-link").forEach((link) => {
        link.addEventListener("click", (event) => {
            if (!isAppleMobileDevice()) {
                return;
            }

            const iosAppUrl = link.dataset.iosAppUrl;
            if (!iosAppUrl) {
                return;
            }

            event.preventDefault();

            let fallbackTimer = window.setTimeout(() => {
                window.location.href = link.href;
            }, 900);

            const cancelFallback = () => {
                if (!document.hidden) {
                    return;
                }
                if (fallbackTimer) {
                    window.clearTimeout(fallbackTimer);
                    fallbackTimer = null;
                }
                document.removeEventListener("visibilitychange", cancelFallback);
                window.removeEventListener("pagehide", cancelFallback);
            };

            document.addEventListener("visibilitychange", cancelFallback);
            window.addEventListener("pagehide", cancelFallback);
            window.location.href = iosAppUrl;
        });
    });
})();

function isAppleMobileDevice() {
    return (
        /iPhone|iPad|iPod/i.test(window.navigator.userAgent) ||
        (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1)
    );
}
