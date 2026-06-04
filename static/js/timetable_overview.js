(function () {
    const scheduleSections = Array.from(document.querySelectorAll("[data-schedule-date]"));
    if (!scheduleSections.length) {
        return;
    }

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
})();

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
