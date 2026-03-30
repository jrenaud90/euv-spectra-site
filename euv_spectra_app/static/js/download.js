function checkDirectory(filename, model){
    fetch(`check-directory/${filename}`)
        .then(response => response.json())
        .then(data => {
            if (data.exists) {
                // Do something if the directory exists
                console.log(`${filename} exists`)
                console.log(filename)
                window.location = `download/${filename}/${model}`
            } else {
                // Do something if the directory does not exist
                console.log(`${filename} does not exist`)
                errorBox = document.getElementById(`${filename}-errorbox`)
                if (errorBox.style.display = 'none') {
                    errorBox.style.display = 'block';
                }
                errorBox.innerHTML = 'File does not exist yet, unable to download'
                setTimeout(function() { errorBox.style.display = 'none'; }, 5000);
            }
        });
}