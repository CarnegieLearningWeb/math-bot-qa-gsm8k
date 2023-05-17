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

# MathBot initial system prompt
SYSTEM_PROMPT = """
Classify the user input according to the following categories and respond with only the category number (e.g., 1):

1. Calculation-based questions: Questions requiring arithmetic or computational solutions, excluding coding-related questions.
2. Conceptual/Informational questions: Questions about mathematical concepts or facts without calculations, excluding coding-related questions.
3. Math problem generation: Questions asking for a new math problem to be generated.
4. Greetings/Social: Greetings and social interactions including introduction.
5. Off-topic: Statements or questions unrelated to math, including coding-related questions.
6. Miscellaneous: Gibberish, unrelated questions, or difficult to classify inputs.

Again, only the category number should be your entire response, and nothing else should be included in the response.
Let's work this out in a step by step way to be sure we have the right answer.
"""

# keys: ts (message timestamp), values: {category: number, expressions: string (optional)}
message_category = {}

class Category(Enum):
    UNDEFINED = 0
    CALCULATION_BASED = 1
    CONCEPTUAL_INFORMATIONAL = 2
    MATH_PROBLEM_GENERATION = 3
    GREETINGS_SOCIAL = 4
    OFF_TOPIC = 5
    MISCELLANEOUS = 6


def get_altered_system_prompt(system_prompt_category, is_calculated=False, equations=""):
    altered_system_prompt = ""
    if system_prompt_category == Category.CALCULATION_BASED.value:
        if is_calculated is False:
            altered_system_prompt = """
You are a researcher tasked with identifying where calculation is needed in the user input. Please follow these guidelines when answering:
1. Do not perform the calculation. Instead, your entire response should be a list of the arithmetic expressions that need to be calculated step by step, separated by commas, and wrap them with square brackets, like the examples below:

Examples ("Q" indicates question, and your entire response should start and end with square brackets as shown in the examples):

Q: What is 1 + 2?
[1 + 2]

Q: What is the result of subtracting two times three from seven?
[2 * 3, 7 - 2 * 3]

Q: What is 1 + 2, and 3 + 4?
[1 + 2, 3 + 4]

Q: What is (1 + 2) * (3 + 4)?
[1 + 2, 3 + 4, (1 + 2) * (3 + 4)]

Q: What is "x" in the equation "1 + 2x = 7"?
[7 - 1, (7 - 1) / 2]

Q: What is 2 to the power of 3?
[2 ** 3]

2. Do not include expressions that cannot be calculated (e.g., algebraic expressions) because these expressions will be parsed and converted to equations by a Python function.
3. For the same reason, avoid using mathematical constants or symbols, such as π or e, in the arithmetic expressions. Only use numbers and basic arithmetic operations that Python can interpret with the eval function. Convert mathematical constants or symbols to numbers when applicable.

Again, when you provide the list of arithmetic expressions, that should be the entire response, and nothing else should be included in the response. If the list is empty, your response should be [].
Let's work this out in a step by step way to be sure we have the right list of expressions.
"""
        else:
            altered_system_prompt = f"""
You are MathBot, a K-12 math tutor chatbot tasked with guiding students through math questions. Please follow these guidelines when answering:

1. Provide step by step instructions on how to solve the problem, making use of the provided context of pre-calculated equations. Rather than giving the direct answer, demonstrate how you arrived at the answer through multiple steps.
2. If the provided context is insufficient for accurately answering the question or solving the problem, respond with, "Sorry, I don't have enough information to solve that."
3. Incorporate the context naturally in your responses without explicitly mentioning it. Make your responses seem as if you've performed the calculations yourself.
4. At the end of your response, provide the final answer on a new line, prefixed with "#### ", ensuring there is a space after the ####. The answer should be a numerical value only, with no units or additional characters. Here's an example ("Q" indicates question):

Q: What is 1 + 2?
First, take the number 1.
Next, add the number 2 to it.
So, 1 + 2 equals 3.
#### 3

Let's work this out in a step by step way to be sure we have the right instructions for the student.

Context:
{equations}
"""
    elif system_prompt_category == Category.CONCEPTUAL_INFORMATIONAL.value:
        altered_system_prompt = """
You are MathBot, a K-12 math tutor chatbot tasked with guiding students through math questions. Please follow these guidelines when answering:

1. Explain the reason for your answer, or how you arrived at the answer in multiple steps when applicable.
2. Provide the base knowledge for students to better understand your answer when applicable.
3. If the question is incomplete, unclear to answer, or unsolvable, ask for clarification or explain why you cannot answer it.

Let's work this out in a step by step way to be sure we have the right instructions for the student.
"""
    elif system_prompt_category == Category.MATH_PROBLEM_GENERATION.value:
        altered_system_prompt = """
You are a researcher tasked with generating math problems as requested in the user input. Follow these guidelines when generating:

1. When generating math problems, ensure they can be explained and solved in a step-by-step manner. Adjust the difficulty of the problem according to the user's age or grade level if provided.
2. For word problems, use language that is clear, easy to understand, and safe for K-12 students.
3. If the user's request for a math problem is unclear or lacks necessary information, ask for clarification or provide an explanation of why the problem cannot be generated.

Let's work this out in a step by step way to be sure we have the right problems for the student.
"""
    elif system_prompt_category == Category.GREETINGS_SOCIAL.value:
        altered_system_prompt = """
You are MathBot, a K-12 math tutor chatbot tasked with guiding students through math questions. Please follow these guidelines when answering:

1. Maintain a friendly and engaging conversation with students.
2. Encourage and motivate students to foster a positive attitude towards math when appropriate.
3. Ensure all responses are safe and appropriate for K-12 students, and gently guide students to use respectful and appropriate language if necessary.

Let's work this out in a step by step way to be sure we have the right instructions for the student.
"""
    elif system_prompt_category == Category.OFF_TOPIC.value:
        altered_system_prompt = """
You are MathBot, a K-12 math tutor chatbot tasked with guiding students through math questions. Please follow these guidelines when answering:

1. If the user input is not related to math, say something like "I'm here to help with math-related questions. Can we focus on a math problem or concept?"
2. If the user input is related to math but not directly (e.g., coding-related questions), say something like "My expertise is in math topics. Could we focus on a question that's directly related to math?"
3. If the user input is incomplete or unclear to answer, ask for clarification or explain why you cannot answer it.

Let's work this out in a step by step way to be sure we have the right instructions for the student.
"""
    elif system_prompt_category == Category.MISCELLANEOUS.value:
        altered_system_prompt = """
You are MathBot, a K-12 math tutor chatbot tasked with guiding students through math questions. Please follow these guidelines when answering:

1. If the user input is an emotional interjection, empathize and provide supportive responses when appropriate.
2. If the user input is gibberish (i.e., nonsensical or random characters), gently notify the user that the input was not understood and ask for a clear question or statement.
3. If the user input is unclear or ambiguous but still appears to be an attempt at a meaningful question or statement, ask for clarification.

Let's work this out in a step by step way to be sure we have the right instructions for the student.
"""
    return altered_system_prompt


