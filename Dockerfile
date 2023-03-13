FROM python:latest
WORKDIR /src
COPY requirements.txt /src/
RUN pip install -r /src/requirements.txt
COPY . /src
