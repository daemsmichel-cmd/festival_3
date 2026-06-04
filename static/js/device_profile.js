(function () {
    const rememberedValueFields = document.querySelectorAll("[data-remember-last-value]");
    hydrateRememberedFields(rememberedValueFields);
    persistRememberedFields(rememberedValueFields);
    syncDeviceDisplayName();
    window.addEventListener("storage", syncDeviceDisplayName);
})();

function hydrateRememberedFields(fields) {
    fields.forEach((field) => {
        const storageKey = field.dataset.rememberLastValue;
        if (!storageKey || field.value) {
            return;
        }

        const rememberedValue = readFromLocalStorage(storageKey);
        if (rememberedValue) {
            field.value = rememberedValue;
        }
    });
}

function persistRememberedFields(fields) {
    fields.forEach((field) => {
        const storageKey = field.dataset.rememberLastValue;
        if (!storageKey) {
            return;
        }

        const saveValue = () => {
            writeToLocalStorage(storageKey, field.value.trim());
            syncDeviceDisplayName();
        };

        field.addEventListener("input", saveValue);
        field.addEventListener("change", saveValue);

        if (field.form) {
            field.form.addEventListener("submit", saveValue);
        }
    });
}

function syncDeviceDisplayName() {
    const displayName = readFromLocalStorage("festival-finder-display-name").trim();

    document.querySelectorAll("[data-device-display-name]").forEach((node) => {
        const valueNode = node.querySelector("[data-device-display-name-value]");
        if (!valueNode || !displayName) {
            node.hidden = true;
            return;
        }

        valueNode.textContent = displayName;
        node.hidden = false;
    });
}

function readFromLocalStorage(key) {
    try {
        return window.localStorage.getItem(key) || "";
    } catch {
        return "";
    }
}

function writeToLocalStorage(key, value) {
    try {
        window.localStorage.setItem(key, value);
    } catch {
        // Ignore storage failures and keep the form usable.
    }
}
