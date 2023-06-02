import math
import os
import re
import json
import openai
import tiktoken
from dotenv import load_dotenv
from enum import Enum
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

# Data filename and Google Sheets URL
TEST_DATA_FILENAME = os.environ["TEST_DATA_FILENAME"]
SPREADSHEET_URL = os.environ["SPREADSHEET_URL"]

# For OpenAI API
openai.api_key = os.environ["OPENAI_API_KEY"]

# Total number of tokens used
total_num_tokens_used = 0

# For Google Sheets API
SERVICE_ACCOUNT_FILENAME = os.environ["SERVICE_ACCOUNT_FILENAME"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILENAME, scopes=SCOPES)
sheets_api = build("sheets", "v4", credentials=credentials)

# MathBot system prompt
MATHBOT_SYSTEM_PROMPT = """
You are a math tutor helping a student understand a problem. Hints may be provided for some problems; while you should not quote these hints directly, use them to guide the conversation if available.
Break down the solution into five steps and guide the student through each, using questions (75%) and conceptual explanations (25%). Your questions should be designed such that each one requires at most a single arithmetic equation to answer. If a question naturally involves more than one equation, break it down into multiple questions.
Ensure that your responses do not exceed 100 words. Use HTML bold tags to emphasize key words or phrases.
Never provide the final mathematical answer or reference the hints. When your question requires an arithmetic calculation, conclude your response with a single arithmetic equation that solves your question, enclosed in double angle brackets (e.g., YOUR_RESPONSE <<1+2=3>>).
Do not include equations that cannot be validated (e.g., algebraic equations), as these will be parsed and validated by a Python function. For the same reason, avoid using mathematical constants or symbols, such as π or e, in the equations. Convert these to numbers when necessary.
These equations will not be shown to the student, so don't reference them.
If a response either confirms the student's final correct answer or provides the final correct answer to the problem, you should acknowledge this by ending your response with a line stating the final answer in the format "#### {Answer}". For example, if the student correctly answers "1 + 2" with "3", and this is the final answer, your response could look like this: "Excellent work, you've got it! The answer to 1 + 2 is indeed 3.\n#### 3". Ensure to follow this practice only when you're certain that the final correct answer has been reached.
Let's work this out in a step by step way to be sure we have the right answer.
"""

# StudentBot system prompt
STUDENTBOT_SYSTEM_PROMPT = """
You are a K-12 student engaging with a math tutor to solve a problem. The tutor will guide you through the process using questions and concept explanations.
Your task is to answer these questions to the best of your ability, while keeping your responses as concise and direct as possible, like the example below:

Example:
Tutor: Can you tell me what is the sum of 1 and 2?
You: 3

Let's work this out in a step by step way to be sure we have the right answer.
"""

# keys: ts (message timestamp), values: equation string
equation_dict = {}


def process_equation(equation):
    # Split the equation into left and right parts
    parts = equation.split("=")
    if len(parts) != 2:  # If equation can't be split into exactly two parts, return as is
        return equation

    # Clean whitespaces
    left, right = parts[0].replace(" ", ""), parts[1].strip()

    # Check if left is a number, or if right is not a number
    if re.fullmatch(r"^-?\d+(\.\d+)?$", left) or not re.fullmatch(r"^-?\d+(\.\d+)?$", right):
        return equation

    # Create a safe environment for eval and try to evaluate the left part
    safe_env = dict(__builtins__=None, math=math)
    try:
        result = eval(left, safe_env)
    except (NameError, SyntaxError, TypeError):
        return equation

    # Format the result based on its type
    if isinstance(result, int):
        return f"{left}={result}"
    elif isinstance(result, float):
        truncated_result = int(result * 10000) / 10000
        return f"{left}={truncated_result:.4f}…" if result != truncated_result else f"{left}={truncated_result}"