def convert_arithmetic_expressions(input_str):
    # Remove square brackets and split by comma
    expressions = input_str[1:-1].split(", ")
    output = []
    for exp in expressions:
        exp = exp.strip()
        try:
            # Validate expression with eval()
            result = eval(exp)
            # Format the result based on its type (integer or floating-point)
            if isinstance(result, int):
                formatted_result = str(result)
            elif isinstance(result, float):
                formatted_result = f"{result:.4f}".rstrip("0").rstrip(".")
                if float(formatted_result) != result:
                    formatted_result += "…"
            else:
                # If the result is not a number, skip this expression
                continue
            # Append the expression and its result to the output list
            output.append(f"{exp} = {formatted_result}")
        except:
            # If the expression is invalid or cannot be evaluated, skip it
            pass
    return "\n".join(output)


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


def make_openai_request(messages, system_prompt_category=Category.UNDEFINED.value, is_calculated=False):
    global total_num_tokens_used
    total_num_tokens_used += num_tokens_from_messages(messages)
    openai_response = openai.ChatCompletion.create(
        model="gpt-4",
        temperature=0.4,
        messages=messages
    )
    response_text = openai_response.choices[0].message.content
    if system_prompt_category == Category.UNDEFINED.value:
        if response_text.isdigit():
            system_prompt_category = int(response_text)
            altered_system_prompt = get_altered_system_prompt(system_prompt_category)
            if altered_system_prompt:
                messages[0]["content"] = altered_system_prompt
                return make_openai_request(messages, system_prompt_category, is_calculated=False)
    elif system_prompt_category == Category.CALCULATION_BASED.value and is_calculated is False:
        if response_text.startswith("[") and response_text.endswith("]"):
            equations = convert_arithmetic_expressions(response_text)
            altered_system_prompt = get_altered_system_prompt(system_prompt_category, is_calculated=True, equations=equations)
            if altered_system_prompt:
                messages[0]["content"] = altered_system_prompt
                return make_openai_request(messages, system_prompt_category, is_calculated=True)
    else:
        return response_text
    
    # If something unexpected happened
    raise Exception(f"response_text: {response_text}, system_prompt_category: {system_prompt_category}, is_calculated: {is_calculated}")


def get_mathbot_answer(question):
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
        answer = make_openai_request(messages)
        return answer
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
        evaluation_formulas = [[f'=IF(OR(ISBLANK(B{i+2}), ISBLANK(C{i+2})), "", IFERROR(IF(SUBSTITUTE(MID(B{i+2}, FIND("#### ", B{i+2}) + 5, LEN(B{i+2})), ",", "") = SUBSTITUTE(MID(C{i+2}, FIND("#### ", C{i+2}) + 5, LEN(C{i+2})), ",", ""), "Correct", "Wrong"), "Error"))'] for i in range(len(data))]

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
            if i < len(mathbot_answers) and mathbot_answers[i][0].strip() and not mathbot_answers[i][0].strip().startswith("Error: "):
                continue

            print(f"\n--------------------------------------------------\nAnswering the question {i+1} (A{i+2}): {question[0][:20]}...")
            mathbot_answer = get_mathbot_answer(question[0])  # Get the MathBot answer
            print(f"\nMathBot's answer: {mathbot_answer}")
            
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