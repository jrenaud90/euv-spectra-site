const nameInput = document.querySelector('#name-form-input-group');
const searchBtn = document.querySelector('#name-form-submit');
const searchNameInput = document.querySelector('#name-form-input-group');
const LOOKUP_DELAY_MS = 700;

let timeoutId;
let activeRequestController = null;
let latestLookupToken = 0;

nameInput.addEventListener('input', checkName);

function runPopovers() {
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        var popover = new bootstrap.Popover(popoverTriggerEl);
        popover.show(); // show the popover immediately
        return popover;
    });
}

function disposePopover() {
    const popover = bootstrap.Popover.getInstance(searchNameInput);
    if (popover) {
        popover.dispose();
    }
}

function setPopoverMessage(message) {
    if (searchNameInput.value.length === 0) {
        disposePopover();
        return;
    }

    searchNameInput.setAttribute('data-bs-toggle', 'popover');
    searchNameInput.setAttribute('data-bs-trigger', 'manual');
    searchNameInput.setAttribute('data-bs-placement', 'top');
    searchNameInput.setAttribute('data-bs-content', message);
    runPopovers();
}

function setLoadingState() {
    searchBtn.setAttribute('disabled', '');
    searchNameInput.classList.remove('found', 'not-found');
    searchNameInput.style.color = '';
    setPopoverMessage('Checking Sesame / SIMBAD...');
}

function setResolvedState(name) {
    searchBtn.removeAttribute('disabled');
    searchNameInput.classList.remove('not-found');
    searchNameInput.classList.add('found');
    searchNameInput.style.color = 'seagreen';
    setPopoverMessage(`${name} resolved by SESAME (SIMBAD).`);
}

function setNotResolvedState(name) {
    searchBtn.setAttribute('disabled', '');
    searchNameInput.classList.remove('found');
    searchNameInput.classList.add('not-found');
    searchNameInput.style.color = 'tomato';
    setPopoverMessage(`${name} not resolved.`);
}

function resetLookupState() {
    searchBtn.setAttribute('disabled', '');
    searchNameInput.classList.remove('found', 'not-found');
    searchNameInput.style.color = '';
    disposePopover();
}

function lookupName(name, lookupToken) {
    if (activeRequestController) {
        activeRequestController.abort();
    }

    activeRequestController = new AbortController();

    fetch(`https://cds.unistra.fr/cgi-bin/nph-sesame/-oIx/~S?${encodeURIComponent(name)}`, {
        signal: activeRequestController.signal,
    })
        .then(response => response.text())
        .then(xmlString => {
            // Ignore late responses so older partial queries cannot overwrite newer input.
            if (lookupToken !== latestLookupToken || searchNameInput.value.trim() !== name) {
                return;
            }

            const parser = new DOMParser();
            const xmlDoc = parser.parseFromString(xmlString, 'text/xml');
            const resolver = xmlDoc.querySelector('Resolver');

            if (resolver) {
                setResolvedState(name);
            } else {
                setNotResolvedState(name);
            }
        })
        .catch(error => {
            if (error.name === 'AbortError') {
                return;
            }

            if (lookupToken !== latestLookupToken || searchNameInput.value.trim() !== name) {
                return;
            }

            // Network failures should not leave the form stuck in a misleading success state.
            searchBtn.setAttribute('disabled', '');
            searchNameInput.classList.remove('found');
            searchNameInput.classList.add('not-found');
            searchNameInput.style.color = 'tomato';
            setPopoverMessage('Resolver lookup failed. Please try again.');
        });
}

function checkName() {
    const name = nameInput.value.trim();

    disposePopover();
    clearTimeout(timeoutId);

    if (activeRequestController) {
        activeRequestController.abort();
        activeRequestController = null;
    }

    if (name.length === 0) {
        resetLookupState();
        return;
    }

    const lookupToken = ++latestLookupToken;
    setLoadingState();

    // Debouncing keeps us from hammering the external resolver on every keystroke.
    timeoutId = setTimeout(() => {
        lookupName(name, lookupToken);
    }, LOOKUP_DELAY_MS);
}


// function checkName() {
//     const name = nameInput.value;
//     popover = bootstrap.Popover.getInstance(searchNameInput);
//     if (popover) {
//         popover.dispose()
//     } 
//     if (searchNameInput.value.length !== 0) {
//         searchNameInput.setAttribute('data-bs-toggle', 'popover');
//         searchNameInput.setAttribute('data-bs-trigger', 'manual');
//         searchNameInput.setAttribute('data-bs-placement', 'top');
//         searchNameInput.setAttribute('data-bs-content', 'Loading...')
//     } else {
//         popover.dispose();
//     }

