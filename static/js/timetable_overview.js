(function () {
    const STORAGE_KEY = "festival-finder:overview-scroll-state";
    const scheduleSections = Array.from(document.querySelectorAll("[data-schedule-date]"));
    if (!scheduleSections.length) {
        return;
    }

    if ("scrollRestoration" in window.history) {
        window.history.scrollRestoration = "manual";
    }

    const savedState = readSavedState();
    if (savedState) {
        restoreSavedState(savedState);
    } else {
        scrollToCurrentFestivalDay();
    }

    let saveFrameId = null;
    const scheduleStateSave = () => {
        if (saveFrameId !== null) {
            return;
        }

        saveFrameId = window.requestAnimationFrame(() => {
            saveFrameId = null;
            saveOverviewState();
        });
    };

    document.addEventListener(
        "click",
        (event) => {
            if (event.target.closest(".schedule-band")) {
                saveOverviewState();
            }
        },
        true
    );

    window.addEventListener("scroll", scheduleStateSave, { passive: true });
    window.addEventListener("pagehide", saveOverviewState);
    window.addEventListener("beforeunload", saveOverviewState);

    scheduleSections.forEach((section) => {
        const scroller = section.querySelector(".schedule-scroll");
        if (!scroller) {
            return;
        }

        scroller.addEventListener("scroll", scheduleStateSave, { passive: true });
    });

    function saveOverviewState() {
        try {
            const sectionScrolls = {};

            scheduleSections.forEach((section) => {
                const scroller = section.querySelector(".schedule-scroll");
                const dateKey = section.dataset.scheduleDate;
                if (!scroller || !dateKey) {
                    return;
                }

                sectionScrolls[dateKey] = scroller.scrollLeft;
            });

            sessionStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({
                    windowScrollY: window.scrollY || 0,
                    sectionScrolls,
                })
            );
        } catch {
            // sessionStorage can be unavailable in some privacy contexts.
        }
    }

    function readSavedState() {
        try {
            const rawState = sessionStorage.getItem(STORAGE_KEY);
            if (!rawState) {
                return null;
            }

            const parsedState = JSON.parse(rawState);
            if (!parsedState || typeof parsedState !== "object") {
                return null;
            }

            return parsedState;
        } catch {
            return null;
        }
    }

    function restoreSavedState(state) {
        const windowScrollY = Number(state.windowScrollY);
        const sectionScrolls =
            state.sectionScrolls && typeof state.sectionScrolls === "object" ? state.sectionScrolls : {};

        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                window.scrollTo(0, Number.isFinite(windowScrollY) && windowScrollY >= 0 ? windowScrollY : 0);

                scheduleSections.forEach((section) => {
                    const scroller = section.querySelector(".schedule-scroll");
                    const dateKey = section.dataset.scheduleDate;
                    const savedScrollLeft = dateKey ? sectionScrolls[dateKey] : null;
                    if (!scroller || typeof savedScrollLeft !== "number" || !Number.isFinite(savedScrollLeft)) {
                        return;
                    }

                    scroller.scrollLeft = Math.max(savedScrollLeft, 0);
                });
            });
        });
    }

    function scrollToCurrentFestivalDay() {
        const now = new Date();
        const scheduleDateCandidates = buildScheduleDateCandidates(now);
        const targetSection =
            scheduleSections.find((section) => scheduleDateCandidates.includes(section.dataset.scheduleDate)) ||
            null;

        if (!targetSection) {
            return;
        }

        const scroller = targetSection.querySelector(".schedule-scroll");
        const table = targetSection.querySelector(".schedule-table");
        if (!scroller || !table) {
            return;
        }

        const dayStart = Number(table.dataset.dayStartMinutes || "630");
        const dayEnd = Number(table.dataset.dayEndMinutes || "1680");
        const pixelsPerMinute = Number(table.dataset.pixelsPerMinute || "3");
        const currentFestivalMinute = getFestivalDayMinutes(now);
        const clampedMinute = Math.min(Math.max(currentFestivalMinute, dayStart), dayEnd);
        const left = Math.max((clampedMinute - dayStart) * pixelsPerMinute - scroller.clientWidth * 0.35, 0);
        const maxScrollLeft = Math.max(scroller.scrollWidth - scroller.clientWidth, 0);

        window.requestAnimationFrame(() => {
            scroller.scrollLeft = Math.min(left, maxScrollLeft);
        });
    }

    function buildScheduleDateCandidates(now) {
        const candidates = [];
        const festivalDate = new Date(now);
        if (getFestivalDayMinutes(now) >= 24 * 60) {
            festivalDate.setDate(festivalDate.getDate() - 1);
        }
        candidates.push(formatDateKey(festivalDate));

        const calendarDate = formatDateKey(now);
        if (!candidates.includes(calendarDate)) {
            candidates.push(calendarDate);
        }

        return candidates;
    }

    function getFestivalDayMinutes(now) {
        const minutes = now.getHours() * 60 + now.getMinutes();
        if (minutes <= 4 * 60) {
            return minutes + 24 * 60;
        }
        return minutes;
    }

    function formatDateKey(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }
})();
