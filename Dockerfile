FROM python:3.8-slim

RUN  apt-get update -y && \
     apt-get upgrade

RUN apt-get install -y zip

WORKDIR /app

ADD . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080
