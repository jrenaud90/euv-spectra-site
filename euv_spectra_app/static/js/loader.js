const loader = document.querySelector("#loading");
const overlay = document.getElementById("overlay");
const overlayBox = document.getElementById("overlay-box");
const overlayTitle = document.getElementById("overlay-title");
const overlayText = document.getElementById("overlay-text");

const loadingMessages = {
    search: {
        title: 'Querying Databases',
        text: 'Hang tight! External catalog lookups can take a moment.',
    },
    modal: {
        title: 'Searching the PEGASUS Grid',
        text: 'Preparing matching models and spectra.',
    },
    admin: {
        title: 'Updating Admin State',
        text: 'Refreshing Pegasus metadata and database state.',
    },
};

let loadingTimer = null;


function showLoading(mode) {
    if (!loader || !overlay || !overlayBox || !overlayTitle || !overlayText) {
        return;
    }

    const message = loadingMessages[mode] || loadingMessages.search;
    loader.classList.add("display");
    overlay.style.display = "block";
    overlayBox.style.display = "block";
    overlayTitle.textContent = message.title;
    overlayText.textContent = message.text;
    overlayText.style.display = "block";
}

function displayLoading(mode) {
    if (loadingTimer !== null) {
        window.clearTimeout(loadingTimer);
    }
    loadingTimer = window.setTimeout(function () {
        showLoading(mode);
        loadingTimer = null;
    }, 1000);
    return true;
}

function hideLoading() {
    if (loadingTimer !== null) {
        window.clearTimeout(loadingTimer);
        loadingTimer = null;
    }
    if (!loader || !overlay || !overlayBox || !overlayText) {
        return;
    }
    loader.classList.remove("display");
    overlay.style.display = "none";
    overlayBox.style.display = "none";
    overlayText.style.display = "none";
}


window.addEventListener('pageshow', hideLoading);