def num_tokens_from_messages(messages, model="gpt-4"):
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo":
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0301")
    elif model == "gpt-4":
        return num_tokens_from_messages(messages, model="gpt-4-0314")
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif model == "gpt-4-0314":
        tokens_per_message = 3
        tokens_per_name = 1
    else:
        raise NotImplementedError(f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens.""")
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


def make_openai_request(messages):
    global total_num_tokens_used
    total_num_tokens_used += num_tokens_from_messages(messages)
    error_message = ""

    for _ in range(3): # Try up to 3 times
        try:
            openai_response = openai.ChatCompletion.create(
                model="gpt-4",
                temperature=0.4,
                messages=messages
            )
            response_text = openai_response.choices[0].message.content
            return response_text
        except Exception as e:
            error_message = str(e)
            print(f"\nOpenAI API Error: {error_message}\nTrying again...\n")
    
    # If all 3 attempts failed, raise the error
    raise Exception(error_message)


def get_mathbot_answer(question):
    try:
        # Initial messages
        mathbot_messages = [{"role": "system", "content": MATHBOT_SYSTEM_PROMPT}, {"role": "user", "content": question}]
        studentbot_messages = [{"role": "system", "content": STUDENTBOT_SYSTEM_PROMPT}, {"role": "assistant", "content": question}]
        reached_final_answer = False
        found_equation_error = False

        print(f"\n• StudentBot: {question}")

        while len(mathbot_messages) <= 20:
            # Ask the next question to MathBot
            mathbot_answer = make_openai_request(mathbot_messages)

            # Remove trailing spaces just in case
            mathbot_answer = mathbot_answer.rstrip()

            # First, find if MathBot answer ends with ">>"
            if mathbot_answer.endswith(">>"):
                # Find all matches of equations
                matches = re.findall("<<(.+?)>>", mathbot_answer)
                if len(matches) == 1:
                    # Extract the equation
                    equation = matches[0]

                    # Process the equation
                    processed_equation = process_equation(equation)

                    # Replace the old equation in MathBot answer with the processed equation
                    mathbot_answer = re.sub("<<.+?>>$", f"<<{processed_equation}>>", mathbot_answer)
                else:
                    found_equation_error = True
            elif "<<" in mathbot_answer or ">>" in mathbot_answer:
                found_equation_error = True

            # Append the MathBot answer to both messages (hide the equation to the StudentBot)
            mathbot_messages.append({"role": "assistant", "content": mathbot_answer})
            studentbot_messages.append({"role": "user", "content": re.sub("<<.*?>>", "", mathbot_answer)})

            print(f"• MathBot: {mathbot_answer}")

            # Break if final answer has been reached
            if "####" in mathbot_answer:
                reached_final_answer = True
                break
            
            # Pass the MathBot response to StudentBot
            studentbot_answer = make_openai_request(studentbot_messages)

            # Append the StudentBot answer to both messages
            mathbot_messages.append({"role": "user", "content": studentbot_answer})
            studentbot_messages.append({"role": "assistant", "content": studentbot_answer})

            print(f"• StudentBot: {studentbot_answer}")

        # The whole conversation
        conversation = ""

        for message in mathbot_messages[1:]:
            if message["role"] == "user":
                conversation += f"\n• StudentBot: {message['content']}"
            elif message["role"] == "assistant":
                conversation += f"\n• MathBot: {message['content']}"

        if not reached_final_answer or found_equation_error:
            raise Exception(conversation)

        return conversation
    except Exception as e:
        return f"Error: {e}"


def get_jsonl_data(filename):
    data = []
    with open(filename, "r") as f:
        for line in f:
            data.append(json.loads(line))
    return data


def write_test_data_to_sheet():
    try:
        # Load the test data
        test_data = get_jsonl_data(TEST_DATA_FILENAME)

        # Extract the spreadsheet_id from the URL
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", SPREADSHEET_URL)
        if match is None:
            raise ValueError("Invalid Google Sheets URL")
        spreadsheet_id = match.group(1)

        # Call the Sheets API
        sheet = sheets_api.spreadsheets()

        # Clear the sheet
        sheet.values().clear(
            spreadsheetId=spreadsheet_id,
            range="Sheet1",
        ).execute()

        # Prepare the header
        header = [["Question", "Answer", "MathBot", "Evaluation", "Results"]]

        # Update the header
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!A1:E1",
            valueInputOption="USER_ENTERED",
            body={"values": header},
        ).execute()

        # Prepare the data
        data = [[item["question"], item["answer"]] for item in test_data]

        # Update the data
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"Sheet1!A2:B{len(data)+1}",
            valueInputOption="USER_ENTERED",
            body={"values": data},
        ).execute()

        # Prepare the evaluation formulas for column D
        evaluation_formulas = [[f'=IF(OR(ISBLANK(B{i+2}), ISBLANK(C{i+2})), "", IFERROR(IF(VALUE(SUBSTITUTE(MID(B{i+2}, FIND("#### ", B{i+2}) + 5, LEN(B{i+2})), ",", "")) = VALUE(SUBSTITUTE(MID(C{i+2}, FIND("#### ", C{i+2}) + 5, LEN(C{i+2})), ",", "")), "Correct", "Wrong"), "Error"))'] for i in range(len(data))]

        # Update the evaluation formulas in column D
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"Sheet1!D2:D{len(evaluation_formulas)+1}",
            valueInputOption="USER_ENTERED",
            body={"values": evaluation_formulas},
        ).execute()

        # Prepare the results summary for E2 cell
        results_formula = [[
            '= "Total Count: " & (COUNTIF(D:D, "Correct") + COUNTIF(D:D, "Wrong") + COUNTIF(D:D, "Error")) & CHAR(10) &' 
            '"Correct Count: " & COUNTIF(D:D, "Correct") & CHAR(10) &' 
            '"Wrong Count: " & COUNTIF(D:D, "Wrong") & CHAR(10) &' 
            '"Error Count: " & COUNTIF(D:D, "Error") & CHAR(10) &' 
            '"Valid Score: " & IFERROR(ROUND((COUNTIF(D:D, "Correct") / (COUNTIF(D:D, "Correct") + COUNTIF(D:D, "Wrong"))*100), 2), 0) & "%" & CHAR(10) &' 
            '"Total Score: " & IFERROR(ROUND((COUNTIF(D:D, "Correct") / (COUNTIF(D:D, "Correct") + COUNTIF(D:D, "Wrong") + COUNTIF(D:D, "Error"))*100), 2), 0) & "%"'
        ]]
        
        # Update the results summary in E2 cell
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!E2",
            valueInputOption="USER_ENTERED",
            body={"values": results_formula},
            ).execute()
        
        # Return True if successful
        return True
    
    except Exception as e:
        # Print the error message and return False
        print(f"\nError: {e}")
        return False


def write_mathbot_answers(max_num_answers):
    try:
        # Extract the spreadsheet_id from the URL
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", SPREADSHEET_URL)
        if match is None:
            raise ValueError("Invalid Google Sheets URL")
        spreadsheet_id = match.group(1)

        # Call the Sheets API
        sheet = sheets_api.spreadsheets()

        # Get the questions from the "Question" column
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Sheet1!A2:A").execute()
        questions = result.get("values", [])

        # Get the answers from the "MathBot" column
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="Sheet1!C2:C").execute()
        mathbot_answers = result.get("values", [])

        num_answers = 0

        for i, question in enumerate(questions):
            if not question[0]:  # If the question cell is empty, stop the loop
                break
            if not num_answers < max_num_answers:  # If the maximum number of answers is reached, stop the loop
                break

            # If a valid (non-error) answer is already there, skip this question
            if i < len(mathbot_answers) and mathbot_answers[i][0].strip(): # and not mathbot_answers[i][0].strip().startswith("Error: ")
                continue

            print(f"\n--------------------------------------------------\nAnswering the question {i+1} (A{i+2}): {question[0][:20]}...")
            mathbot_answer = get_mathbot_answer(question[0])  # Get the MathBot answer
            print(f"\nMathBot's answer:\n{mathbot_answer}")
            
            # Write the MathBot answer to the "MathBot" column
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f"Sheet1!C{2+i}",
                valueInputOption="USER_ENTERED",
                body={"values": [[mathbot_answer]]},
            ).execute()

            num_answers += 1
            print(f"\nAnswered {num_answers} out of the {max_num_answers} questions ({format(total_num_tokens_used, ',')} tokens have been used so far)")

        # Return True if successful
        return True

    except Exception as e:
        # Print the error message and return False
        print(f"\nError: {e}")
        return False


def interact_with_user():
    # Ask the first question
    response = input("Do you want to write the test data to the spreadsheet?\n(Note: this will clear the existing spreadsheet content) y/N: ").lower()
    if response == 'y':
        if write_test_data_to_sheet():
            print("\nTest data has been successfully written to the spreadsheet.")
        else:
            print("\nAn error occurred while writing the test data to the spreadsheet.")

    # Ask the second question
    num_questions_str = input("\nEnter the number of questions you want MathBot to answer (default: 10): ")
    num_questions = int(num_questions_str) if num_questions_str.isdigit() else 10
    if write_mathbot_answers(num_questions):
        print(f"\nSuccessfully answered {num_questions} questions and the responses have been written to the spreadsheet.")
        print(f"\nA total of {format(total_num_tokens_used, ',')} tokens have been used.")
    else:
        print("\nAn error occurred while MathBot was answering the questions.")


# Call the function when the script runs
if __name__ == "__main__":
    interact_with_user()