FROM python:3.13
WORKDIR /usr/local/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


COPY api-service.py ./api-service.py

RUN useradd app
USER app

CMD ["flask", "--app", "api-service", "run", "--port=8080", "--host=0.0.0.0"]

EXPOSE 8080