//     // Clear the previous timeout
//     clearTimeout(timeoutId);

//     // Set a new timeout to execute the function after 2 seconds of inactivity
//     timeoutId = setTimeout(() => {
//         fetch(`https://cds.unistra.fr/cgi-bin/nph-sesame/-oIx/~S?${name}`)
//             .then(response => response.text())
//             .then(xmlString => {
//                 // Rest of your code...
//                 const parser = new DOMParser();
//                 const xmlDoc = parser.parseFromString(xmlString, "text/xml");
//                 const resolver = xmlDoc.querySelector("Resolver");
//                 if (resolver) {
//                     console.log(resolver);
//                     searchBtn.removeAttribute('disabled');
//                     searchNameInput.classList.remove('not-found');
//                     searchNameInput.classList.add('found');
//                     searchNameInput.style.color = 'seagreen';

//                     popover = bootstrap.Popover.getInstance(searchNameInput);
//                     if (popover) {
//                         popover.dispose()
//                     } 
//                     if (searchNameInput.value.length !== 0) {
//                         searchNameInput.setAttribute('data-bs-toggle', 'popover');
//                         searchNameInput.setAttribute('data-bs-trigger', 'manual');
//                         searchNameInput.setAttribute('data-bs-placement', 'top');
//                         searchNameInput.setAttribute('data-bs-content', `${searchNameInput.value} resolved by SESAME (SIMBAD).`)
//                     } else {
//                         popover.dispose();
//                     }
//                 } else {
//                     searchBtn.setAttribute('disabled', '');
//                     searchNameInput.classList.remove('found');
//                     searchNameInput.classList.add('not-found');
//                     searchNameInput.style.color = 'tomato';

//                     popover = bootstrap.Popover.getInstance(searchNameInput);
//                     if (popover) {
//                         popover.dispose();
//                     } 
//                     if (searchNameInput.value.length !== 0) {
//                         searchNameInput.setAttribute('data-bs-toggle', 'popover');
//                         searchNameInput.setAttribute('data-bs-trigger', 'manual');
//                         searchNameInput.setAttribute('data-bs-placement', 'top');
//                         searchNameInput.setAttribute('data-bs-content', `${searchNameInput.value} not resolved.`);
//                     } else {
//                         popover.dispose();
//                     }
//                 }
//                 runPopovers();
//             });
//         runPopovers();
//         }, 2000); // Delay set to 2 seconds (2000 milliseconds)
//     }

//     fetch(`https://cds.unistra.fr/cgi-bin/nph-sesame/-oIx/~S?${name}`)
//         .then(response => response.text())
//             .then(xmlString => {
//                 const parser = new DOMParser();
//                 const xmlDoc = parser.parseFromString(xmlString, "text/xml");
//                 const resolver = xmlDoc.querySelector("Resolver");
//                 if (resolver) {
//                     console.log(resolver);
//                     searchBtn.removeAttribute('disabled');
//                     searchNameInput.classList.remove('not-found');
//                     searchNameInput.classList.add('found');
//                     searchNameInput.style.color = 'seagreen';

//                     popover = bootstrap.Popover.getInstance(searchNameInput);
//                     if (popover) {
//                         popover.dispose()
//                     } 
//                     if (searchNameInput.value.length !== 0) {
//                         searchNameInput.setAttribute('data-bs-toggle', 'popover');
//                         searchNameInput.setAttribute('data-bs-trigger', 'manual');
//                         searchNameInput.setAttribute('data-bs-placement', 'top');
//                         searchNameInput.setAttribute('data-bs-content', `${searchNameInput.value} resolved by SESAME (SIMBAD).`)
//                     } else {
//                         popover.dispose();
//                     }
//                 } else {
//                     searchBtn.setAttribute('disabled', '');
//                     searchNameInput.classList.remove('found');
//                     searchNameInput.classList.add('not-found');
//                     searchNameInput.style.color = 'tomato';

//                     popover = bootstrap.Popover.getInstance(searchNameInput);
//                     if (popover) {
//                         popover.dispose();
//                     } 
//                     if (searchNameInput.value.length !== 0) {
//                         searchNameInput.setAttribute('data-bs-toggle', 'popover');
//                         searchNameInput.setAttribute('data-bs-trigger', 'manual');
//                         searchNameInput.setAttribute('data-bs-placement', 'top');
//                         searchNameInput.setAttribute('data-bs-content', `${searchNameInput.value} not resolved.`);
//                     } else {
//                         popover.dispose();
//                     }
//                 }
//                 runPopovers();
//             })
//     runPopovers();
// }