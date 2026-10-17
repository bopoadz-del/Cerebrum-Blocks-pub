FROM cerebrum-block-base:latest

WORKDIR /app
COPY requirements.txt block.json block.py ./
RUN pip install --no-cache-dir -r requirements.txt
# run.py is provided by cerebrum-block-base:latest
ENTRYPOINT ["python", "/app/run.py"]
