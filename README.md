# llm-api-connector

This repository is for the source code handling the web-api call of llm providers as GPT from Open AI

## Prerequisites

1. Create a virtual environment:
    ```bash
    python -m venv .venv
    ```

2. Activate the virtual environment:
    - **Windows:**
      ```bash
      .venv\Scripts\activate
      ```
    - **macOS/Linux:**
      ```bash
      source .venv/bin/activate
      ```

3. Install the requirements:
    ```bash
    pip install -r requirements/dev.txt
    ```

After cloning this repository, it's essential to [set up git hooks](https://github.com/woped/woped-git-hooks/blob/main/README.md#activating-git-hooks-after-cloning-a-repository) to ensure project standards.

## Running the Application Locally

To run the Flask application in development mode, make sure your `.venv` is activated and set the necessary environment variables:

**Windows (PowerShell):**
```powershell
$env:FLASK_APP = "llm-api-connector.py"
$env:FLASK_DEBUG = "1"
flask run
```

**macOS/Linux:**
```bash
export FLASK_APP=llm-api-connector.py
export FLASK_DEBUG=1
flask run
```

This will start the Flask development server with auto-reloading enabled, and the application will be accessible at http://localhost:5000. 

> **Note:** In older versions of Flask, you might have used `FLASK_ENV=development`. However, since Flask 2.3 (and this project uses Flask 3.1+), `FLASK_ENV` has been removed. Setting `FLASK_DEBUG=1` is now the correct way to enable development mode.

## Running the Application with Docker

To build the docker image, navigate to the root directory of the project and run the following command:
```bash
docker build -t llm-api-connector .
```

To run the application in docker, run the following command:
```bash
docker run -p 5000:5000 llm-api-connector
```
The application will be accessible at http://localhost:5000.

## Testing
To test the code, navigate to the test folder and run the following command:
```bash
coverage run -m unittest discover
```
You can then view the coverage report by running:
```bash
coverage report
```
if you want to see the coverage in html format, run:
```bash
coverage html
```
and open the htmlcov/index.html file in your browser.
