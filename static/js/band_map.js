(function () {
    const clamp = (value, minimum, maximum) => Math.min(Math.max(value, minimum), maximum);
    const JPEG_MIME_TYPE = "image/jpeg";

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

    document.querySelectorAll("[data-festival-map]").forEach((mapNode) => {
        const viewport = mapNode.querySelector("[data-map-viewport]");
        const canvas = mapNode.querySelector("[data-map-canvas]");
        const zoomInButton = mapNode.querySelector("[data-map-zoom-in]");
        const zoomOutButton = mapNode.querySelector("[data-map-zoom-out]");
        const clearPinButton = mapNode.querySelector("[data-map-pin-clear]");
        const draftPin = mapNode.querySelector("[data-map-draft-pin]");
        const statusNode = mapNode.querySelector("[data-map-status]");
        const sharedPins = Array.from(mapNode.querySelectorAll("[data-map-shared-pin]"));
        const mapXInput = document.getElementById(mapNode.dataset.mapXInput);
        const mapYInput = document.getElementById(mapNode.dataset.mapYInput);

        if (!viewport || !canvas) {
            return;
        }

        let currentZoom = Number.parseFloat(canvas.style.getPropertyValue("--map-zoom")) || 1;

        const setMapStatus = (message, state = "") => {
            if (!statusNode) {
                return;
            }

            statusNode.textContent = message;
            statusNode.dataset.state = state;
        };

        const getZoomBounds = () => ({
            minimum: Number(mapNode.dataset.mapMinZoom || 1),
            maximum: Number(mapNode.dataset.mapMaxZoom || 2.6),
        });

        const setZoom = (value, anchor = null) => {
            const { minimum, maximum } = getZoomBounds();
            const zoom = clamp(Number(value) || minimum, minimum, maximum);
            const previousWidth = canvas.offsetWidth || 1;
            const previousHeight = canvas.offsetHeight || 1;
            let focusX = (viewport.scrollLeft + viewport.clientWidth / 2) / previousWidth;
            let focusY = (viewport.scrollTop + viewport.clientHeight / 2) / previousHeight;
            let viewportX = viewport.clientWidth / 2;
            let viewportY = viewport.clientHeight / 2;

            if (anchor) {
                const canvasRect = canvas.getBoundingClientRect();
                const viewportRect = viewport.getBoundingClientRect();
                focusX = clamp((anchor.clientX - canvasRect.left) / previousWidth, 0, 1);
                focusY = clamp((anchor.clientY - canvasRect.top) / previousHeight, 0, 1);
                viewportX = anchor.clientX - viewportRect.left;
                viewportY = anchor.clientY - viewportRect.top;
            }

            currentZoom = zoom;
            canvas.style.setProperty("--map-zoom", zoom.toFixed(2));

            window.requestAnimationFrame(() => {
                viewport.scrollLeft = focusX * canvas.offsetWidth - viewportX;
                viewport.scrollTop = focusY * canvas.offsetHeight - viewportY;
            });
        };

        const setDraftPin = (x, y) => {
            if (!draftPin || !mapXInput || !mapYInput) {
                return;
            }

            const normalizedX = clamp(x, 0, 100);
            const normalizedY = clamp(y, 0, 100);
            const xValue = normalizedX.toFixed(3);
            const yValue = normalizedY.toFixed(3);

            mapXInput.value = xValue;
            mapYInput.value = yValue;
            draftPin.style.setProperty("--pin-x", `${xValue}%`);
            draftPin.style.setProperty("--pin-y", `${yValue}%`);
            draftPin.hidden = false;
            setMapStatus("Map pin set.", "success");
        };

        const clearDraftPin = () => {
            if (mapXInput) {
                mapXInput.value = "";
            }
            if (mapYInput) {
                mapYInput.value = "";
            }
            if (draftPin) {
                draftPin.hidden = true;
            }
            setMapStatus("No map pin selected.");
        };

        let pointerStart = null;
        let pinchState = null;
        let ignoreTapUntil = 0;

        const getTouchDistance = (touches) => {
            const firstTouch = touches[0];
            const secondTouch = touches[1];
            return Math.hypot(
                secondTouch.clientX - firstTouch.clientX,
                secondTouch.clientY - firstTouch.clientY
            );
        };

        const getTouchCenter = (touches) => ({
            clientX: (touches[0].clientX + touches[1].clientX) / 2,
            clientY: (touches[0].clientY + touches[1].clientY) / 2,
        });

        canvas.addEventListener("pointerdown", (event) => {
            if (!draftPin || event.button > 0) {
                return;
            }

            pointerStart = {
                id: event.pointerId,
                x: event.clientX,
                y: event.clientY,
            };
        });

        canvas.addEventListener("pointerup", (event) => {
            if (!pointerStart || pointerStart.id !== event.pointerId || Date.now() < ignoreTapUntil) {
                pointerStart = null;
                return;
            }

            const movement = Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y);
            pointerStart = null;
            if (movement > 8) {
                return;
            }

            const rect = canvas.getBoundingClientRect();
            const x = ((event.clientX - rect.left) / rect.width) * 100;
            const y = ((event.clientY - rect.top) / rect.height) * 100;
            setDraftPin(x, y);
        });

        canvas.addEventListener("pointercancel", () => {
            pointerStart = null;
        });

        viewport.addEventListener(
            "touchstart",
            (event) => {
                if (event.touches.length !== 2) {
                    return;
                }

                pinchState = {
                    distance: getTouchDistance(event.touches),
                    zoom: currentZoom || getZoomBounds().minimum,
                };
                pointerStart = null;
            },
            { passive: true }
        );

        viewport.addEventListener(
            "touchmove",
            (event) => {
                if (!pinchState || event.touches.length !== 2) {
                    return;
                }

                event.preventDefault();
                const nextDistance = getTouchDistance(event.touches);
                if (pinchState.distance <= 0 || nextDistance <= 0) {
                    return;
                }

                const zoom = pinchState.zoom * (nextDistance / pinchState.distance);
                setZoom(zoom, getTouchCenter(event.touches));
            },
            { passive: false }
        );

        const endPinch = (event) => {
            if (!pinchState || event.touches.length >= 2) {
                return;
            }

            pinchState = null;
            pointerStart = null;
            ignoreTapUntil = Date.now() + 350;
        };

        viewport.addEventListener("touchend", endPinch, { passive: true });
        viewport.addEventListener("touchcancel", endPinch, { passive: true });

        if (zoomInButton) {
            zoomInButton.addEventListener("click", () => {
                setZoom(currentZoom + Number(mapNode.dataset.mapZoomStep || 0.1));
            });
        }

        if (zoomOutButton) {
            zoomOutButton.addEventListener("click", () => {
                setZoom(currentZoom - Number(mapNode.dataset.mapZoomStep || 0.1));
            });
        }

        if (clearPinButton) {
            clearPinButton.addEventListener("click", clearDraftPin);
        }

        sharedPins.forEach((pin) => {
            pin.addEventListener("click", (event) => {
                event.stopPropagation();
                const isOpen = pin.classList.contains("festival-map__pin--active");

                sharedPins.forEach((otherPin) => {
                    otherPin.classList.remove("festival-map__pin--active");
                    otherPin.setAttribute("aria-expanded", "false");
                });

                if (!isOpen) {
                    pin.classList.add("festival-map__pin--active");
                    pin.setAttribute("aria-expanded", "true");
                }
            });
        });

        setZoom(currentZoom);
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

    document.querySelectorAll("[data-photo-compression-form]").forEach((form) => {
        const photoInputs = Array.from(form.querySelectorAll("[data-compress-photo]"));
        const statusNode = form.querySelector("[data-photo-compression-status]");
        const submitButtons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
        const maxEdge = Number.parseInt(form.dataset.photoMaxEdge, 10) || 1280;
        const quality = clamp(Number.parseFloat(form.dataset.photoQuality) || 0.6, 0.1, 0.95);

        const setStatus = (message, state = "") => {
            if (!statusNode) {
                return;
            }

            statusNode.textContent = message;
            statusNode.dataset.state = state;
        };

        const setSubmitting = (isSubmitting) => {
            form.setAttribute("aria-busy", isSubmitting ? "true" : "false");
            submitButtons.forEach((button) => {
                button.disabled = isSubmitting;
            });
        };

        form.addEventListener("submit", async (event) => {
            if (form.dataset.photoCompressionComplete === "true") {
                return;
            }

            const selectedPhotoInputs = photoInputs.filter((input) => input.files && input.files[0]);
            if (selectedPhotoInputs.length === 0) {
                return;
            }

            if (!isPhotoCompressionSupported()) {
                return;
            }

            event.preventDefault();
            setSubmitting(true);
            setStatus("Preparing photos...", "pending");

            try {
                for (const input of selectedPhotoInputs) {
                    const sourceFile = input.files[0];
                    if (!shouldCompressPhoto(sourceFile)) {
                        continue;
                    }

                    try {
                        const compressedFile = await compressPhoto(sourceFile, maxEdge, quality);
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(compressedFile);
                        input.files = dataTransfer.files;
                    } catch (error) {
                        // Keep the original photo when the browser cannot decode it.
                    }
                }

                form.dataset.photoCompressionComplete = "true";
                form.submit();
            } catch (error) {
                form.dataset.photoCompressionComplete = "true";
                form.submit();
            }
        });
    });
})();

function isAppleMobileDevice() {
    return (
        /iPhone|iPad|iPod/i.test(window.navigator.userAgent) ||
        (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1)
    );
}

function isPhotoCompressionSupported() {
    return Boolean(
        window.DataTransfer &&
            window.File &&
            window.URL &&
            window.HTMLCanvasElement &&
            HTMLCanvasElement.prototype.toBlob
    );
}

function shouldCompressPhoto(file) {
    if (!file) {
        return false;
    }

    const fileName = (file.name || "").toLowerCase();
    const mimeType = (file.type || "").toLowerCase();
    return !(
        mimeType === "image/heic" ||
        mimeType === "image/heif" ||
        fileName.endsWith(".heic") ||
        fileName.endsWith(".heif")
    );
}

function compressPhoto(file, maxEdge, quality) {
    return loadPhoto(file).then((image) => {
        const scale = Math.min(1, maxEdge / Math.max(image.naturalWidth, image.naturalHeight));
        const width = Math.max(1, Math.round(image.naturalWidth * scale));
        const height = Math.max(1, Math.round(image.naturalHeight * scale));
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("2d");

        canvas.width = width;
        canvas.height = height;
        if (!context) {
            URL.revokeObjectURL(image.src);
            return Promise.reject(new Error("Canvas is not available."));
        }

        context.drawImage(image, 0, 0, width, height);
        URL.revokeObjectURL(image.src);

        return new Promise((resolve, reject) => {
            canvas.toBlob(
                (blob) => {
                    if (!blob) {
                        reject(new Error("Photo compression failed."));
                        return;
                    }

                    resolve(
                        new File([blob], `${getFileStem(file.name)}.jpg`, {
                            type: JPEG_MIME_TYPE,
                            lastModified: Date.now(),
                        })
                    );
                },
                JPEG_MIME_TYPE,
                quality
            );
        });
    });
}

function loadPhoto(file) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => {
            URL.revokeObjectURL(image.src);
            reject(new Error("Photo could not be loaded."));
        };
        image.src = URL.createObjectURL(file);
    });
}

function getFileStem(filename) {
    const cleanedName = filename.trim().replace(/\.[^/.]+$/, "");
    return cleanedName || "photo";
}
