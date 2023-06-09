# MathBot QA GSM8K
A Python program designed to test the problem-solving abilities of [MathBot](https://github.com/CarnegieLearningWeb/math-bot), a GPT-4-based math tutor chatbot, using the [GSM8K dataset](https://github.com/openai/grade-school-math) of grade school math problems.

## Features
- **Interactive problem-solving**: MathBot interacts with a student chatbot, guiding the student through the problem-solving process. The test program simulates the role of the student, asking questions and following MathBot's guidance, adhering to a set of clearly defined interaction rules.
- **Python-validated equations**: When necessary for the accuracy of the response, MathBot includes a Python-validated equation in its response. This equation is hidden from the student and aids in ensuring the accuracy of MathBot's responses.
- **Structured guidance**: MathBot provides structured guidance, breaking down the solution into five steps and guiding the student through each, using a mix of questions and conceptual explanations. The interaction is designed to mimic a real-world math tutor guiding a K-12 student.
- **Automated documentation**: The dataset (problems and correct answers), prompts used for MathBot/StudentBot, and the resulting conversations for solving each problem are automatically written to a Google Sheets document. This feature allows easy viewing and analysis of the test results.

## Installation
1. Clone this repository:

```bash
git clone https://github.com/CarnegieLearningWeb/math-bot-qa-gsm8k.git
cd math-bot-qa-gsm8k
```
2. Install the required packages:

```bash
pip install -r requirements.txt
```
3. Create a .env file in the root directory of the project and set the following variables:

```bash
OPENAI_API_KEY=your_openai_api_key
TEST_DATA_FILENAME=your_test_dataset_filename
SPREADSHEET_URL=your_google_sheets_url
SERVICE_ACCOUNT_FILENAME=your_service_account_filename
```

## Usage
1. Create a Google Sheets document and share it with your Google service account. Make sure to give the service account "Editor" permissions.
2. Run the program:
```
python main.py
```
3. When prompted, enter "Y" if you want to write the test data (problems and answers) to the spreadsheet. If you don't want to do this, just press enter.
4. When prompted, enter the number of questions you want MathBot to answer, and then press enter to start the test program.