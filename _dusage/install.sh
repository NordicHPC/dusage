#!/usr/bin/env bash

export PIP_REQUIRE_VIRTUALENV=true

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
