# llm-api-connector
This repository is for the source code handling the web-api call of llm providers as GPT from Open AI

## Preqrequisites
- Install the requirements:
    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

To run the application, you need to execute the `app.py` script. You can do this by running the following command in your terminal:
```bash
python app.py
```
This will start the Flask server and the application will be accessible at 
    http://localhost:5000.

## Running the Application with Docker
To build the docker image, navigate to the root directory of the project and run the following command:
```bash
docker build -t llm-api-connector .
```
To run the application in docker, run the following command:
```bash
docker run -p 5000:5000 llm-api-connector
```
The application will be accessible at 
    http://localhost:5000.

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
