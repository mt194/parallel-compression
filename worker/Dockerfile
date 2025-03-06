FROM python:3.13
ENV WORKER_NUMBER=4
WORKDIR /usr/local/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN apt update && apt install -y
# RUN apt install dnsutils netcat-openbsd -y
# RUN apt install curl -y


COPY huffman-compression.py ./huffman-compression.py
COPY odyssey.txt ./odyssey.txt

RUN useradd app
USER app
# ENTRYPOINT ["tail", "-f", "/dev/null"]
CMD ["python", "huffman-compression.py"]

