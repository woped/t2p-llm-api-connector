# Use an official Python runtime as a base image
FROM python:3.10-slim

# Set the working directory in the container to /app
WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary files
COPY app.py .
COPY requirements.txt .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable if needed
ENV NAME World

# Run app.py when the container launches
CMD ["python", "app.py"]
