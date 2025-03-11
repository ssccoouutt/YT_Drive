FROM python:3.10-slim

  # Install system dependencies
  RUN apt-get update && apt-get install -y ffmpeg

  # Copy project files
  COPY . /app
  WORKDIR /app

  # Install Python dependencies
  RUN pip install -r requirements.txt

  # Run the bot
  CMD ["python", "main.py"]