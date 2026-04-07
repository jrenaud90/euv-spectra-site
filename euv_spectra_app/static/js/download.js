function checkDirectory(filename, model){
    fetch(`check-directory/${filename}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Unable to check file availability (${response.status})`);
            }
            return response.json();
        })
        .then(data => {
            if (data.exists) {
                window.location = `download/${filename}/${model}`
            } else {
                const errorBox = document.getElementById(`${filename}-errorbox`)
                if (!errorBox) {
                    return;
                }
                errorBox.style.display = 'block';
                errorBox.textContent = 'This FITS file is not available yet for download.'
                setTimeout(function() { errorBox.style.display = 'none'; }, 5000);
            }
        })
        .catch(() => {
            const errorBox = document.getElementById(`${filename}-errorbox`)
            if (!errorBox) {
                return;
            }
            errorBox.style.display = 'block';
            errorBox.textContent = 'Unable to check FITS availability right now. Please try again.'
            setTimeout(function() { errorBox.style.display = 'none'; }, 5000);
        });
}