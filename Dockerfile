# syntax=docker/dockerfile:1

FROM python:3.9

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy the code into a folder named app
ADD . /app

# switch the working directory to app
WORKDIR /app

# Install App dependencies
RUN pip3 install -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 5002

# Run app.py when the container launches
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "app:app", "--forwarded-allow-ips=*"]